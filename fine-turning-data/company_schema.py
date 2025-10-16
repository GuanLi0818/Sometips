import json
import re
from typing import Dict
from api_utils import call_local_model
from policy_loader import get_policy_info_struct


COMPANY_SCHEMA = {
    # 基本信息
    "name": {"type": "str", "desc": "企业名称"},
    "org": {"type": "str", "choices": ["有限责任公司", "股份有限公司", "股份合作制", "全民所有制",
                                       "外商投资企业分公司", "集体所有制", "个人独资企业", "合伙企业"],
            "desc": "企业组织形式"},
    "cap": {"type": "str", "choices": ["民营企业", "国有企业", "外商投资企业", "外商投资企业投资",
                                       "外企", "台、港、澳投资企业"],
            "desc": "企业资本类型"},
    "size": {"type": "str", "choices": ["微型企业", "小型企业", "中型企业", "大型企业"],
             "desc": "企业规模"},
    "description": {"type": "str", "desc": "企业简介或主营方向，描述其业务特征"},
    "establish_time": {"type": "str", "desc": "成立时间，格式 YYYY-MM-DD"},
    "regist_loc": {"type": "str", "desc": "企业注册地，例如：上海市_浦东新区"},
    "tax_loc": {"type": "str", "desc": "税务登记地，例如：上海市_浦东新区"},
    # 财务指标
    "person_size": {"type": "int", "desc": "员工人数"},
    "cap_size": {"type": "float", "desc": "注册资本（万元）"},
    "revenue_last_year": {"type": "float", "desc": "上年营业收入（万元）"},
    "revenue_growth_rate_last_year": {"type": "float", "desc": "上年营业收入增长率（%）"},
    "r_d_expense_last_year": {"type": "float", "desc": "上年研发费用（万元）"},
    "total_profit_last_year": {"type": "float", "desc": "上年利润（万元）"},
    "total_assets_last_year": {"type": "float", "desc": "上年资产总额（万元）"},
    "asset_liability_ratio_last_year": {"type": "float", "desc": "上年资产负债率（%）"},
    "total_output_last_year": {"type": "float", "desc": "上年总产值（万元）"},
    "r_d_staff_count": {"type": "int", "desc": "研发人员数量"},
    # 资质与荣誉
    "credit_rating": {"type": "list[str]", "desc": "信用等级，如 ['AAA','A+']"},
    "credit_code": {"type": "str", "desc": "统一社会信用代码"},
    "honors": {"type": "list[str]", "desc": "企业获得的荣誉称号"},
    "qualifications": {"type": "list[str]", "desc": "企业认证与资质，如ISO9001、高企证书"},
    "rank": {"type": "list[str]",
             "choices": ["科技型中小企业", "高新技术企业", "专精特新企业", "小巨人企业",
                         "地理信息企业", "独角兽企业", "潜在独角兽企业",
                         "领先汽车科技企业", "瞪羚企业", "单项冠军企业"],
             "desc": "企业称号或等级"},
    # 行业与产品
    "industry": {"type": "list[str]",
                 "desc": "企业所属行业（三级分类），例如 ['科学研究和技术服务业','科技推广和应用服务业','技术推广服务']"},
    "primary_product": {"type": "list[str]", "desc": "企业主要产品/服务，如 ['智能客服系统','数据分析平台']"},
    "key_focus_areas": {"type": "list[str]", "desc": "重点研究或业务方向，如 ['自然语言处理','计算机视觉']"},
    "tags": {"type": "list[str]", "desc": "自定义标签，用于补充特征，如 ['AI算法','云计算']"}
}


def build_company_prompt(policy_info: dict) -> str:

    policy_text = "\n".join([f"{k}: {v}" for k, v in policy_info.items() if v])
    schema_fields = ", ".join(COMPANY_SCHEMA.keys())
    prompt = f"""
你是一位企业合规与政策研究专家。
请根据以下政策内容，生成一个合理的企业信息字段（company_info）。
要求输出为JSON格式，字段名必须来自下列字段全集中：
[{schema_fields}]

【政策内容】
{policy_text}

输出要求：
1. 仅生成与政策内容相关的字段。
2. 字段值需真实合理，并符合字段类型（如字符串、数字、列表等）。
3. 不要生成额外的字段。
4. JSON结构必须正确。
5. 可以根据政策推测合理的企业规模、行业、主营方向等。
6. 若政策与特定行业、企业类型相关，请在字段中体现（如industry, cap, rank）。


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
"""
    return prompt.strip()


def parse_json_response(text: str) -> dict:
    """提取模型输出 JSON"""
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return {}
    return {}


def filter_company_fields(data: dict) -> dict:
    """仅保留 COMPANY_SCHEMA 定义的字段"""
    return {k: v for k, v in data.items() if k in COMPANY_SCHEMA}


def enforce_field_types(data: dict) -> dict:
    """校正 list 和数值字段类型"""
    for field, meta in COMPANY_SCHEMA.items():
        if field not in data:
            continue
        val = data[field]
        if meta["type"] == "list[str]":
            if isinstance(val, str):
                # 按逗号、顿号、分号分割成列表
                data[field] = [s.strip() for s in re.split(r"[，,;；]", val) if s.strip()]
            elif isinstance(val, list):
                data[field] = [str(s).strip() for s in val]
        elif meta["type"] == "list[list[str]]":
            if isinstance(val, str):
                lines = [s.strip() for s in re.split(r"[，,;；\n]", val) if s.strip()]
                data[field] = [lines] if lines else []
            elif isinstance(val, list):
                new_list = []
                for item in val:
                    if isinstance(item, list):
                        new_list.append([str(s).strip() for s in item])
                    else:
                        new_list.append([str(item).strip()])
                data[field] = new_list
        elif meta["type"] == "int":
            try:
                data[field] = int(val)
            except (ValueError, TypeError):
                data[field] = 0
        elif meta["type"] == "float":
            try:
                data[field] = float(val)
            except (ValueError, TypeError):
                data[field] = 0.0
    return data


def filter_generated_company_fields(data: dict) -> dict:
    """
    过滤生成字段：
    1. 仅保留 COMPANY_SCHEMA 定义的字段
    2. 丢弃值为空、None 或空列表的字段
    """
    result = {}
    for k, v in data.items():
        if k not in COMPANY_SCHEMA:
            continue
        if v is None:
            continue
        if isinstance(v, list) and not v:  # 空列表
            continue
        if isinstance(v, str) and not v.strip():  # 空字符串
            continue
        result[k] = v
    return result

def generate_company_info_from_policy(part_id: str) -> dict:
    """
    核心函数：根据 part_id.txt 获取政策信息，并生成公司完整结构化字段
    """
    result = get_policy_info_struct(part_id)
    policy_info = result.get("policy_info", {})
    if not policy_info:
        return {"error": f"policy_info not found for part_id.txt {part_id}"}

    prompt = build_company_prompt(policy_info)
    response = call_local_model(prompt)
    parsed = parse_json_response(response)

    filtered = filter_company_fields(parsed)
    return enforce_field_types(filtered)


# 测试
# if __name__ == "__main__":
#     company_info = generate_company_info_from_policy("1228370698563420160")
#     import json
#     print(json.dumps(company_info, ensure_ascii=False, indent=2))
