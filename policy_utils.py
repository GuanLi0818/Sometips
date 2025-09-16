# -*- coding: utf-8 -*-
"""
@File    : policy_utils.py
@Author  : qy
@Date    : 2025/7/25 10:30
"""
import requests
from typing import Dict, Any

API_URL = "http://192.168.2.233:21351/query/get_part"


def get_policy_info(part_id: str) -> Dict[str, Any]:
    """
    调用接口获取政策信息（申报对象、扶持领域、申报条件、文件名）
    返回完整字典
    """
    targets = ['申报对象', '扶持领域', '申报条件']

    try:
        resp = requests.post(API_URL, json={"part_id": part_id}, timeout=10)
        resp.raise_for_status()  # 触发 HTTP 错误（如 404、500）

        # 关键修复：强制用 UTF-8 解码响应内容，避免中文乱码
        resp.encoding = "utf-8"  # 手动指定编码
        data = resp.json()  # 基于正确编码解析 JSON

    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP请求错误: {e}"}  # 细分HTTP错误
    except requests.exceptions.Timeout as e:
        return {"error": f"请求超时: {e}"}  # 细分超时错误
    except Exception as e:
        return {"error": f"接口请求失败: {e}"}  # 其他通用错误

    if not data.get("success"):
        return {"error": data.get("error_msg", "接口返回失败")}

    rows = data.get("data", [])
    if not rows:
        return {"error": f"未找到 {part_id} 的政策数据"}

    row = rows[0]
    struct_data = row.get("struct_data", {})



    # 获取文件名（处理可能的中文乱码）
    file_name = row.get("file_name", f"政策 {part_id}")
    # 额外保险：若文件名仍乱码，尝试用UTF-8重新解码（部分接口可能单独对文件名编码）
    if isinstance(file_name, str) and any(ord(c) > 127 for c in file_name):
        try:
            file_name = file_name.encode("latin-1").decode("utf-8")
        except:
            pass  # 解码失败则保留原内容

    # 匹配目标字段（修复后键名正常，可直接匹配）
    result = {}
    for target in targets:
        # 直接匹配（若键名有空格，可保留原逻辑用 k.strip() 匹配）
        result[target] = struct_data.get(target, f"未找到【{target}】字段")

    result["file_name"] = file_name
    return result


# 测试调用
# s = get_policy_info("ZXZC039")
# print("最终结果:", s)


# === 单字段封装函数 ===

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




