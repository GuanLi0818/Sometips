# -*- coding: utf-8 -*-
"""
@File    : api_async.py
@Author  : qy
@Date    : 2025/10/27 15:03
"""


import json
import httpx
import asyncio

API_URL = "http://192.168.2.233:58000/v1/chat/completions"


async def call_local_model_async(prompt: str, stream: bool = True) -> str:
    """
    异步调用本地 Qwen3-32B 模型生成文本。

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

    result_text = ""

    async with httpx.AsyncClient(timeout=180.0) as client:
        if stream:
            async with client.stream("POST", API_URL, json=payload) as response:
                async for line in response.aiter_lines():
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
            response = await client.post(API_URL, json=payload)
            result_json = response.json()
            result_text = result_json["choices"][0]["message"]["content"]

    return result_text.strip()


# 测试入口
# if __name__ == "__main__":
#     async def main():
#         text = await call_local_model_async("你好，介绍一下你自己", stream=False)
#         print(text)
#
#     asyncio.run(main())
