# -*- coding: utf-8 -*-
"""
@File    : main17.py
@Author  : qy
@Date    : 2025/8/26
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, AsyncGenerator, Optional
import httpx
import logging
import json
import uuid
import asyncio
import time
import os
from datetime import datetime, timedelta

from starlette.responses import StreamingResponse
from company_info import CompanyInfo
from policy_utils import get_policy_info
from prompt import (
    build_policy_elements_prompt,
    build_company_judgment_prompt,
    empty_company_info_dict,
    build_company_standardization_prompt
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://mcc-pre.3xmt.com/gateway/ai-service/v1/chat/completions"
API_KEY = "sk-bFcPcwS7J7oP6e8LGo"

app = FastAPI()

# 会话历史存储文件路径
SESSION_HISTORY_FILE = "session_history.json"
# 会话过期时间（6小时）
EXPIRY_HOURS = 6
# 每个 session_id 的最大历史记录数
MAX_HISTORY_PER_SESSION = 10


def load_session_history() -> Dict[str, List[Dict[str, Any]]]:
    """从文件加载会话历史"""
    if os.path.exists(SESSION_HISTORY_FILE):
        try:
            with open(SESSION_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error("会话历史文件解析失败，返回空字典")
            return {}
    return {}


def save_session_history(history: Dict[str, List[Dict[str, Any]]]):
    """保存会话历史到文件"""
    try:
        with open(SESSION_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存会话历史失败: {str(e)}")


def clean_expired_sessions(history: Dict[str, List[Dict[str, Any]]], current_time: float,
                           session_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """清理过期会话"""
    cleaned_history = {}
    expiry_threshold = current_time - (EXPIRY_HOURS * 3600)
    for sid, messages in history.items():
        if not messages:
            continue
        # 检查最后一条记录的时间戳
        last_timestamp = messages[-1].get('timestamp', 0) if messages[-1].get('timestamp') else current_time
        if sid == session_id or last_timestamp >= expiry_threshold:
            cleaned_history[sid] = messages
        else:
            logger.info(
                f"清理过期会话: session_id={sid}, last_timestamp={datetime.fromtimestamp(last_timestamp).strftime('%Y-%m-%d %H:%M:%S')}")
    return cleaned_history


SESSION_HISTORY: Dict[str, List[Dict[str, Any]]] = load_session_history()


def merge_company_info(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """将 new 中非空字段合并到 old"""
    merged = old.copy()
    for k, v in new.items():
        if v is not None and (v != "" and (not isinstance(v, list) or len(v) > 0)):
            merged[k] = v
    return merged


def filter_non_empty_fields(d: dict) -> dict:
    result = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, list) and len(v) == 0:
            continue
        result[k] = v
    return result


class NewCheckRequest(BaseModel):
    part_id: str
    metadata: CompanyInfo
    user_input_text: Optional[str] = None
    session_id: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None


async def stream_model_response(prompt: str, buffer_size: int = 2, flush_interval: float = 0.06) -> AsyncGenerator[
    str, None]:
    payload = {
        "model": "deepseek-v3",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    buffer = ""
    finished = False

    async def fetch_model():
        nonlocal buffer, finished
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", API_URL, json=payload, headers=headers) as response:
                    async for line_bytes in response.aiter_lines():
                        if not line_bytes or not line_bytes.startswith("data:"):
                            continue
                        line_str = line_bytes[len("data:"):].strip()
                        if not line_str:
                            continue
                        try:
                            data = json.loads(line_str)
                            delta = data["choices"][0]["delta"].get("content", "")
                            if delta:
                                buffer += delta
                            finish_reason = data["choices"][0].get("finish_reason")
                            if finish_reason == "stop":
                                finished = True
                                break
                        except json.JSONDecodeError:
                            continue
        except httpx.RequestError:
            buffer += "[模型服务请求失败]"
            finished = True

    fetch_task = asyncio.create_task(fetch_model())

    try:
        while not finished or buffer:
            if buffer:
                out, buffer = buffer[:buffer_size], buffer[buffer_size:]
                yield out
            await asyncio.sleep(flush_interval)
        yield "\n"
    finally:
        fetch_task.cancel()
        await asyncio.sleep(0)


async def collect_model_output(prompt: str) -> str:
    result = ""
    async for chunk in stream_model_response(prompt, buffer_size=64, flush_interval=0.02):
        result += chunk
    return result.strip()


async def chunked_response(generator: AsyncGenerator[Dict[str, Any], None]):
    async def iterate():
        async for text_dict in generator:
            text_bytes = json.dumps(text_dict, ensure_ascii=False).encode("utf-8")
            output = b"data:" + text_bytes + b"\n\n"
            yield output

    return StreamingResponse(iterate(), media_type="text/event-stream")


@app.post("/check_policy")
async def check_policy(req: NewCheckRequest):
    # 获取当前时间戳
    current_time = time.time()

    # 清理过期会话，保留当前 session_id 的记录
    global SESSION_HISTORY
    SESSION_HISTORY = clean_expired_sessions(SESSION_HISTORY, current_time, req.session_id or str(uuid.uuid4()))
    save_session_history(SESSION_HISTORY)

    # 使用 session_id，如果没有就新建
    session_id = req.session_id or str(uuid.uuid4())
    if session_id not in SESSION_HISTORY:
        SESSION_HISTORY[session_id] = []

    # 初始化基础公司信息
    base_company_info = req.metadata.dict()

    # 获取最新的公司信息 - 优先使用会话历史中的最新信息，没有则使用基础信息
    if SESSION_HISTORY[session_id]:
        last_message = SESSION_HISTORY[session_id][-1]['content']
        if isinstance(last_message, str):
            try:
                last_company_info = json.loads(last_message)
            except json.JSONDecodeError:
                last_company_info = base_company_info
        else:
            last_company_info = last_message
    else:
        last_company_info = base_company_info


    # 获取政策信息
    policy_info = get_policy_info(req.part_id)
    if "error" in policy_info:
        raise HTTPException(status_code=404, detail='未找到该申报专项政策')

    # 构建政策要素提示词（可以立即执行，不依赖标准化）
    policy_elements_prompt = build_policy_elements_prompt(req.part_id, policy_info)

    first_intro = (
        "欢迎进入智能帮办环节，我可以为您提供智能匹配、智能体检、智能填报等环节的申报全流程智能辅助服务，"
        "您可以点击此处查看为您推荐的相关申报政策。您也可以直接告诉我想要申报的政策，由我提供智能体检服务。\n"
        "下面展示申请专项政策要素：\n"
    )
    second_intro = (
        "经AI对政策申报要求与贵司画像特征智能分析，您当前还不满足政策申报条件，"
        "还存在以下条件需要由您确认：\n"
    )

    created_ts = int(current_time)
    choice_index = 0

    async def event_stream() -> AsyncGenerator[Dict[str, Any], None]:
        nonlocal choice_index

        queue1: asyncio.Queue[str] = asyncio.Queue()
        queue2: asyncio.Queue[str] = asyncio.Queue()

        async def model_task(prompt: str, queue: asyncio.Queue):
            async for chunk in stream_model_response(prompt):
                await queue.put(chunk)
            await queue.put(None)

        # 🔹 标准化任务
        async def standardize_user_input(user_input_text: str, last_company_info: Dict[str, Any]):
            standardization_prompt = build_company_standardization_prompt(user_input_text)
            standardized_info_str = await collect_model_output(standardization_prompt)
            standardized_info_str = standardized_info_str.strip("```json").strip("```").strip()
            try:
                standardized_info_dict = json.loads(standardized_info_str)
            except json.JSONDecodeError:
                logger.warning(f"无法解析标准化信息: {standardized_info_str}")
                standardized_info_dict = {}
            merged_info = merge_company_info(last_company_info, standardized_info_dict)
            merged_info = merge_company_info(empty_company_info_dict(), merged_info)
            return merged_info

        if req.user_input_text and req.user_input_text.strip():
            standardize_task = asyncio.create_task(standardize_user_input(req.user_input_text, last_company_info))
        else:
            async def return_last_info():
                merged_info = merge_company_info(empty_company_info_dict(), last_company_info)
                return merged_info
            standardize_task = asyncio.create_task(return_last_info())

        # 🔹 模型任务1：政策要素（立即跑）
        task1 = asyncio.create_task(model_task(policy_elements_prompt, queue1))

        # 🔹 模型任务2：企业判断（等待标准化后再跑）
        async def wait_and_run_judgment():
            merged_info = await standardize_task

            logger.info(f"[调试] 更新后要送给大模型的公司信息: {json.dumps(merged_info, ensure_ascii=False, indent=2)}")

            new_message = {
                "role": "user",
                "content": filter_non_empty_fields(merged_info),
                "timestamp": time.time()
            }
            SESSION_HISTORY[session_id].append(new_message)
            if len(SESSION_HISTORY[session_id]) > MAX_HISTORY_PER_SESSION:
                SESSION_HISTORY[session_id] = SESSION_HISTORY[session_id][-MAX_HISTORY_PER_SESSION:]
            save_session_history(SESSION_HISTORY)

            # 再构建企业判断提示词
            company_judgment_prompt = build_company_judgment_prompt(merged_info, policy_info)
            await model_task(company_judgment_prompt, queue2)

        task2 = asyncio.create_task(wait_and_run_judgment())

        # 打字机效果输出
        async def send_typing_text_json(text: str, speed: float = 0.06) -> AsyncGenerator[Dict[str, Any], None]:
            nonlocal choice_index
            buffer = text
            while buffer:
                out, buffer = buffer[:2], buffer[2:]
                chunk_data = {
                    "id": session_id,
                    "model": "deepseek-v3",
                    "created": created_ts,
                    "part_id": req.part_id,
                    "choices": [
                        {
                            "index": choice_index,
                            "finish_reason": None,
                            "message": {
                                "content": out,
                                "role": "assistant"
                            }
                        }
                    ]
                }
                choice_index += 1
                yield chunk_data
                await asyncio.sleep(speed)

        # 输出开头语1
        async for chunk in send_typing_text_json(first_intro):
            yield chunk

        # 消费模型1 - 政策要素
        while True:
            chunk = await queue1.get()
            if chunk is None:
                break
            yield {
                "id": session_id,
                "model": "deepseek-v3",
                "created": created_ts,
                "part_id": req.part_id,
                "choices": [
                    {
                        "index": choice_index,
                        "finish_reason": None,
                        "message": {
                            "content": chunk,
                            "role": "assistant"
                        }
                    }
                ]
            }
            choice_index += 1

        # 空行分隔
        yield {
            "id": session_id,
            "model": "deepseek-v3",
            "created": created_ts,
            "part_id": req.part_id,
            "choices": [
                {
                    "index": choice_index,
                    "finish_reason": None,
                    "message": {"content": "", "role": "assistant"}
                }
            ]
        }
        choice_index += 1

        # 输出开头语2
        async for chunk in send_typing_text_json(second_intro):
            yield chunk

        # 消费模型2 - 企业判断
        last_chunk = None
        while True:
            chunk = await queue2.get()
            if chunk is None:
                break
            last_chunk = chunk
            yield {
                "id": session_id,
                "model": "deepseek-v3",
                "created": created_ts,
                "part_id": req.part_id,
                "choices": [
                    {
                        "index": choice_index,
                        "finish_reason": None,
                        "message": {
                            "content": chunk,
                            "role": "assistant"
                        }
                    }
                ]
            }
            choice_index += 1

        if last_chunk is not None:
            yield {
                "id": session_id,
                "model": "deepseek-v3",
                "created": created_ts,
                "part_id": req.part_id,
                "choices": [
                    {
                        "index": choice_index,
                        "finish_reason": "stop",
                        "message": {
                            "content": last_chunk,
                            "role": "assistant"
                        }
                    }
                ]
            }

    return await chunked_response(event_stream())



if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app="main17:app", workers=1, host="0.0.0.0", port=8001, reload=False)
