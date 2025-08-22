# -*- coding: utf-8 -*-
"""
@File    : policy_utils.py
@Author  : qy
@Date    : 2025/7/25 10:30
"""
import json
from typing import Dict, Any

# 1启动时加载数据
with open('data/database.json', 'r', encoding='utf-8') as f:
    ori_data = json.load(f)
    parts = ori_data.get('parts', {})

# 2生成缓存：part_id -> {'struct_data': {...}, 'file_name': '...'}
policy_cache: Dict[str, Dict[str, Any]] = {}
debug_parts = ori_data.get("debug_data", {}).get("policy_toolbox_parts", {})
for part_id, pdata in parts.items():
    struct_data = pdata.get('ext_data', {}).get('struct_data', {})
    file_name = debug_parts.get(part_id, {}).get("file_name", f"政策 {part_id}")
    policy_cache[part_id] = {
        "struct_data": struct_data,
        "file_name": file_name
    }

# 3获取政策信息函数
def get_policy_info(part_id: str) -> Dict:
    """直接从缓存里获取政策要素"""
    targets = ['申报对象', '扶持领域', '申报条件']
    cached = policy_cache.get(part_id)
    if not cached:
        return {'error': f"{part_id} not found"}

    struct_data = cached.get("struct_data", {})
    result = {target: struct_data.get(target, '无对应申报信息内容，请检查申报专项part_id是否正确。')
              for target in targets}
    return result
