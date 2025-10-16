# -*- coding: utf-8 -*-
"""
@File    : policy_loader.py
@Author  : qy
@Date    : 2025/10/9 10:35
"""

import json
from typing import Dict, Any

# 加载数据
with open('../data/database.json', 'r', encoding='utf-8') as f:
    ori_data = json.load(f)
    parts = ori_data.get('parts', {})

# 生成缓存
policy_cache: Dict[str, Dict[str, Any]] = {}
policy_toolbox_parts = ori_data.get('debug_data', {}).get('policy_toolbox_parts', {})

for part_id, pdata in parts.items():
    struct_data = pdata["ext_data"]["struct_data"]
    file_name = policy_toolbox_parts.get(part_id, {}).get("file_name", "未知文件名")
    policy_cache[part_id] = {"file_name": file_name, "struct_data": struct_data}


# 获取政策信息并整理为 policy_info 结构
def get_policy_info_struct(part_id: str) -> dict:
    """
    获取政策信息并返回 policy_info 结构
    """
    cached = policy_cache.get(part_id)
    if not cached:
        return {"error": "part_id.txt not found"}

    struct_data = cached["struct_data"]

    # 提取原文内容
    policy_info = {
        "申报对象": struct_data.get("申报对象", ""),
        "扶持领域": struct_data.get("扶持领域", ""),
        "申报条件": struct_data.get("申报条件", "")
    }

    # 如果申报条件是列表，则 join 成字符串
    for key in ["申报对象", "扶持领域", "申报条件"]:
        value = policy_info.get(key, "")
        if isinstance(value, list):
            policy_info[key] = "\n".join(value)
        elif not isinstance(value, str):
            policy_info[key] = str(value)  # 兜底转换

        return {
            "policy_info": policy_info
        }



# # 测试输出
# if __name__ == "__main__":
#     part_id.txt = "1228370698563420160"
#     result = get_policy_info_struct(part_id.txt)
#     # result = json.dumps(result, ensure_ascii=False, indent=2)
#
#     print(result)



