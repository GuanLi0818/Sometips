# -*- coding: utf-8 -*-
"""
@File    : ds-v3-main.py
@Author  : qy
@Date    : 2025/8/13
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import httpx
import logging
import json

from policy_utils import get_policy_info, parts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://mcc-pre.3xmt.com/gateway/ai-service/v1/chat/completions"
API_KEY = "sk-bFcPcwS7J7oP6e8LGo"

app = FastAPI()

# 最大保存记录数
MAX_RECORDS_PER_COMPANY = 10

# 全局公司申请记录存储（每个公司存列表，保存历史记录）
global_company_info: Dict[str, List[Dict[str, Any]]] = {}

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
        "r_d_expense_last_year": None,
        "revenue_last_year": None,
        "revenue_growth_rate_last_year": None,
        "total_assets_last_year": None,
        "asset_liability_ratio_last_year": None,
        "total_output_last_year": None,
        "extra_fields": {}
    }

def merge_company_info(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """新字段有值直接覆盖老字段，包括 extra_fields"""
    merged = old.copy()
    for k, v in new.items():
        if k == "extra_fields":
            old_extra = merged.get("extra_fields", {})
            if not isinstance(old_extra, dict):
                old_extra = {}
            if isinstance(v, dict):
                merged["extra_fields"] = {**old_extra, **v}  # 新字段覆盖老字段
        else:
            if v is not None and (v != "" and (not isinstance(v, list) or len(v) > 0)):
                merged[k] = v
    return merged

def deep_clean_dict(d: dict) -> dict:
    """递归清理字典中的空值: None, '', []"""
    if not isinstance(d, dict):
        return d
    cleaned = {}
    for k, v in d.items():
        if v is None or v == "":
            continue
        if isinstance(v, list):
            v = [deep_clean_dict(i) if isinstance(i, dict) else i for i in v]
            v = [i for i in v if i is not None and i != ""]
            if not v:
                continue
        elif isinstance(v, dict):
            v = deep_clean_dict(v)
            if not v:
                continue
        cleaned[k] = v
    return cleaned

class Message(BaseModel):
    role: str
    content: str
    metadata: Dict[str, Any]

class NewCheckRequest(BaseModel):
    part_id: str
    source_part_id: Optional[str] = None
    messages: List[Message]

def build_combined_prompt(company_info: Dict[str, Any], policy_info: Dict[str, Any]) -> str:
    company_info_text = "\n".join(f"{k}: {v}" for k, v in company_info.items())
    policy_text = "\n".join(f"{k}: {v}" for k, v in policy_info.items())
    prompt = f"""
你是一位精通政府政策解读和企业合规分析的专家。
请根据以下企业信息和政策条款，完成两步操作：

一、判断企业是否符合以下三项申报条件：
1. 申报对象（重点关注 org、cap、size、regist_loc、tax_loc、description）
2. 扶持领域（重点关注 key_focus_areas、industry、description、primary_product、tags、honors）
3. 申报条件（逐条对照政策条款）

二、判断规则：
- 必须依次判断“申报对象”“扶持领域”“申报条件”三项，无论前项是否符合，都要完成三项判断。
- 如果某项相关信息为空，默认该项符合。
- 判断仅基于提供的企业信息和政策条款，不得引入外部或推测性信息。

三、输出必须严格遵守 JSON 格式，包含四个字段：
- "compliant_items"：符合的项名称列表，例如 ["申报对象", "扶持领域"]
- "non_compliant_items"：不符合的项及具体原因，格式为键值对，例如 {{"申报对象": "原因描述"}}
- "uncertain_items"：因信息不完整导致无法判断的项及说明，格式为键值对，例如 {{"申报条件": "缺少财务报表"}}
- "suggestions"：针对 non_compliant_items 或 uncertain_items 的具体操作建议，每一项都单独列出，例如：
  {{
    申报对象:
    1.
    2. 
    扶持领域:
    1.
    申报条件:
    1.
  }}
  - 建议内容不要重复。
  - 多条建议可用换行符分隔
  - 仅输出 JSON，不要推理过程或额外文本

企业信息：
{company_info_text}

政策条款：
{policy_text}
"""
    return prompt

# ============================
# 检查政策申请接口
# ============================
@app.post("/check_policy")
async def check_policy_single(req: NewCheckRequest):
    company_info = req.messages[0].metadata.get("company_info", {})
    policy_info = get_policy_info(parts, req.part_id)
    if "error" in policy_info:
        raise HTTPException(status_code=404, detail='未找到该申报专项政策,请检查part_id是否正确。')

    company_name = company_info.get("name", "")
    if not company_name:
        raise HTTPException(status_code=400, detail="company_info 必须包含 name 字段作为唯一标识。")

    # 获取该公司历史记录列表
    records = global_company_info.setdefault(company_name, [])
    # 检查最大记录数限制
    if len(records) >= MAX_RECORDS_PER_COMPANY:
        raise HTTPException(
            status_code=400,
            detail=f"该公司历史记录已达 {MAX_RECORDS_PER_COMPANY} 条，请删除旧记录后再提交"
        )

    # 获取最新一条记录作为 base_info
    base_info = records[-1]["company_info"] if records else empty_company_info_dict()
    # merge
    updated_info = merge_company_info(base_info, company_info)
    # 保存一条新记录
    record = {
        "part_id": req.part_id,
        "company_info": updated_info,
        "policy_info": policy_info
    }
    records.append(record)

    logger.info(f"=============当前全局存储状态:\n{json.dumps(global_company_info, ensure_ascii=False, indent=2)}")

    # 清理空值用于 prompt
    company_info_for_prompt = deep_clean_dict(updated_info)
    prompt = build_combined_prompt(company_info_for_prompt, policy_info)

    payload = {
        "model": "deepseek-v3",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    accumulated_content = ""
    final_id = None
    final_model = None

    try:
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
                        break
    except httpx.RequestError as e:
        logger.error(f"请求模型API失败: {e}")
        raise HTTPException(status_code=500, detail="调用模型服务失败，请稍后重试。")

    # 清理 ```json 包裹
    cleaned_content = accumulated_content.strip()
    if cleaned_content.startswith("```json"):
        cleaned_content = cleaned_content[len("```json"):].strip()
    if cleaned_content.endswith("```"):
        cleaned_content = cleaned_content[:-3].strip()

    try:
        parsed_result = json.loads(cleaned_content)
    except json.JSONDecodeError:
        logger.error(f"模型返回内容无法解析为JSON: {cleaned_content}")
        raise HTTPException(status_code=500, detail="模型返回内容不是有效的JSON格式")

    # 修正 parsed_result
    parsed_result.setdefault("non_compliant_items", {})
    parsed_result.setdefault("uncertain_items", {})
    suggestions = parsed_result.get("suggestions", {})
    if isinstance(suggestions, str):
        keys = list(parsed_result["non_compliant_items"].keys()) + list(parsed_result["uncertain_items"].keys())
        suggestions = {k: suggestions for k in keys} if suggestions.strip() else {k: "" for k in keys}
    parsed_result.pop("suggestions", None)

    return {
        "status": "done",
        "id": final_id,
        "model": final_model,
        "part_id": req.part_id,
        "result": {
            "company_info": deep_clean_dict(updated_info),
            "policy_info": policy_info,
            "policy_compliance": parsed_result,
            "suggestions": suggestions
        }
    }

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("ds-v3-main:app", host="0.0.0.0", port=8500)
