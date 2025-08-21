# -*- coding: utf-8 -*-
"""
@File    : prompt.py
@Author  : qy
@Date    : 2025/8/21 14:14
"""
from typing import List, Dict, Any, Optional
from policy_utils import get_policy_info, parts, ori_data




import json
policy_file_name_cache = {
    pid: pdata.get("file_name", f"政策 {pid}")
    for pid, pdata in ori_data.get("debug_data", {}).get("policy_toolbox_parts", {}).items()
}

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






def build_policy_elements_prompt(part_id: str, policy_info: Dict[str, Any]) -> str:
    policy_name = policy_file_name_cache.get(part_id, f"政策 {part_id}")
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

        只输出政策兑付金额、申报期限、牵头部门，如没有就写无，格式：
        专项名称：（固定为 {policy_name}）
        兑付金额: XXX 元
        申报期限: XXXX - XXXX
        牵头部门: XXX

        """
    return prompt

def build_company_judgment_prompt(company_info: Dict[str, Any], policy_info: Dict[str, Any]) -> str:
    company_info_text = "\n".join(f"{k}: {v}" for k, v in company_info.items())
    policy_text_lines = [f"{k}: {v}" for k, v in policy_info.items()]
    policy_text = "\n".join(policy_text_lines)
    prompt = f"""
        你是一位精通政府政策解读和企业合规分析的专家。
        你的任务是根据企业信息和政策条款，判断企业是否符合申报条件，只输出“不满足/不确定”的条件及简短建议，不生成其他内容。

        要求：
        1. 政策条款中{policy_text}的“申报对象”、“扶持领域”、“申报条件”三项必须都要判断，若某一项为空或无内容，则默认满足该项。
        1. 输出为纯文本，不要 JSON，也不要勾选框或符号。
        2. 每条条件一句话，直接描述问题。
        3. 控制总输出长度，语言一定要简洁，要控制输出字数。
        4. 列出所有不满足的条件，给出简要的建议。
        5. 列出所有不确定的条件，给出简要的建议。
        6. 不要生成企业信息字段名（如 regit_loc、tax_loc、industry 等）。
        7. 如果公司信息中未明确：企业内部治理结构规范性、企业财务管理制度健全性、企业经营状态良好、企业信用记录良好、企业在生产经营中做好安全生产工作、企业安全生产合规性信息，就默认为满足项，就不用输出和建议。

        政策条款：
        {policy_text}

        企业信息：
        {company_info_text}

        请生成最终输出示例如下风格：
        不满足项：
            1. 企业所在行业是否为高端智能装备领域。
            2. 是否在2024年期间完成上海市级政策支持高端智能装备首台套突破项目验收。
            3. 市级扶持资金是否已拨付到位。
        不确定项：
            1. 
            2. 
        """
    return prompt