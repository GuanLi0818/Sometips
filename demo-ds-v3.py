# -*- coding: utf-8 -*-
"""
@File    : ds-v3-sse.py
@Author  : qy
@Date    : 2025/8/20 10:25
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, AsyncGenerator
import httpx
import logging
import json
import uuid
import asyncio
from policy_utils import get_policy_info, parts, ori_data
from prompt import build_policy_elements_prompt, build_company_judgment_prompt, empty_company_info_dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://mcc-pre.3xmt.com/gateway/ai-service/v1/chat/completions"
API_KEY = "sk-bFcPcwS7J7oP6e8LGo"

app = FastAPI()

MAX_RECORDS_PER_COMPANY = 5
global_company_info: Dict[str, List[Dict[str, Any]]] = {}


def merge_company_info(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    merged = old.copy()
    for k, v in new.items():
        if k == "extra_fields":
            old_extra = merged.get("extra_fields", {})
            if not isinstance(old_extra, dict):
                old_extra = {}
            if isinstance(v, dict):
                merged["extra_fields"] = {**old_extra, **v}
        else:
            if v is not None and (v != "" and (not isinstance(v, list) or len(v) > 0)):
                merged[k] = v
    return merged

class Message(BaseModel):
    role: str
    content: str
    metadata: Dict[str, Any]

class NewCheckRequest(BaseModel):
    part_id: str
    uid: Optional[str] = None
    messages: List[Message]


async def stream_model_response(prompt: str, buffer_size: int = 20) -> AsyncGenerator[str, None]:
    """流式调用大模型，SSE 逐块返回 JSON，使用缓冲区收集输出直到达到指定长度"""
    payload = {
        "model": "deepseek-v3",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    buffer = ""
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", API_URL, json=payload, headers=headers) as response:
                async for line_bytes in response.aiter_lines():
                    if not line_bytes or not line_bytes.startswith("data:"):
                        continue
                    line_str = line_bytes[len("data:"):].strip()
                    if not line_str:
                        continue

                    try:
                        data = json.loads(line_str)
                        delta = data["choices"][0]["delta"].get("content", "")
                        if delta:
                            buffer += delta
                            # 当缓冲区达到指定长度或包含换行时，输出并清空缓冲区
                            if len(buffer) >= buffer_size or "\n" in buffer:
                                yield json.dumps({"content": buffer}, ensure_ascii=False)
                                buffer = ""
                        finish_reason = data["choices"][0].get("finish_reason")
                        if finish_reason == "stop":
                            if buffer:  # 输出剩余内容
                                yield json.dumps({"content": buffer}, ensure_ascii=False)
                            # 添加换行符作为第一个模型结束的标记
                            yield json.dumps({"content": "\n"}, ensure_ascii=False)
                            break
                    except json.JSONDecodeError:
                        continue

    except httpx.RequestError as e:
        logger.error(f"请求模型API失败: {e}")
        yield json.dumps({'error': '模型服务请求失败'}, ensure_ascii=False)


@app.post("/check_policy")
async def check_policy(req: NewCheckRequest):
    company_info = req.messages[0].metadata.get("company_info", {})
    policy_info = get_policy_info(req.part_id)
    if "error" in policy_info:
        raise HTTPException(status_code=404, detail='未找到该申报专项政策')

    company_name = company_info.get("name", "")
    if not company_name:
        raise HTTPException(status_code=400, detail="company_info 必须包含 name")

    existing_records = global_company_info.get(company_name, [])

    if req.uid:
        target_record = next((r for r in existing_records if r["uid"] == req.uid), None)
        if not target_record:
            raise HTTPException(status_code=404, detail="指定 uid 对应的记录不存在")
        merged_info = merge_company_info(target_record["company_info"], company_info)
        merged_policy_info = merge_company_info(target_record.get("policy_info", {}), policy_info)
        new_uid = str(uuid.uuid4())
        new_record = {
            "uid": new_uid,
            "part_id": req.part_id,
            "company_info": merged_info,
            "policy_info": merged_policy_info
        }
        if len(existing_records) >= MAX_RECORDS_PER_COMPANY:
            raise HTTPException(status_code=400, detail=f"该公司历史记录已达 {MAX_RECORDS_PER_COMPANY} 条")
        global_company_info.setdefault(company_name, []).append(new_record)
    else:
        if len(existing_records) >= MAX_RECORDS_PER_COMPANY:
            raise HTTPException(status_code=400, detail=f"该公司历史记录已达 {MAX_RECORDS_PER_COMPANY} 条")
        base_info = existing_records[-1]["company_info"] if existing_records else empty_company_info_dict()
        merged_info = merge_company_info(base_info, company_info)
        new_uid = str(uuid.uuid4())
        record = {
            "uid": new_uid,
            "part_id": req.part_id,
            "company_info": merged_info,
            "policy_info": policy_info
        }
        global_company_info.setdefault(company_name, []).append(record)

    policy_elements_prompt = build_policy_elements_prompt(req.part_id, policy_info)
    company_judgment_prompt = build_company_judgment_prompt(merged_info, policy_info)

    # 定义两个部分的开头语
    first_intro = "欢迎进入智能帮办环节，我可以为您提供智能匹配、智能体检、智能填报等环节的申报全流程智能辅助服务，您可以点击此处查看为您推荐的相关申报政策。您也可以直接告诉我想要申报的政策，由我提供智能体检服务。\n"
    second_intro = "经AI对政策申报要求与贵司画像特征智能分析，您当前还不满足政策申报条件，还存在以下条件需要由您确认；\n"

    async def event_stream() -> AsyncGenerator[str, None]:
        # 输出第一轮开头语
        yield f"data: {json.dumps({'content': first_intro}, ensure_ascii=False)}\n\n"

        # 输出第一个模型的结果（带缓冲）
        async for chunk in stream_model_response(policy_elements_prompt):
            yield f"data: {chunk}\n\n"

        # 输出第二轮开头语
        yield f"data: {json.dumps({'content': second_intro}, ensure_ascii=False)}\n\n"

        # 输出第二个模型的结果（带缓冲）
        async for chunk in stream_model_response(company_judgment_prompt):
            yield f"data: {chunk}\n\n"

        # 输出结束事件
        done_data = json.dumps({'status': 'done', 'uid': new_uid, 'part_id': req.part_id}, ensure_ascii=False)
        yield f"data: {done_data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == '__main__':
    import uvicorn
    uvicorn.run("demo-ds-v3:app", host="0.0.0.0", port=8500, reload=True)
