# -*- coding: utf-8 -*-
"""
@File    : ds-v3.py
@Author  : qy
@Date    : 2025/8/8 10:27
"""
# 你的 demo_ds.py 保留不变，这里新增新的 Pydantic 模型和接口

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, AsyncGenerator
import json
import httpx
import logging
from company_info import CompanyInfo   # 直接引入你的 Pydantic 模型
from policy_utils import get_policy_info, parts
from policy_prompt import build_policy_prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://mcc-pre.3xmt.com/gateway/ai-service/v1/chat/completions"
API_KEY = "sk-bFcPcwS7J7oP6e8LGo"

app = FastAPI()

def empty_company_info_dict() -> Dict[str, Any]:
    """
    根据 CompanyInfo 模型自动生成空结构
    - 字符串字段: ""
    - 数字字段: None
    - 列表字段: []
    """
    example = CompanyInfo.model_json_schema()["properties"]
    result = {}
    for field_name, field_info in example.items():
        t = field_info.get("type")
        if t == "string":
            result[field_name] = ""
        elif t == "integer" or t == "number":
            result[field_name] = None
        elif t == "array":
            result[field_name] = []
        else:
            result[field_name] = None
    return result


async def llm_stream_generator(prompt: str, part_id: str) -> AsyncGenerator[str, None]:
    payload = {
        "stream": True,
        "model": "deepseek-v3",
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "metadata": {
                    "company_info": empty_company_info_dict(),
                    "part_id": part_id,
                }
            }
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    accumulated_content = ""
    final_id = None
    final_model = None

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", API_URL, json=payload, headers=headers) as response:
            async for line_bytes in response.aiter_lines():
                if not line_bytes:
                    continue
                line_str = line_bytes.lstrip("data:").strip()
                try:
                    data_json = json.loads(line_str)
                except json.JSONDecodeError:
                    continue
                if final_id is None:
                    final_id = data_json.get("id")
                if final_model is None:
                    final_model = data_json.get("model")
                choice = data_json.get("choices", [{}])[0]
                chunk = choice.get("delta", {}).get("content", "")
                if chunk:
                    accumulated_content += chunk
                finish_reason = choice.get("finish_reason")
                if finish_reason == "stop":
                    result_dict = {
                        "id": final_id,
                        "model": final_model,
                        "part_id": part_id,
                        "status": "done",
                        "data_content": accumulated_content,
                    }
                    yield f" {json.dumps(result_dict, ensure_ascii=False)}\n\n"
                    break


class MessageMetadata(BaseModel):
    company_info: Dict[str, Any]
    part_id: str

class Message(BaseModel):
    role: str
    content: str
    metadata: MessageMetadata

class FullRequest(BaseModel):
    stream: bool
    model: str
    messages: List[Message]


@app.post("/check_policy")
async def check_policy(request: FullRequest):
    message = request.messages[0]
    company_info_raw = message.metadata.company_info
    part_id = message.metadata.part_id

    policy_info = get_policy_info(parts, part_id)
    if "error" in policy_info:
        raise HTTPException(status_code=404, detail='未找到该申报专项政策,请检查part_id是否正确。')

    company_data = {
        k: v for k, v in company_info_raw.items()
        if v not in [None, ""] and (not isinstance(v, list) or len(v) > 0)
    }

    company_info_text = "\n".join(f"{k}: {v}" for k, v in company_data.items())
    policy_text = "\n".join(f"{k}: {v}" for k, v in policy_info.items())
    prompt = build_policy_prompt(company_info_text, policy_text)

    return StreamingResponse(
        llm_stream_generator(prompt, part_id),
        media_type="application/json"
    )


if __name__ == '__main__':
    import uvicorn
    uvicorn.run("ds-v3:app", host="0.0.0.0", port=8500)


