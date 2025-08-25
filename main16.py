# -*- coding: utf-8 -*-
"""
@File    : 1_json_chunk.py
@Author  : qy
@Date    : 2025/8/22 18:27
"""
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, AsyncGenerator
import httpx
import logging
import json
import uuid
import asyncio
import time

from starlette.responses import StreamingResponse

from policy_utils import get_policy_info
from prompt import build_policy_elements_prompt, build_company_judgment_prompt, empty_company_info_dict
from recods_info import save_record, load_record

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://mcc-pre.3xmt.com/gateway/ai-service/v1/chat/completions"
API_KEY = "sk-bFcPcwS7J7oP6e8LGo"

app = FastAPI()

MAX_RECORDS_PER_COMPANY = 1000
global_company_info: Dict[str, List[Dict[str, Any]]] = {}

historical_records = load_record()
for r in historical_records:
    name = r["company_info"].get("name")
    if name:
        global_company_info.setdefault(name, []).append(r)


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


# ------------------- 模型流 -------------------
async def stream_model_response(prompt: str, buffer_size: int = 2, flush_interval: float = 0.06) -> AsyncGenerator[
    str, None]:
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
    finished = False

    async def fetch_model():
        nonlocal buffer, finished
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
                            finish_reason = data["choices"][0].get("finish_reason")
                            if finish_reason == "stop":
                                finished = True
                                break
                        except json.JSONDecodeError:
                            continue
        except httpx.RequestError:
            buffer += "[模型服务请求失败]"
            finished = True

    fetch_task = asyncio.create_task(fetch_model())

    try:
        while not finished or buffer:
            if buffer:
                out, buffer = buffer[:buffer_size], buffer[buffer_size:]
                yield out
            await asyncio.sleep(flush_interval)
        yield "\n"
    finally:
        fetch_task.cancel()
        await asyncio.sleep(0)



async def chunked_response(generator: AsyncGenerator[Dict[str, Any], None]):
    async def iterate():
        async for text_dict in generator:
            text_bytes = json.dumps(text_dict, ensure_ascii=False).encode("utf-8")
            output = b"data:" + text_bytes + b"\n\n" + b"\r\n"

            size = len(output) - 2
            size_hex = hex(size)[2:].encode("ascii") + b"\r\n"

#            yield size_hex
            yield output

        # 结束标志
#        yield b"0\r\n"
 #       yield b"\r\n"

    return StreamingResponse(iterate(), media_type="text/event-stream")



# ------------------- check_policy endpoint -------------------
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

    # 记录合并逻辑
    if req.uid:
        target_record = next((r for r in existing_records if r["uid"] == req.uid), None)
        if not target_record:
            raise HTTPException(status_code=404, detail="指定 uid 对应的记录不存在")
        merged_info = merge_company_info(target_record["company_info"], company_info)
        merged_policy_info = merge_company_info(target_record.get("policy_info", {}), policy_info)
        new_uid = str(uuid.uuid4())
        record = {
            "uid": new_uid,
            "part_id": req.part_id,
            "company_info": merged_info,
            "policy_info": merged_policy_info
        }
        if len(existing_records) >= MAX_RECORDS_PER_COMPANY:
            raise HTTPException(status_code=400, detail=f"该公司历史记录已达 {MAX_RECORDS_PER_COMPANY} 条")
        global_company_info.setdefault(company_name, []).append(record)
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
    save_record(record)

    policy_elements_prompt = build_policy_elements_prompt(req.part_id, policy_info)
    company_judgment_prompt = build_company_judgment_prompt(merged_info, policy_info)

    first_intro = "欢迎进入智能帮办环节，我可以为您提供智能匹配、智能体检、智能填报等环节的申报全流程智能辅助服务，您可以点击此处查看为您推荐的相关申报政策。您也可以直接告诉我想要申报的政策，由我提供智能体检服务。\n下面展示申请专项政策要素：\n"
    second_intro = "经AI对政策申报要求与贵司画像特征智能分析，您当前还不满足政策申报条件，还存在以下条件需要由您确认：\n"

    # ------------------- 事件流 -------------------
    session_id = str(uuid.uuid4())  # 整个请求的唯一 id
    created_ts = int(time.time())  # 时间戳
    choice_index = 0  # 全局 index 递增

    # ------------------- 事件流 -------------------
    async def event_stream() -> AsyncGenerator[Dict[str, Any], None]:
        nonlocal choice_index

        queue1: asyncio.Queue[str] = asyncio.Queue()
        queue2: asyncio.Queue[str] = asyncio.Queue()

        async def model_task(prompt: str, queue: asyncio.Queue):
            async for chunk in stream_model_response(prompt):
                await queue.put(chunk)
            await queue.put(None)

        task1 = asyncio.create_task(model_task(policy_elements_prompt, queue1))
        task2 = asyncio.create_task(model_task(company_judgment_prompt, queue2))

        # 打字机输出 JSON
        async def send_typing_text_json(text: str, speed: float = 0.06) -> AsyncGenerator[Dict[str, Any], None]:
            nonlocal choice_index
            buffer = text
            while buffer:
                out, buffer = buffer[:2], buffer[2:]
                chunk_data = {
                    "id": session_id,
                    "model": "deepseek-v3",
                    "created": created_ts,
                    "part_id": req.part_id,
                    "choices": [
                        {
                            "index": choice_index,
                            "finish_reason": None,
                            "message": {
                                "content": out,
                                "role": "assistant"
                            }
                        }
                    ]
                }
                choice_index += 1
                yield chunk_data
                await asyncio.sleep(speed)

        # 输出开头语1
        async for chunk in send_typing_text_json(first_intro):
            yield chunk

        # 消费模型1
        while True:
            chunk = await queue1.get()
            if chunk is None:
                break
            yield {
                "id": session_id,
                "model": "deepseek-v3",
                "created": created_ts,
                "part_id": req.part_id,
                "choices": [
                    {
                        "index": choice_index,
                        "finish_reason": None,
                        "message": {
                            "content": chunk,
                            "role": "assistant"
                        }
                    }
                ]
            }
            choice_index += 1

        # 空行分隔
        yield {
            "id": session_id,
            "model": "deepseek-v3",
            "created": created_ts,
            "part_id": req.part_id,
            "choices": [
                {
                    "index": choice_index,
                    "finish_reason": None,
                    "message": {"content": "", "role": "assistant"}
                }
            ]
        }
        choice_index += 1

        # 输出开头语2
        async for chunk in send_typing_text_json(second_intro):
            yield chunk

        # 消费模型2
        last_chunk = None
        while True:
            chunk = await queue2.get()
            if chunk is None:
                break
            last_chunk = chunk
            yield {
                "id": session_id,
                "model": "deepseek-v3",
                "created": created_ts,
                "part_id": req.part_id,
                "choices": [
                    {
                        "index": choice_index,
                        "finish_reason": None,
                        "message": {
                            "content": chunk,
                            "role": "assistant"
                        }
                    }
                ]
            }
            choice_index += 1

        # 最后一个 chunk finish_reason="stop"
        if last_chunk is not None:
            yield {
                "id": session_id,
                "model": "deepseek-v3",
                "created": created_ts,
                "part_id": req.part_id,
                "choices": [
                    {
                        "index": choice_index,
                        "finish_reason": "stop",
                        "message": {
                            "content": last_chunk,
                            "role": "assistant"
                        }
                    }
                ]
            }

    return await chunked_response(event_stream())


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app="main16:app", workers=1, host="0.0.0.0", port=8500, reload=False)
