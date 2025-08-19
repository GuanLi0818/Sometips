# -*- coding: utf-8 -*-
"""
@File    : ds-v3.py
@Author  : qy
@Date    : 2025/8/18 11:06
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import httpx
import logging
import json
import uuid
import asyncio

from policy_utils import get_policy_info, parts,ori_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://mcc-pre.3xmt.com/gateway/ai-service/v1/chat/completions"
API_KEY = "sk-bFcPcwS7J7oP6e8LGo"

app = FastAPI()

MAX_RECORDS_PER_COMPANY = 5
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

def deep_clean_dict(d: dict) -> dict:
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
    uid: Optional[str] = None
    messages: List[Message]


policy_file_name_cache = {
    pid: pdata.get("file_name", f"政策 {pid}")
    for pid, pdata in ori_data.get("debug_data", {}).get("policy_toolbox_parts", {}).items()
}


def build_policy_elements_prompt(part_id: str, policy_info: Dict[str, Any]) -> str:
    """第一轮提示词：输出政策要素，三项由大模型补全"""
    policy_name = policy_file_name_cache.get(part_id, f"政策 {part_id}")

    # 转为文本展示政策条款
    policy_text_lines = [f"{key}: {value}" for key, value in policy_info.items()]
    policy_text = "\n".join(policy_text_lines)

    prompt = f"""

        请根据以下要求生成输出：
        1. 角色：你是一位政府政策分析专家，擅长从政策条款中提炼核心展示信息。
        2. 功能：你的任务是从提供的政策条款中，输出政策展示要素，便于企业理解和申报。
        3. 输出要求：每项单独换行显示。
        4. 不要提供建议或额外说明，字数一定精简。
        5. 必须输出以下四项：
            1. 专项名称（固定为 {policy_name}）
            2. 兑付金额（请从政策条款中提取或推算具体金额）
            3. 申报期限（请从政策条款中提取或推算申报时间段）
            4. 牵头部门（请从政策条款中识别或推算相关信息）
        
        政策条款：
        {policy_text}
        
        只输出政策兑付金额、申报期限、牵头部门，格式：
        专项名称：（固定为 {policy_name}）
        兑付金额: XXX 元
        申报期限: XXXX - XXXX
        牵头部门: XXX

        """
    return prompt


def build_company_judgment_prompt(company_info: Dict[str, Any], policy_info: Dict[str, Any]) -> str:
    """第二轮提示词：判断企业是否符合申报专项（简洁文本输出，不含勾选框）"""
    company_info_text = "\n".join(f"{k}: {v}" for k, v in company_info.items())
    policy_text_lines = [f"{k}: {v}" for k, v in policy_info.items()]
    policy_text = "\n".join(policy_text_lines)

    prompt = f"""
        你是一位精通政府政策解读和企业合规分析的专家。
        你的任务是根据企业信息和政策条款，判断企业是否符合申报专项。
        
        角色：企业合规分析专家
        功能：只判断企业是否符合申报条件，输出“不满足/不确定”的条件及简短建议，不生成其他内容。

        要求：
        1. 输出为纯文本，不要 JSON，也不要勾选框或符号。
        2. 每条条件一句话，直接描述问题。
        3. 控制总输出长度，语言一定要简洁。
        4. 只列出不满足或不确定的条件，满足的项可以省略(不满足或不确定的条件给出简要的建议)。
        5. 不要生成企业信息字段名（如 regit_loc、tax_loc、industry 等）。
        
        政策条款：
        {policy_text}
        
        企业信息：
        {company_info_text}
        
        请生成最终输出示例如下风格：
        经AI对政策申报要求与贵司画像特征分析，您当前尚未完全满足政策申报条件，以下条件需要进一步确认：
        1. 企业所在行业是否为高端智能装备领域。
        2. 是否在2024年期间完成上海市级政策支持高端智能装备首台套突破项目验收。
        3. 市级扶持资金是否已拨付到位。
        """
    return prompt


async def get_model_response(prompt: str) -> str:
    """通用流式调用模型获取文本"""
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
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream("POST", API_URL, json=payload, headers=headers) as response:
                async for line_bytes in response.aiter_lines():
                    if not line_bytes:
                        continue
                    line_str = line_bytes.lstrip("data:").strip()
                    try:
                        data_json = json.loads(line_str)
                    except json.JSONDecodeError:
                        continue
                    choice = data_json.get("choices", [{}])[0]
                    chunk = choice.get("delta", {}).get("content", "")
                    if chunk:
                        accumulated_content += chunk
                    if choice.get("finish_reason") == "stop":
                        break
    except httpx.RequestError as e:
        logger.error(f"请求模型API失败: {e}")
        raise HTTPException(status_code=500, detail="调用模型服务失败，请稍后重试。")
    return accumulated_content.strip()

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
        # 找到原记录
        target_record = next((r for r in existing_records if r["uid"] == req.uid), None)
        if not target_record:
            raise HTTPException(status_code=404, detail="指定 uid 对应的记录不存在")

        # 合并公司信息（有值覆盖，无值保留原值）
        merged_info = merge_company_info(target_record["company_info"], company_info)
        merged_policy_info = merge_company_info(target_record.get("policy_info", {}), policy_info)

        # 新生成 uid 保存为新记录
        new_uid = str(uuid.uuid4())
        new_record = {
            "uid": new_uid,
            "part_id": req.part_id,
            "company_info": merged_info,
            "policy_info": merged_policy_info
        }

        # 检查是否超出最大记录数
        if len(existing_records) >= MAX_RECORDS_PER_COMPANY:
            raise HTTPException(
                status_code=400,
                detail=f"该公司历史记录已达 {MAX_RECORDS_PER_COMPANY} 条，无法再新增记录。"
            )
        global_company_info.setdefault(company_name, []).append(new_record)

    else:
        # uid 为空 → 新增记录
        if len(existing_records) >= MAX_RECORDS_PER_COMPANY:
            raise HTTPException(
                status_code=400,
                detail=f"该公司历史记录已达 {MAX_RECORDS_PER_COMPANY} 条，无法再新增记录。"
            )

        # 新增记录，继承最新一条记录基础信息
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

    print("===================全局保存结果：", global_company_info)

    # 构建提示词
    policy_elements_prompt = build_policy_elements_prompt(req.part_id, policy_info)
    company_judgment_prompt = build_company_judgment_prompt(merged_info, policy_info)

    # 并行流式调用
    policy_task = asyncio.create_task(get_model_response(policy_elements_prompt))
    judgment_task = asyncio.create_task(get_model_response(company_judgment_prompt))

    # await 两个流式结果
    policy_elements_text, judgment_text = await asyncio.gather(policy_task, judgment_task)

    return {
        "status": "done",
        "uid": new_uid,
        "part_id": req.part_id,
        "result": f"{policy_elements_text}\n\n{judgment_text}"
    }




if __name__ == '__main__':
    import uvicorn
    uvicorn.run("ds-v3:app", host="0.0.0.0", port=8500)
