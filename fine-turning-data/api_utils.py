# -*- coding: utf-8 -*-
"""
@File    : api_utils.py
@Author  : qy
@Date    : 2025/10/9 10:34
"""


import requests
import json

API_URL = "http://192.168.2.233:58000/v1/chat/completions"



def call_local_model(prompt: str, stream: bool = True) -> str:
    """
    调用本地 Qwen3-32B 模型生成文本。

    参数：
        prompt (str): 输入提示词
        stream (bool): 是否启用流式返回，默认 True

    返回：
        str: 模型最终生成的文本内容
    """

    payload = {
        "model": "qwen3_32b",
        "messages": [{"role": "user", "content": prompt}],
        "chat_template_kwargs": {"enable_thinking": False},
        "temperature": 1.1,
        "top_k": 50,
        "top_p": 0.99,
        "stream": stream,
    }

    response = requests.post(API_URL, json=payload, stream=stream, timeout=180)

    result_text = ""
    if stream:
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            line_data = line[6:]
            if line_data.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(line_data)
                delta = chunk["choices"][0].get("delta", {}).get("content", "")
                result_text += delta
            except Exception:
                continue
    else:
        result_json = response.json()
        result_text = result_json["choices"][0]["message"]["content"]

    return result_text.strip()

# print(call_local_model(prompt,stream=False))