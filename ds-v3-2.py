# -*- coding: utf-8 -*-
"""
@File    : ds-v3-2.py
@Author  : qy
@Date    : 2025/8/11 10:27
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, AsyncGenerator, Optional
import json
import httpx
import logging
from policy_utils import get_policy_info, parts
from policy_prompt import build_policy_prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://mcc-pre.3xmt.com/gateway/ai-service/v1/chat/completions"
API_KEY = "sk-bFcPcwS7J7oP6e8LGo"

app = FastAPI()

# --功能1：用列表存储公司申请记录，保持顺序 -------------------
global_company_info_store: Dict[str, List[Dict[str, Any]]] = {}
MAX_RECORDS_PER_COMPANY = 3

print(global_company_info_store)


def empty_company_info_dict() -> Dict[str, Any]:
    return {
        "name": "",
        "org": "",
        "cap": "",
        "size": "",
        "description": "",
        "establish_time": "",
        "regist_loc": "",
        "tax_loc": "",
        "person_size": None,
        "cap_size": None,
        "credit_rating": None,
        "credit_code": "",
        "industry": [],
        "primary_product": "",
        "key_focus_areas": "",
        "honors": "",
        "qualifications": "",
        "rank": [],
        "tags": [],
        "r_d_staff_count": None,
        "revenue_last_year": None,
        "revenue_growth_rate_last_year": None,
        "r_d_expense_last_year": None,
        "total_assets_last_year": None,
        "asset_liability_ratio_last_year": None,
        "total_output_last_year": None,

        "extra_fields": {}
    }


def merge_company_info(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    merged = old.copy()
    for k, v in new.items():
        if v is None:
            continue    #跳过这条数据，不做更新 .跳过当前循环的这一次
        if isinstance(v, list) and len(v) == 0:
            continue
        if v == "":
            continue

        if k == "extra_fields":
            old_extra = merged.get("extra_fields", {})
            if not isinstance(old_extra, dict):
                old_extra = {}
            if isinstance(v, dict):
                # 合并两个字典，后者覆盖同名字段
                merged["extra_fields"] = {**old_extra, **v}
            else:
                # 新的不是dict时保持旧的
                merged["extra_fields"] = old_extra
        else:
            merged[k] = v
    return merged

# --功能2：修剪列表中多余记录，删最早 -------------------
def trim_records(company_name: str):
    records = global_company_info_store.get(company_name)
    if not records:
        return
    while len(records) > MAX_RECORDS_PER_COMPANY:
        removed = records.pop(0)  # 删除最早（列表头）
        logger.info(f"删除公司 {company_name} 最旧申请记录 part_id={removed.get('part_id')}")


async def llm_stream_generator(prompt: str, part_id: str, company_info: Dict[str, Any]) -> AsyncGenerator[str, None]:
    payload = {
        "stream": True,
        "model": "deepseek-v3",
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "metadata": {
                    "company_info": company_info,
                    "part_id": part_id,
                }
            }
        ]
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    accumulated_content = ""
    final_id = None
    final_model = None

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", API_URL, json=payload, headers=headers) as response:
            async for line_bytes in response.aiter_lines():
                if not line_bytes:
                    continue
                line_str = line_bytes.lstrip("data:").strip()
                try:
                    data_json = json.loads(line_str)
                except json.JSONDecodeError:
                    continue
                if final_id is None:
                    final_id = data_json.get("id")
                if final_model is None:
                    final_model = data_json.get("model")
                choice = data_json.get("choices", [{}])[0]
                chunk = choice.get("delta", {}).get("content", "")
                if chunk:
                    accumulated_content += chunk
                finish_reason = choice.get("finish_reason")
                if finish_reason == "stop":
                    result_dict = {
                        "id": final_id,
                        "model": final_model,
                        "part_id": part_id,
                        "status": "done",
                        "data_content": accumulated_content,
                    }
                    yield f" {json.dumps(result_dict, ensure_ascii=False)}\n\n"
                    break



class MessageMetadata(BaseModel):
    company_info: Dict[str, Any]          # 公司信息
    part_id: str                          # 申报专项政策id
    update_flag: Optional[bool] = False   # 更新按钮
    source_part_id: Optional[str] = None  # 继承按钮


class Message(BaseModel):
    role: str
    content: str
    metadata: MessageMetadata


class FullRequest(BaseModel):
    stream: bool
    model: str
    messages: List[Message]


@app.post("/check_policy")
async def check_policy(request: FullRequest):
    message = request.messages[0]
    company_info_raw = message.metadata.company_info
    part_id = message.metadata.part_id
    update_flag = message.metadata.update_flag
    source_part_id = message.metadata.source_part_id

    # 1. 校验政策信息
    policy_info = get_policy_info(parts, part_id)
    if "error" in policy_info:
        raise HTTPException(status_code=404, detail='未找到该申报专项政策,请检查part_id是否正确。')

    # 2. 校验公司名
    company_name = company_info_raw.get("name", "")
    if not company_name:
        raise HTTPException(status_code=400, detail="company_info 必须包含 name 字段作为唯一标识。")

    if company_name not in global_company_info_store:
        global_company_info_store[company_name] = []

    company_records = global_company_info_store[company_name]
    logger.info(f"更新前，{company_name}的全部申请记录（{len(company_records)}条）: {company_records}")

    # 3. 找到是否已有该part_id记录
    idx = next((i for i, r in enumerate(company_records) if r["part_id"] == part_id), None)
    if idx is not None:
        # 有旧记录，删除旧记录
        old_record = company_records.pop(idx)
        old_info = old_record["company_info"]
        if update_flag:
            updated_info = merge_company_info(old_info, company_info_raw)
        else:
            updated_info = merge_company_info(empty_company_info_dict(), company_info_raw)
        # 新记录追加到尾部，表示最新
        company_records.append({
            "part_id": part_id,
            "company_info": updated_info
        })
    else:
        # 新记录
        if source_part_id:
            base_record = next((r for r in company_records if r["part_id"] == source_part_id), None)
            base_info = base_record["company_info"] if base_record else empty_company_info_dict()
        else:
            base_info = empty_company_info_dict()

        updated_info = merge_company_info(base_info, company_info_raw)
        company_records.append({
            "part_id": part_id,
            "company_info": updated_info
        })

    # 4. 修剪记录函数
    # trim_records(company_name)

    logger.info(f"修剪后，{company_name}的申请记录数: {len(company_records)}")
    logger.info(f"========最终记录内容: {company_records}")
    logger.info(f"========更新后公司信息======== name={company_name} part_id={part_id} info={updated_info}")

    # 5. 准备 prompt
    company_data = {
        k: v for k, v in updated_info.items()
        if v not in [None, ""] and (not isinstance(v, list) or len(v) > 0)
    }
    company_info_text = "\n".join(f"{k}: {v}" for k, v in company_data.items())
    policy_text = "\n".join(f"{k}: {v}" for k, v in policy_info.items())
    prompt = build_policy_prompt(company_info_text, policy_text)

    # 6. 调用大模型
    return StreamingResponse(
        llm_stream_generator(prompt, part_id, updated_info),
        media_type="application/json"
    )


if __name__ == '__main__':
    import uvicorn
    uvicorn.run("ds-v3-2:app", host="0.0.0.0", port=8500)
