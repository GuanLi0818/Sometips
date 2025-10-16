# -*- coding: utf-8 -*-
"""
@File    : demo2.py
@Author  : qy
@Date    : 2025/10/13 14:43
"""
import json
import os
import re
from typing import Dict, List

from tqdm import tqdm

from api_utils import call_local_model
from demo1 import generate_finetune_sample


#二次验证结果

def verify_output(cleaned_output: str, policy_text: str, company_info: str) -> str:

    prompt = f"""
你是一位政策合规审查专家，请对以下【模型初次输出】进行复核，只保留判断**合理且有充分依据**的条目。

请严格根据【政策原文】和【企业信息】逐条核实【模型初次输出】中的“满足项”、“不满足项”、“不确定项”是否合理。

复核规则：
1. 仅保留有明确事实依据、且与政策条款相符的内容；
2. 删除不合理、重复、或无充分依据的条目；
3. 不新增任何内容，不修改原句表述；
4. 不生成分析说明或总结性语言；
5. 输出格式必须与模型初次输出完全一致，只对条目做删减。

【政策原文】
{policy_text}

【企业信息】
{company_info}

【模型初次输出】
{cleaned_output}

输出格式：
请保持与模型初次输出完全一致的三部分结构：
满足项：
...
不满足项：
...
不确定项：
...

只删除不合理的内容，其他内容保持原样，不添加任何额外说明。

"""

    result = call_local_model(prompt, stream=False).strip()
    cleaned_output = result.strip()

    return cleaned_output





def generate_finetune_policy_match_samples(
    part_id: str,
    ratio: float = 0.6,
    num_samples: int = 3,
    enable_verify: bool = True,
    output_path: str = "finetune_samples.jsonl"
) -> List[dict]:

    # Step 1: 生成多个企业样本（company_text + company_info）
    samples = generate_finetune_sample(part_id, ratio=ratio, num_samples=num_samples)

    if not isinstance(samples, list):
        print("generate_finetune_sample 返回异常:", samples)
        return []

    all_records  = []

    # Step 2: 遍历每个样本生成微调记录
    for idx, base_sample in enumerate(samples):
        # print(f"\n=== 开始生成第 {idx+1}/{len(samples)} 条微调样本 ===")

        policy_info = base_sample["policy_info"]
        company_text = base_sample["company_text"]
        company_info_from_text = base_sample["company_info_from_text"]

        # 拼接政策文本
        policy_text = "\n".join([f"{k}：{v}" for k, v in policy_info.items()])


        input_text = (
            f"[企业信息]\n{company_info_from_text}\n\n"
            f"[企业信息(口语化描述)]：\n{company_text}\n\n"
            f"[政策信息]\n{policy_text}"
        )

    # Step 3: 生成判断结果（调用本地模型）
        prompt = f"""
你是一位精通政府政策解读和企业合规分析的专家，请根据输入信息{input_text}，包含企业信息和政策内容，判断该企业是否符合政策的申报条件。

请输出三个部分：
1. 满足项：只描述企业已经明确符合的事实性内容，不重复或引用政策原文要求。
2. 不满足项：只描述企业存在明显不符合的事实，不重复政策要求。
3. 不确定项：仅描述信息不足或模糊的部分，不作政策判断。

请严格按照以下格式输出：

满足项：
1. ...
2. ...
不满足项：
1. ...
2. ...
不确定项：
1. ...
2. ...


输出示例：
满足项：
1. 注册登记和税收户管地在浦东新区。
2. 企业组织形式为事业单位，符合申报对象。
3. 企业行业为知识产权服务。 
不满足项：
1. 成立时间不足两年。
2. 知识产权服务能力不足。
3. 每年服务对象仅5家，未超过10家。
4. 未组织过2次以上海外知识产权公益培训。
5. 未形成2份法律环境报告或预警报告并允许用于公益宣传。 
不确定项：
1. 经营状态未提及。
2. 信用记录未提及。

输出要求：
- 政策条款中的“申报对象”、“扶持领域”、“申报条件”三项必须都要判断，若某一项为空或无，则默认满足该项。
- 每一条只陈述事实，不再出现“符合……要求”“满足……条件”等总结性语句。
- 避免重复表达，例如不要在同一条中既描述事实又重述政策条件。
- 每条内容应简洁明确，聚焦企业信息本身。

以下是输入信息：
{input_text}
"""
        response = call_local_model(prompt)
        cleaned_output = response.strip()

        if enable_verify:
            verified_output = verify_output(cleaned_output, policy_text, company_info_from_text)
        else:
            verified_output = cleaned_output

        record = {
            "instruction": "你是一位精通政府政策解读和企业合规分析的专家，请根据企业信息和政策信息，判断该企业是否符合申报条件，并输出“满足项”、“不满足项”和“不确定项”。",
            "input": input_text,
            "output": verified_output
        }


        with open(output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        all_records.append(record)

    return all_records


if __name__ == "__main__":

    # part_id = "1228340397564952576"
    # samples = generate_finetune_policy_match_samples(
    #     part_id=part_id,
    #     ratio=0.5,
    #     num_samples=3,
    #     output_path="finetune_samples.jsonl"
    # )
    #
    # print(f"已完成，共生成 {len(samples)} 条样本。")
    #

    num_samples = 3

    with open('part_id.txt', 'r',encoding='utf-8') as f:
        part_ids = f.readlines()
        part_id_list = [i.strip() for i in part_ids][:2]


        total_target = len(part_id_list) * num_samples
        total = 0
        with tqdm(total=total_target, desc="总样本生成进度") as pbar:
            for part_id in part_id_list:
            # print(f"处理第{i}/{len(part_id_list)}个part_id：{part_id}")

                samples = generate_finetune_policy_match_samples(
                    part_id=part_id,
                    ratio=0.6,
                    num_samples=num_samples,
                    output_path="finetune_samples.jsonl"
                )
                current_num = len(samples)
                total += current_num
                pbar.update(current_num)


        print(f"全部处理完成！共处理{len(part_id_list)}个part_id，生成{total}条样本，保存至：finetune_samples.jsonl")


