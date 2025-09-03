# -*- coding: utf-8 -*-
"""
@File    : main17.py
@Author  : qy
@Date    : 2025/8/26
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, AsyncGenerator, Optional, Any
import httpx
import logging
import json
import uuid
import asyncio
import time
import os
from contextlib import asynccontextmanager

from starlette.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse
from company_info import CompanyInfo
from policy_utils import get_policy_info
from prompt import (
    build_policy_elements_prompt,
    build_company_judgment_prompt,
    build_company_standardization_prompt
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "http://192.168.2.233:58000/v1/chat/completions"
SESSIONS_FILE = "sessions.json"
MAX_RECORDS = 20
EXPIRY_HOURS = 1

# -------------------------- 请求/响应模型 --------------------------
class NewCheckRequest(BaseModel):
    part_id: str
    metadata: CompanyInfo
    user_input_text: Optional[str] = None
    session_id: str

class PolicyStreamResponse(BaseModel):
    id: str
    model: str
    created: int
    part_id: str
    choices: List[Dict[str, Any]]

# -------------------------- Session 存储与清理 --------------------------
def load_sessions() -> Dict[str, Any]:
    """从 sessions.json 读取会话记录，如果不存在则返回空字典"""
    if not os.path.exists(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_sessions(sessions: Dict[str, Any]):
    """把 sessions 数据写入到 sessions.json"""
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)

def save_session_record(session_id: str, merged_info: str, part_id: str):
    """
    保存用户输入或公司信息的记录。
    - 如果是某个 part_id 第一次保存，标记 first_output_done=True
    - 只保留最多 MAX_RECORDS 条
    """
    if not merged_info:
        return
    now = time.time()
    sessions = load_sessions()
    cleanup_sessions(sessions)
    if session_id not in sessions:
        sessions[session_id] = {"records": [], "last_update": now}
    session = sessions[session_id]

    first_done = not any(rec["part_id"] == part_id for rec in session["records"])

    session["records"].append({
        "role": "user",
        "content": merged_info,
        "part_id": part_id,
        "first_output_done": first_done
    })
    if len(session["records"]) > MAX_RECORDS:
        session["records"] = session["records"][-MAX_RECORDS:]
    session["last_update"] = now
    save_sessions(sessions)

def check_first_output_done(session_id: str, part_id: str) -> bool:
    """检查某个 session_id 的 part_id 是否已经输出过首段介绍"""
    sessions = load_sessions()
    for rec in sessions.get(session_id, {}).get("records", []):
        if rec["part_id"] == part_id:
            return rec.get("first_output_done", False)
    return False

def cleanup_sessions(sessions: Optional[Dict[str, Any]] = None):
    """清理过期的 session（超过 EXPIRY_HOURS 小时未更新）"""
    if sessions is None:
        sessions = load_sessions()
    now = time.time()
    expired = [sid for sid, data in sessions.items()
               if now - data.get("last_update", 0) > EXPIRY_HOURS * 3600]
    for sid in expired:
        del sessions[sid]
    save_sessions(sessions)
    if expired:
        logger.info(f"定期清理 session 完成，删除 {len(expired)} 个过期 session")

async def periodic_cleanup(interval_hours: float = 1):
    """后台定时任务，每隔 interval_hours 小时执行 cleanup_sessions 一次"""
    while True:
        cleanup_sessions()
        await asyncio.sleep(interval_hours * 3600)

# -------------------------- FastAPI lifespan --------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(periodic_cleanup(interval_hours=0.5))
    yield

app = FastAPI(lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    # 显式地添加 'OPTIONS'
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


# -------------------------- 模型调用函数 --------------------------
async def stream_model_response(prompt: str, buffer_size: int = 2, flush_interval: float = 0.04) -> AsyncGenerator[str, None]:
    """
    调用大模型的流式接口：
    - 发送 prompt
    - 每次返回 buffer_size 个字符
    - flush_interval 控制输出间隔
    """
    payload = {
        "model": "qwen3_32b",
        "messages": [{"role": "user", "content": prompt}],
        "chat_template_kwargs": {"enable_thinking": False},
        "temperature": 0.6,
        "top_k": 50,
        "stream": True
    }
    buffer = ""
    finished = False

    async def fetch_model():
        """子任务：从模型服务获取流式响应，并把内容写入 buffer"""
        nonlocal buffer, finished
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", API_URL, json=payload) as response:
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
                            if data["choices"][0].get("finish_reason") == "stop":
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
    """收集模型完整输出（非流式，拼接为字符串返回）"""
    result = ""
    async for chunk in stream_model_response(prompt, buffer_size=64, flush_interval=0.02):
        result += chunk
    return result.strip()

# -------------------------- 工具函数 --------------------------
def remove_empty_values(data: Dict[str, Any]) -> Dict[str, Any]:
    """去掉字典中 None、空字符串、空列表的字段"""
    cleaned_data = {}
    for key, value in data.items():
        if value is None:
            continue
        elif isinstance(value, list) and len(value) == 0:
            continue
        elif isinstance(value, str) and value.strip() == "":
            continue
        cleaned_data[key] = value
    return cleaned_data

# -------------------------- SSE流式响应 --------------------------
async def chunked_response(generator: AsyncGenerator[Dict[str, Any], None]):
    """把生成器的字典转换成 SSE (Server-Sent Events) 格式输出"""
    async def iterate():
        async for resp_dict in generator:
            resp_bytes = json.dumps(resp_dict, ensure_ascii=False).encode("utf-8")
            yield b"data:" + resp_bytes + b"\n\n"
    return StreamingResponse(iterate(), media_type="text/event-stream")

# -------------------------- 核心接口 --------------------------
@app.post("/check_policy")
async def check_policy(req: NewCheckRequest):
    """
    核心接口：
    1. 校验输入参数（必须有 session_id）
    2. 根据 part_id 获取政策信息
    3. 根据是否首次输出，生成政策要素、公司体检结果
    4. 通过流式 SSE 返回
    """
    if not req.session_id or not req.session_id.strip():
        raise HTTPException(status_code=400, detail="必须传入 session_id")

    policy_info = get_policy_info(req.part_id)
    if "error" in policy_info:
        raise HTTPException(status_code=404, detail='未找到该申报专项政策ID。')

    policy_elements_prompt = build_policy_elements_prompt(req.part_id, policy_info)
    session_id = req.session_id
    choice_index = 0

    async def event_stream() -> AsyncGenerator[Dict[str, Any], None]:
        """内部生成器：控制首段介绍、政策要素、公司体检、输出顺序"""
        nonlocal choice_index
        stream_id = str(uuid.uuid4())
        created_ts = int(time.time())
        first_output_done = check_first_output_done(session_id, req.part_id)

        # 标记 发一个初始空响应
        yield PolicyStreamResponse(
            id=stream_id,
            model="qwen3_32b",
            created=created_ts,
            part_id=req.part_id,
            choices=[{
                "index": -1,
                "finish_reason": None,
                "message": {"content": "", "role": "assistant"}
            }],
        ).dict() | {"first_chunk": True}

        elem_queue: asyncio.Queue[str] = asyncio.Queue()
        judge_queue: asyncio.Queue[str] = asyncio.Queue()

        async def model_to_queue(prompt: str, queue: asyncio.Queue):
            """把模型流式输出写入队列"""
            async for chunk in stream_model_response(prompt):
                await queue.put(chunk)
            await queue.put(None)

        async def run_standardization() -> Dict[str, Any]:
            """标准化公司信息，基于历史最新记录进行合并"""
            # 先取历史最新记录
            sessions = load_sessions()
            session = sessions.get(session_id, {})
            records = session.get("records", [])

            if records:
                try:
                    # 取最后一次非空记录（最新的 merged_info）
                    last_record = next(
                        rec for rec in reversed(records) if rec.get("content")
                    )
                    merged_info = json.loads(last_record["content"])
                except Exception:
                    merged_info = req.metadata.dict().copy()
            else:
                merged_info = req.metadata.dict().copy()

            # 如果用户没有输入，直接返回最新的 merged_info
            if not req.user_input_text or not req.user_input_text.strip():
                cleaned = remove_empty_values(merged_info)
                logger.info(f"当前公司信息：{json.dumps(cleaned, ensure_ascii=False, indent=2)}")
                save_session_record(session_id, json.dumps(cleaned, ensure_ascii=False),
                                    req.part_id)
                return cleaned

            # 调用大模型做标准化
            std_prompt = build_company_standardization_prompt(req.user_input_text)
            std_result = await collect_model_output(std_prompt)

            # 解析结果
            new_data = {}
            for line in std_result.splitlines():
                line = line.strip()
                if not line or '": ' not in line:
                    continue
                key_part, value_part = line.split('": ', 1)
                key = key_part.strip('"')
                value_str = value_part.strip().rstrip(',').strip()
                if value_str.startswith("[") and value_str.endswith("]"):
                    try:
                        value = [v.strip().strip('"') for v in value_str[1:-1].split(",")]
                    except:
                        value = value_str
                else:
                    value = value_str.strip('"')
                new_data[key] = value

            # 合并新数据到历史 merged_info
            for k, v in new_data.items():
                if k in merged_info and isinstance(merged_info[k], list) and isinstance(v, list):
                    merged_info[k] = list(dict.fromkeys(merged_info[k] + v))
                else:
                    merged_info[k] = v

            cleaned = remove_empty_values(merged_info)
            save_session_record(session_id, json.dumps(cleaned, ensure_ascii=False),
                                req.part_id)
            logger.info(f"送给大模型的公司信息：{json.dumps(cleaned, ensure_ascii=False, indent=2)}")
            return cleaned

        std_task = asyncio.create_task(run_standardization())

        if not first_output_done:
            elem_task = asyncio.create_task(model_to_queue(policy_elements_prompt, elem_queue))
        else:
            elem_task = None

        async def run_judgment():
            """调用模型，对公司与政策进行分析"""
            cleaned_info = await std_task
            judge_prompt = build_company_judgment_prompt(cleaned_info, policy_info)
            await model_to_queue(judge_prompt, judge_queue)

        judge_task = asyncio.create_task(run_judgment())

        async def typing_output(text: str) -> AsyncGenerator[Dict[str, Any], None]:
            """模拟打字机效果，把 text 分批次流式输出"""
            nonlocal choice_index
            for i in range(0, len(text), 2):
                chunk_text = text[i:i + 2]
                yield PolicyStreamResponse(
                    id=stream_id,
                    model="qwen3_32b",
                    created=created_ts,
                    part_id=req.part_id,
                    choices=[{
                        "index": choice_index,
                        "finish_reason": None,
                        "message": {"content": chunk_text, "role": "assistant"}
                    }]
                ).dict()
                choice_index += 1
                await asyncio.sleep(0.04)

        # ---------- 首次输出 ----------
        if not first_output_done:
            first_intro = (
                "欢迎进入智能帮办环节，我可以为您提供智能匹配、智能体检、智能填报等环节的申报全流程智能辅助服务，"
                "您可以点击此处查看为您推荐的相关申报政策。您也可以直接告诉我想要申报的政策，由我提供智能体检服务。\n"
                "下面展示申请专项政策要素：\n"
            )
            async for chunk in typing_output(first_intro):
                yield chunk

            while True:
                elem_chunk = await elem_queue.get()
                if elem_chunk is None:
                    break
                yield PolicyStreamResponse(
                    id=stream_id,
                    model="qwen3_32b",
                    created=created_ts,
                    part_id=req.part_id,
                    choices=[{
                        "index": choice_index,
                        "finish_reason": None,
                        "message": {"content": elem_chunk, "role": "assistant"}
                    }]
                ).dict()
                choice_index += 1

            save_session_record(session_id, "", req.part_id)

        # ---------- 后续输出 ----------
        second_intro = (
            "经AI对政策申报要求与贵司画像特征智能分析，您当前还不满足政策申报条件，"
            "还存在以下条件需要由您确认：\n"
        )
        async for chunk in typing_output(second_intro):
            yield chunk

        last_judge_chunk = None
        while True:
            judge_chunk = await judge_queue.get()
            if judge_chunk is None:
                break
            last_judge_chunk = judge_chunk
            yield PolicyStreamResponse(
                id=stream_id,
                model="qwen3_32b",
                created=created_ts,
                part_id=req.part_id,
                choices=[{
                    "index": choice_index,
                    "finish_reason": None,
                    "message": {"content": judge_chunk, "role": "assistant"}
                }]
            ).dict()
            choice_index += 1

        if last_judge_chunk is not None:
            yield PolicyStreamResponse(
                id=stream_id,
                model="qwen3_32b",
                created=created_ts,
                part_id=req.part_id,
                choices=[{
                    "index": choice_index,
                    "finish_reason": "stop",
                    "message": {"content": "", "role": "assistant"}
                }]
            ).dict()
            choice_index += 1

    return await chunked_response(event_stream())


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app="qwen32:app", workers=1, host="0.0.0.0", port=8002, reload=False)
