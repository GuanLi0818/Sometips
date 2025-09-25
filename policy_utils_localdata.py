# -*- coding: utf-8 -*-
"""
@File    : policy_utils_localdata.py
@Author  : qy
@Date    : 2025/9/23 14:36
"""
import json
from typing import Dict,Any


#加载数据
with open('data/database.json', 'r', encoding='utf-8') as f:
    ori_data = json.load(f)
    parts = ori_data.get('parts', {})


#生成缓存
policy_cache: Dict[str, Dict[str, Any]] = {}
policy_toolbox_parts = ori_data.get('debug_data', '').get('policy_toolbox_parts', '')

for part_id, pdata in parts.items():
    struct_data =  pdata["ext_data"]["struct_data"]
    file_name = policy_toolbox_parts.get(part_id, {}).get("file_name", "未知文件名")

    policy_cache[part_id] = {"file_name": file_name, "struct_data": struct_data}



#获取政策信息

def get_policy_info(part_id:str) ->Dict:

    targets = ['申报对象', '扶持领域', '申报条件']
    cached = policy_cache.get(part_id)
    if not cached:
        return {"error": "part_id not found"}

    struct_data = cached["struct_data"]
    result ={"file_name":cached['file_name']}

    result.update({target: struct_data.get(target, '无对应申报信息内容，请检查申报专项part_id是否正确。') for target in targets})

    return result


def get_policy_object(part_id: str) -> str:
    """获取申报对象"""
    return get_policy_info(part_id).get("申报对象", "")

def get_policy_domain(part_id: str) -> str:
    """获取扶持领域"""
    return get_policy_info(part_id).get("扶持领域", "")

def get_policy_condition(part_id: str) -> str:
    """获取申报条件"""
    return get_policy_info(part_id).get("申报条件", "")




def get_policy_filename(part_id: str) -> str:
    """获取文件名"""
    return get_policy_info(part_id).get("file_name", "")


def format_polict_text(part_id: str) -> str:

    polict_info = get_policy_info(part_id)
    targets = ['申报对象', '扶持领域', '申报条件']

    policy_text_lines = [f"{key}:{polict_info.get(key, '')}" for key in targets]

    return "\n".join(policy_text_lines)

# print(get_policy_object('1229329955961991168'))
# print(get_policy_domain('1229329955961991168'))
# print(get_policy_condition('1229329955961991168'))
# print(get_policy_filename("1229329955961991168"))
# print(format_polict_text("1229329955961991168"))
