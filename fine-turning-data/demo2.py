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
你是一位政策合规审查专家，请对以下模型初次输出进行复核，只保留判断合理的条目。
请严格根据【政策原文】和【企业信息】逐条核实【模型初次输出】的结果是否合理，输出结果任为三部分：
对输出的结果：“满足项”、“不满足项”、“不确定项”，只保留有充分依据的内容，合理的输出保留，不合理或不存在的剔除。

【政策原文】
{policy_text}

【企业信息】
{company_info}

【模型初次输出】
{cleaned_output}

输出格式：
与模型的模型初次输出一样，只对满足项，不满足项，不确定项做删减，合理的留下，不合理的剔除
不需要生成其他文字，格式保持与模型初次输出一样。

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
1. 满足项：明确符合政策要求的条目。
2. 不满足项：明确不符合的条目。
3. 不确定项：信息不足或无法判断的条目。

请严格遵循以下格式输出：

满足项：
...
不满足项：
...
不确定项：
...

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


    with open('part_id.txt', 'r',encoding='utf-8') as f:
        part_ids = f.readlines()
        part_id_list = [i.strip() for i in part_ids][48:]

        total = 0
        for i, part_id in tqdm(enumerate(part_id_list, 1), total=len(part_id_list), desc="处理进度"):
            # print(f"处理第{i}/{len(part_id_list)}个part_id：{part_id}")

            samples = generate_finetune_policy_match_samples(
                part_id=part_id,
                ratio=0.5,
                num_samples=3,
                output_path="finetune_samples.jsonl"
            )
            total += len(samples)


        print(f"全部处理完成！共处理{len(part_id_list)}个part_id，生成{total}条样本，保存至：finetune_samples.jsonl")


