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
        1. 申报对象：重点关注字段：org、cap、size、regist_loc、tax_loc、description、extra_fields 等。
        2. 扶持领域：重点关注字段：key_focus_areas、industry、description、primary_product、tags、honors 、extra_fields等。
        3. 申报条件：逐条对照政策条款的申报条件，结合企业所有信息判断。
        4. 政策条款中{policy_text}的“申报对象”、“扶持领域”、“申报条件”三项必须都要判断，若某一项为空或无内容，则默认满足该项。
        5. 输出为纯文本，不要 JSON，也不要勾选框或符号。
        6. 每条条件一句话，直接描述问题。
        7. 控制总输出长度，语言一定要简洁，要控制输出字数。
        8. 列出所有不满足的条件，没有就不写，给出简要的建议。
        9. 列出所有不确定的条件，没有就不写，给出简要的建议。
        10. 不要生成企业信息字段名（如 regit_loc、tax_loc、industry 等）。
        11. 如果公司信息中未明确以下信息，就默认为满足项，就不用输出和建议：
            企业内部治理结构规范性、
            企业财务管理制度健全性、
            企业经营状态良好、
            企业信用记录良好、
            企业在生产经营中做好安全生产工作、
            企业安全生产合规性信息。
        12. 请根据企业信息（honors 和 tags）以及政策要求判断是否满足条件：
            1. 如果企业荣誉或 tags 的时间在政策要求的时间范围内，即认为满足条件。
               例如：政策时间为 2024年1月1日-2025年3月23日，用户输入时间为 2024年7月，则满足条件。
            2. 用户输入的荣誉信息为准。
            3. 不要保守输出“不满足项”，除非确实缺少信息。
        13. 当用户输入的时间、行为、对象满足政策要求时间段时，判断为满足，不要保守输出不满足项。
        14. tags 中的内容也视为有效补充信息，可用于满足政策要求。


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
        1. ...
        2. ...
        """
    return prompt

def build_company_standardization_prompt(user_input: str) -> str:
    """
    将用户口语化输入映射成标准公司信息字段，输出方便与 metadata 合并：
    - 列表字段输出 Python 列表
    - 数值字段输出数字
    - 字符串字段输出带双引号
    - 每行一个字段
    """
    prompt = f"""
你是一位企业信息清洗和标准化专家，请严格按照以下规则处理用户口语化输入，仅输出标准化后的字段内容，无任何多余信息。

## 用户输入
{user_input}

## 标准字段清单（仅输出用户明确提及的字段）：
- 枚举约束字段：
  - size: 企业规模（微型企业、小型企业、中型企业、大型企业）
  - org: 企业组织形式（有限责任公司、股份合作制、全民所有制、外商投资企业分公司、集体所有制、个人独资企业、股份有限公司、合伙企业）
  - cap: 企业资本类型（外商投资企业投资、外商投资企业、民营企业、国有企业、外企、台、港、澳投资企业）
  - regist_loc: 注册地址（格式：省/直辖市_市/区）
  - rank: 企业称号（列表字段，有["科技型中小企业", "高新技术企业", "专精特新企业", "小巨人企业","地理信息企业","独角兽企业","潜在独角兽企业","领先汽车科技企业","瞪羚企业","单项冠军企业"]）
  - industry: 所属行业（列表字段）

- 通用字段：
  - name: 公司名称
  - description: 企业简介
  - establish_time: 成立时间（YYYY-MM-DD）
  - tax_loc: 税收户管地
  - person_size: 企业员工人数（数字）
  - cap_size: 企业注册资金（数字）
  - credit_rating: 企业信用等级
  - credit_code: 统一社会信用代码
  - primary_product: 主营业务（列表字段）
  - key_focus_areas: 重点领域（列表字段）
  - honors: 企业荣誉（列表字段，若荣誉有获取时间，必须包含时间信息）
  - qualifications: 企业资质（列表字段）
  - tags: 如遇到用户输入中任何无法自动归类到已有标准字段的信息，都统一归到tags里（列表字段）
  - r_d_staff_count: 研发人员人数（数字）
  - r_d_expense_last_year: 上年研发支出（数字）
  - revenue_last_year: 上一年营收（数字）
  - revenue_growth_rate_last_year: 上年营收增幅（数字）
  - total_profit_last_year: 上年利润（数字）
  - total_assets_last_year: 上年总资产（数字）
  - asset_liability_ratio_last_year: 上年资产负债率（数字）
  - total_output_last_year: 上年总产值（数字）

## 输出规则：
1. 每行仅输出一个字段，格式为 "字段": 值
2. 列表字段直接输出 Python 列表，如 ["A", "B"]
3. 数值字段直接输出数字，不加引号
4. 字符串字段保留双引号
5. tags 作为重点字段，包含无法归类的关键信息（如具体技术、项目描述）
6. 未提及字段不输出
7. 不输出任何多余说明、注释、空行或标题
8. 严格禁止输出 JSON 字符串或额外文本
9. 字段已经存在的值不要在其他字段中重复输出

## 增强规则：
1. 时间推理：对于时间相关信息（如“2024年7月”），推断为完整范围（如“2024-07-01 到 2024-07-31”）并归类到 tags 或 key_focus_areas（例如，"IP购买时间: 2024-07-01 到 2024-07-31"）。
2. 语义匹配：将用户输入的非标准术语映射到政策相关术语。例如，“购买IP开发高端芯片”可映射为 key_focus_areas: ["购买IP开发高端芯片"] 。
3. 领域术语识别：识别技术领域相关信息（如“高端芯片”“人工智能”），优先归类到 key_focus_areas 或 tags。
4. 信息扩展：若用户输入信息不足以判断政策符合性，尽可能推断并补充。例如，“2024年7月购买IP”推断为“2024-07-01 到 2024-07-31购买IP”。

## 输出示例：
"name": "上海瑞影医疗科技有限公司"
"industry": ["信息技术", "软件服务"]
"honors": ["上海市标杆性智能工厂", "2024年度上海市先进级智能工厂"]
"key_focus_areas": ["医疗科技", "人工智能"]
"tags": ["科技型企业", "瞪羚企业", "IP购买时间: 2024-07-01 到 2024-07-31"]
"person_size": 200
"cap_size": 800
"""
    return prompt





