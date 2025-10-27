# -*- coding: utf-8 -*-
"""
@File    : demo1_async.py
@Author  : qy
@Date    : 2025/10/27 15:05
"""

import random
import json
import re
import asyncio
from api_async import call_local_model_async
from policy_loader import get_policy_info_struct
from company_schema import COMPANY_SCHEMA, generate_company_info_from_policy


async def company_info_to_text_async(company_info: dict, ratio: float = 0.6) -> str:
    """
    从完整 company_info 随机抽取比例字段，生成自然口语化描述（异步版）
    """
    available_keys = [k for k, v in company_info.items() if v and k in COMPANY_SCHEMA]
    if not available_keys:
        return ""

    num_fields = max(1, int(len(available_keys) * ratio))
    selected_keys = random.sample(available_keys, num_fields)

    template_parts = []
    for k in selected_keys:
        v = company_info[k]
        if isinstance(v, list):
            v = "、".join(map(str, v))
        elif isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False)
        else:
            v = str(v)
        template_parts.append(f"{COMPANY_SCHEMA[k]['desc']}是 {v}")

    template_text = "；".join(template_parts)

    prompt = f"""
你是一位专业的商业分析助理，请将以下企业信息改写成一段自然、连贯的口语化描述。

【企业信息模板】：
{template_text}

【改写要求】：
1. 必须包含输入中提供的所有关键信息，不能遗漏任何字段内容。
2. 不得虚构、添加或扩展模板中没有出现的信息。
3. 内容应以自然语言连贯表达，语气可以口语化、流畅，但保持客观准确。
4. 不要输出条列式内容，不要使用编号、项目符号或分号分隔。
5. 输出一段连续的自然语言文本。
6. 保证所有数字、金额、时间、地名等信息准确保留。
7.公司的名称name，必须要有，而且生成的要合理。

请直接输出改写后的自然语言描述，不要解释或附加说明。
"""
    natural_text = await call_local_model_async(prompt)
    return natural_text.strip()


def filter_generated_company_fields(data: dict) -> dict:
    INVALID_VALUES = {"", "无", "未知", "不详", "None", "无相关", "未填写", "未说明", "未提供"}
    result = {}
    for k, v in data.items():
        if k not in COMPANY_SCHEMA:
            continue
        if v is None:
            continue
        if isinstance(v, (int, float)) and v == 0:
            continue
        if isinstance(v, str):
            if v.strip() in INVALID_VALUES:
                continue
            result[k] = v.strip()
            continue
        if isinstance(v, list):
            filtered_list = [i for i in v if i not in INVALID_VALUES and i != 0]
            if filtered_list:
                result[k] = filtered_list
            continue
        if isinstance(v, dict):
            cleaned = filter_generated_company_fields(v)
            if cleaned:
                result[k] = cleaned
            continue
        result[k] = v
    return result


async def generate_finetune_sample_async(part_id: str, ratio: float = 0.6, num_samples: int = 1) -> list:
    """
    异步版本：生成微调样本
    """
    policy_info_res = get_policy_info_struct(part_id)
    policy_info = policy_info_res.get("policy_info", {})
    if not policy_info:
        return {"error": f"policy_info not found for part_id {part_id}"}

    company_info_full = await generate_company_info_from_policy(part_id)
    all_samples = []

    for _ in range(num_samples):
        company_text = await company_info_to_text_async(company_info_full, ratio=ratio)

        prompt = f"""
请根据以下口语化描述，生成一个完整的公司结构化信息（company_info）。
    
    【任务要求】：
    1. 仅生成在描述中明确提到或可合理推断的字段。
    2. 不要生成描述中没有出现或无法确定的字段。
    3. 字段值必须来自以下字段全集：
       [{', '.join(COMPANY_SCHEMA.keys())}]
    4. 保证 JSON 格式正确，字段名用英文，不要额外增加说明文字。
    5. 字段值类型必须与原定义一致（字符串、数字、列表、布尔值）。
    6. 列表字段以 JSON 数组格式输出，例如 ["a", "b"]。
    7. 不要输出空值、None、null、0、""、“无”、“未知”、“不详”、“无相关”等无效内容。
    8. 若某字段未在描述中出现，则不要生成该字段。
    
    口语化描述：
    {company_text}
    
    要求：
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
    - "industry": 三级行业名,（如["信息传输、软件和信息技术服务业", "技术推广服务"]）
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
    
    现在请开始处理用户输入，严格按照上述规则输出。
...
{company_text}
"""
        response = await call_local_model_async(prompt)
        try:
            parsed_json = json.loads(re.search(r"\{[\s\S]*\}", response).group(0))
        except:
            parsed_json = {}

        company_info_from_text = filter_generated_company_fields(parsed_json)
        sample = {
            "part_id.txt": part_id,
            "policy_info": policy_info,
            "company_info_full": company_info_full,
            "company_text": company_text,
            "company_info_from_text": company_info_from_text,
        }
        all_samples.append(sample)

    return all_samples


if __name__ == "__main__":
    async def main():
        res = await generate_finetune_sample_async("1260140009999060992", ratio=0.5, num_samples=1)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    asyncio.run(main())
