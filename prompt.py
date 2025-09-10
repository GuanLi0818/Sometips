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
            3. 申报期限（请从政策条款中提取或推算申报时间段，这里的申报期限一定要准确。）
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


def build_company_judgment_prompt(
        company_info: Dict[str, Any],
        policy_info: Dict[str, Any],
        extra_user_inputs: str = "",
        check_mode: int = 1
) -> str:
    """
    构建企业政策判断的提示词
    :param company_info: 企业信息字典
    :param policy_info: 政策条款字典
    :param extra_user_inputs: 用户原始输入文本
    :param check_mode: 判断模式，1=保留原逻辑，2=只输出满足/不满足/不确定
    :return: LLM提示词
    """
    company_info_text = "\n".join(f"{k}: {v}" for k, v in company_info.items())
    policy_text_lines = [f"{k}: {v}" for k, v in policy_info.items()]
    policy_text = "\n".join(policy_text_lines)

    # check_mode=1 提示词：原有逻辑
    if check_mode == 1:
        base_prompt = f"""
            你是一位精通政府政策解读和企业合规分析的专家。
            你的任务是根据企业信息和政策条款，判断企业是否符合申报条件，只输出“不满足/不确定”的条件及简短建议，不生成其他内容。
            
            要求：
            1. 申报对象：重点关注字段：org、cap、size、regist_loc、tax_loc、description、extra_fields 等。
            2. 扶持领域：重点关注字段：key_focus_areas、industry、description、primary_product、tags、honors、extra_fields 等。
            3. 申报条件：逐条对照政策条款的申报条件，结合企业所有信息判断。
            4. 政策条款中 {policy_text} 的“申报对象”、“扶持领域”、“申报条件”三项必须都要判断，若某一项为空或无内容，则默认满足该项。
            5. 输出为纯文本，不要 JSON，也不要勾选框或符号。
            6. 每条条件一句话，直接描述问题。
            7. 控制总输出长度，语言一定要简洁，要控制输出字数。
            8. 列出所有不满足的条件，没有就不写。
            9. 列出所有不确定的条件，没有就不写。
            10. 不要生成企业信息字段名（如 regist_loc、tax_loc、industry 等）。
            11. 如果公司信息中未明确以下信息，就默认为满足项，不用输出：
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
            15. 字段里重复的信息只输出一次。
            16. 输出规则：
                - 如果存在不满足或不确定的条件，则输出对应内容。
                - 如果所有条件都满足，则输出：
                    不满足项：无
                    不确定项：无
                - 不要输出其他任何前缀或说明文字。
            
            政策条款：
            {policy_text}
            
            企业信息（以这个为准）：
            {company_info_text}
            
            用户原始输入（仅供参考）：
            {extra_user_inputs}
            
            示例输出风格:
            不满足项：
            1. 企业税收户管不在浦东新区。
            2. ...

            不确定项：
            1. 是否存在尚未披露的股权结构情况。
            2. ...
            
            """
        return base_prompt

    # check_mode=2 提示词：只输出满足/不满足/不确定
    elif check_mode == 2:
        base_prompt = f"""
            你是一位精通政府政策解读和企业合规分析的专家。
            你的任务是根据企业信息和政策条款，判断企业是否符合申报条件，必须输出三类：
            1. 满足项：列出企业信息中实际使用到且符合政策要求的字段。
            2. 不满足项：列出企业缺少或不符合政策要求的条件。
            3. 不确定项：列出信息不明确或无法判断的条件。
            不要输出其他文字。

            要求：
            1. 申报对象：重点关注字段：org、cap、size、regist_loc、tax_loc、description、extra_fields 等。
            2. 扶持领域：重点关注字段：key_focus_areas、industry、description、primary_product、tags、honors、extra_fields 等。
            3. 申报条件：逐条对照政策条款的申报条件，结合企业所有信息判断。
            4. 政策条款中 {policy_text} 的“申报对象”、“扶持领域”、“申报条件”三项必须都要判断，若某一项为空或无内容，则默认满足该项。
            5. 输出为纯文本，不要 JSON，也不要勾选框或符号。
            6. 每条条件一句话，直接描述问题。
            7. 控制总输出长度，语言一定要简洁，要控制输出字数。
            8. 列出所有不满足的条件，没有就不写。
            9. 列出所有不确定的条件，没有就不写。
            10. 不要生成企业信息字段名（如 regist_loc、tax_loc、industry 等）。
            11. 如果公司信息中未明确以下信息，就默认为满足项，不用输出：
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
            15. 满足项只列出企业信息中实际使用到且符合政策要求的字段。
            15. 满足项必须列出所有实际符合政策要求的条件，不论是否存在不满足项。
            16. 不满足项列出企业缺少或不符合政策要求的条件。
            17. 不确定项列出信息不明确或无法判断的条件。
            18. 不要输出企业字段名、勾选框或其他前缀。
            19. 如果所有条件都满足，不满足项和不确定项显示“无”。
            20. 控制总输出长度，一定要简短。
            21. 根据企业信息(regist_loc、org等)判断实际满足项，即使是默认满足也列出。

            政策条款：
            {policy_text}

            企业信息：
            {company_info_text}

            用户原始输入（仅供参考）：
            {extra_user_inputs}

            示例输出风格,根据实际内容把满足项也要输出：
            满足项：
            1. 企业所在行业为高端智能装备领域。
            2. 企业荣誉信息符合政策时间要求。

            不满足项：
            1. 企业税收户管不在浦东新区。

            不确定项：
            1. 是否存在尚未披露的股权结构情况。
            """

        return base_prompt


def build_company_standardization_prompt(user_input: str) -> str:
    """
    将用户口语化输入映射成标准公司信息字段，输出方便与 metadata 合并
    """
    prompt = f"""
        你是一位企业信息清洗和标准化专家。请将用户口语化输入严格映射到标准公司信息字段，优先填充非tags字段。

        ## 用户输入
        {user_input}

        ## 核心原则（必须优先遵守）：
        1. 所有信息必须首先尝试匹配到除"tags"外的标准字段中
        2. 只有当信息确实无法匹配任何其他标准字段时，才能放入"tags"
        3. 严禁将可匹配到其他字段的信息放入"tags"

        ## 处理规则：
        1. **字段映射**：仅输出用户明确提及的字段，未提及字段不输出
        2. **格式规范**：
           - 每行一个字段，格式: "字段名": 值
           - 列表字段: ["值1", "值2"] 
           - 数值字段: 直接数字（如 100, 3.14）
           - 字符串字段: "带引号字符串"
        3. **优先级**：优先匹配标准字段，无法归类的放入tags
        4. **去重处理**：相同信息不在多个字段重复输出

        ## 标准字段清单及处理细则：

        ### 企业基本信息
        - "name": 公司全称（必须准确识别）
        - "description": 企业简介（概括性描述）
        - "establish_time": 成立时间（YYYY-MM-DD格式，必须推断完整日期）
        - "regist_loc": 注册地址（市_区格式，如"上海市_浦东新区"）
        - "tax_loc": 税收户管地（市_区格式，如"上海市_浦东新区"）

        ###  规模与资本
        - "size": ["微型企业", "小型企业", "中型企业", "大型企业"]（严格匹配）
        - "org": ["有限责任公司", "股份合作制", "全民所有制", "外商投资企业分公司", "集体所有制", "个人独资企业", "股份有限公司", "合伙企业"]
        - "cap": ["外商投资企业投资", "外商投资企业", "民营企业", "国有企业", "外企", "台、港、澳投资企业"]
        - "person_size": 员工人数（纯数字）
        - "cap_size": 注册资金（万元，纯数字）
        - "credit_code": 字符串，统一社会信用代码（18位）

        ###  资质荣誉（列表字段）
        - "rank": ["科技型中小企业", "高新技术企业", "专精特新企业", "小巨人企业", "瞪羚企业", "单项冠军企业", "独角兽企业", "潜在独角兽企业", "领先汽车科技企业", "地理信息企业"]
        - "honors": 企业荣誉（必须包含时间信息，如"2024年度创新企业"），如["2024年度上海市创新企业", "2023年高新技术企业"]
        - "qualifications": 企业资质证书,如["软件企业认定证书", "双软认证"]
        - "credit_rating": 信用等级,如["AAA","AA+"]


        ###  业务领域（列表字段）
        - "industry": 所属行业,（如["信息传输、软件和信息技术服务业", "制造业"]）
        - "primary_product": 主要产品（如["智能眼镜", "智能眼镜配件"]）
        - "key_focus_areas": 重点技术领域（如["人工智能", "生物医药", "集成电路"]）

        ###  财务数据（纯数字）
        - "r_d_staff_count": 整数，研发人员数量
        - "r_d_expense_last_year": 上年研发支出（万元）
        - "revenue_last_year": 上一年营收（万元）
        - "revenue_growth_rate_last_year": 上年营收增幅（%）
        - "total_profit_last_year": 上年利润（万元）
        - "total_assets_last_year": 上年总资产（万元）
        - "asset_liability_ratio_last_year": 上年资产负债率（%）
        - "total_output_last_year": 上年总产值（万元）

        ###  其他信息
        - "tags": 仅包含完全无法匹配上述任何字段的关键信息，特别是：
          * 时间范围信息（格式："事项: 开始时间 到 结束时间"）
          * 技术项目描述
          * 特殊业务情况
          * 政策相关关键词
          * 已在其他字段包含的信息，严禁在tags中重复出现

        ##  智能处理规则：
        1. **优先匹配**：对每条信息，必须先检查是否能匹配到非tags字段，只有确认无法匹配后才能放入tags
        2. **时间推理**：模糊时间→精确范围（"2024年"→"2024-01-01 到 2024-12-31"）
        3. **术语映射**：口语→标准术语（"做AI的"→"人工智能"）
        4. **数值提取**：文本中的数字→纯数值（"约100人"→100）
        5. **列表去重**：自动合并相同类型的多个值
        6. **格式验证**：确保输出格式可直接解析

        ##  字段验证规则：
        - 数值字段：必须为数字，无单位，无逗号分隔
        - 时间字段：必须为YYYY-MM-DD格式
        - 地址字段：必须为"市_区"格式
        - 枚举字段：必须从预定义值中选择
        - 列表字段：必须为Python列表格式

        ##  禁止行为：
        - 输出JSON格式或大括号
        - 添加额外说明文字或注释
        - 输出空字段或未提及字段
        - 将可匹配到其他字段的信息放入tags
        - 重复输出相同信息到多个字段
        - 输出任何标题或分隔线

        ##  输出示例：
            "name": "上海云智科技有限公司",
            "org": "有限责任公司",
            "cap": "民营企业",
            "size": "中型企业",
            "description": "一家专注于人工智能和大数据解决方案的高科技企业，成立于2018年",
            "establish_time": "2018-05-20",
            "regist_loc": "上海市_浦东新区",
            "tax_loc": "上海市_浦东新区",
            "person_size": 256,
            "cap_size": 1000.0,
            "credit_rating": ["AAA","A"],
            "credit_code": "91310115MA1K35J78E",
            "industry": [
              "信息技术",
              "人工智能",
              "大数据"
            ],
            "primary_product": [
              "智能客服系统",
              "数据分析平台",
              "机器学习框架"
            ],
            "key_focus_areas": [
              "自然语言处理",
              "计算机视觉",
              "云计算"
            ],
            "honors": [
              "2023年度上海市创新型企业",
              "2024年浦东新区科技进步奖"
            ],
            "qualifications": [
              "ISO9001认证",
              "CMMI3级认证",
              "高新技术企业证书"
            ],
            "rank": [
              "高新技术企业",
              "科技型中小企业"
            ],
            "tags": [
              "企业级解决方案",
              "参与国家863计划项目: 2023-01-01 到 2025-12-31"
            ],
            "r_d_staff_count": 85,
            "revenue_last_year": 3850.5,
            "revenue_growth_rate_last_year": 32.6,
            "r_d_expense_last_year": 920.8,
            "total_profit_last_year": 780.3,
            "total_assets_last_year": 5200.0,
            "asset_liability_ratio_last_year": 42.1,
            "total_output_last_year": 4500.2

        现在请开始处理用户输入，严格按照上述规则输出：
        """
    return prompt






