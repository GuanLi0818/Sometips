# -*- coding: utf-8 -*-
"""
@File    : deepseek_r1.py
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

API_URL = "https://mcc-pre.3xmt.com/gateway/ai-service/v1/chat/completions"
API_KEY = "sk-bFcPcwS7J7oP6e8LGo"

SESSIONS_FILE = "sessions.json"
MAX_RECORDS = 20
EXPIRY_HOURS = 1

class NewCheckRequest(BaseModel):
    part_id: str
    metadata: CompanyInfo
    user_input_text: Optional[str] = None
    session_id: str
    check_mode: int = 1

class PolicyStreamResponse(BaseModel):
    id: str
    model: str
    created: int
    part_id: str
    choices: List[Dict[str, Any]]


# -------------------------- Session 存储与清理 --------------------------
class BaseUtils:
    @staticmethod
    def remove_empty_values(data: Dict[str, Any]) -> Dict[str, Any]:
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

    @staticmethod
    def load_json(file: str) -> Dict[str, Any]:
        if not os.path.exists(file):
            return {}
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def save_json(file: str, data: Dict[str, Any]):
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

baseutils =  BaseUtils()
# -------------------------- 会话管理类 --------------------------
class SessionManager:
    def __init__(self, file_path: str = SESSIONS_FILE, max_records: int = MAX_RECORDS, expiry_hours: int = EXPIRY_HOURS):
        self.file_path = file_path
        self.max_records = max_records
        self.expiry_hours = expiry_hours

    def load_sessions(self) -> Dict[str, Any]:
        return baseutils.load_json(self.file_path)

    def save_sessions(self, sessions: Dict[str, Any]):
        baseutils.save_json(self.file_path, sessions)

    def save_session_record(self, session_id: str, merged_info: str, part_id: str, user_input_text: Optional[str] = None):
        if not merged_info:
            return
        now = time.time()
        sessions = self.load_sessions()
        self.cleanup_sessions(sessions)

        if session_id not in sessions:
            sessions[session_id] = {"records": [], "last_update": now}
        session = sessions[session_id]

        first_done = not any(rec["part_id"] == part_id for rec in session["records"])
        session["records"].append({
            "role": "user",
            "user_input_text": user_input_text,
            "content": merged_info,
            "part_id": part_id,
            "first_output_done": first_done
        })
        if len(session["records"]) > self.max_records:
            session["records"] = session["records"][-self.max_records:]
        session["last_update"] = now
        self.save_sessions(sessions)

    def check_first_output_done(self, session_id: str, part_id: str) -> bool:
        sessions = self.load_sessions()
        for rec in sessions.get(session_id, {}).get("records", []):
            if rec["part_id"] == part_id:
                return rec.get("first_output_done", False)
        return False

    def cleanup_sessions(self, sessions: Optional[Dict[str, Any]] = None):
        if sessions is None:
            sessions = self.load_sessions()
        now = time.time()
        expired = [sid for sid, data in sessions.items()
                   if now - data.get("last_update", 0) > self.expiry_hours * 3600]
        for sid in expired:
            del sessions[sid]
        self.save_sessions(sessions)
        if expired:
            logger.info(f"定期清理 session 完成，删除 {len(expired)} 个过期 session")

    async def periodic_cleanup(self, interval_hours: float = 1):
        while True:
            self.cleanup_sessions()
            await asyncio.sleep(interval_hours * 3600)

# -------------------------- 大模型调用类 --------------------------
class LLMClient:
    def __init__(self, api_url: str = API_URL):
        self.api_url = api_url

    async def stream_model_response(self, prompt: str, buffer_size: int = 2, flush_interval: float = 0.04) -> AsyncGenerator[str, None]:
        payload = {
            "model": "qwen3_32b",
            "messages": [{"role": "user", "content": prompt}],
            "chat_template_kwargs": {"enable_thinking": False},
            "temperature": 0.25,
            "top_k": 3,
            "top_p": 0.9,
            "stream": True
        }
        buffer = ""
        finished = False

        async def fetch_model():
            nonlocal buffer, finished
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("POST", self.api_url, json=payload) as response:
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

    async def collect_model_output(self, prompt: str) -> str:
        result = ""
        async for chunk in self.stream_model_response(prompt, buffer_size=64, flush_interval=0.02):
            result += chunk
        return result.strip()

# -------------------------- SSE流式响应 --------------------------
async def chunked_response(generator: AsyncGenerator[Dict[str, Any], None]):
    async def iterate():
        async for resp_dict in generator:
            resp_bytes = json.dumps(resp_dict, ensure_ascii=False).encode("utf-8")
            yield b"data:" + resp_bytes + b"\n\n"
    return StreamingResponse(iterate(), media_type="text/event-stream")

# -------------------------- FastAPI应用 --------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(session_manager.periodic_cleanup(interval_hours=0.5))
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

session_manager = SessionManager()
llm_client = LLMClient()


# -------------------------- API --------------------------
@app.post("/check_policy")
async def check_policy(req: NewCheckRequest):
    """
       核心接口：
       1. 校验输入参数（必须有 session_id）
       2. 根据 part_id 获取政策信息
       3. 根据是否首次输出，生成政策要素、公司体检结果
       4. 通过流式 SSE 返回
       """
    if req.check_mode == 1:
        if not req.session_id or not req.session_id.strip():
            raise HTTPException(status_code=400, detail="必须传入 session_id")

        policy_info = get_policy_info(req.part_id)
        if "error" in policy_info:
            raise HTTPException(status_code=404, detail='未找到该申报专项政策ID。')

        policy_elements_prompt = build_policy_elements_prompt(req.part_id, policy_info)
        session_id = req.session_id
        choice_index = 0

        async def event_stream() -> AsyncGenerator[Dict[str, Any], None]:
            nonlocal choice_index
            stream_id = str(uuid.uuid4())
            created_ts = int(time.time())
            first_output_done = session_manager.check_first_output_done(session_id, req.part_id)

            #标记
            yield PolicyStreamResponse(
                id=stream_id,
                model="deepseek-v3",
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
                async for chunk in llm_client.stream_model_response(prompt):
                    await queue.put(chunk)
                await queue.put(None)

            async def run_standardization() -> Dict[str, Any]:
                merged_info = req.metadata.dict().copy()
                if not req.user_input_text or not req.user_input_text.strip():
                    cleaned = baseutils.remove_empty_values(merged_info)
                    logger.info(f"原始公司信息：{json.dumps(cleaned, ensure_ascii=False, indent=2)}")
                    session_manager.save_session_record(session_id, json.dumps(cleaned, ensure_ascii=False),
                                        req.part_id, req.user_input_text)
                    return cleaned

                std_prompt = build_company_standardization_prompt(req.user_input_text)
                std_result = await llm_client.collect_model_output(std_prompt)
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

                for k, v in new_data.items():
                    if k in merged_info and isinstance(merged_info[k], list) and isinstance(v, list):
                        merged_info[k] = list(dict.fromkeys(merged_info[k] + v))
                    else:
                        merged_info[k] = v
                cleaned = baseutils.remove_empty_values(merged_info)
                session_manager.save_session_record(session_id, json.dumps(cleaned, ensure_ascii=False),
                                    req.part_id,req.user_input_text)
                logger.info(f"送给大模型的公司信息：{json.dumps(cleaned, ensure_ascii=False, indent=2)}")
                return cleaned

            std_task = asyncio.create_task(run_standardization())

            if not first_output_done:
                elem_task = asyncio.create_task(model_to_queue(policy_elements_prompt, elem_queue))
            else:
                elem_task = None

            async def run_judgment():
                cleaned_info = await std_task
                sessions = session_manager.load_sessions()
                session = sessions.get(session_id, {})
                records = session.get("records", [])
                history_inputs = [
                    rec.get("user_input_text", "").strip()
                    for rec in records
                    if rec.get("user_input_text") and rec["part_id"] == req.part_id
                ]
                history_inputs = list(dict.fromkeys(history_inputs))

                history_text = "\n".join(history_inputs)
                print(f"=========== history_text======\n{history_text}")
                print("===============================")

                judge_prompt = build_company_judgment_prompt(
                    cleaned_info,
                    policy_info,
                    extra_user_inputs=history_text,
                    check_mode=req.check_mode
                )

                await model_to_queue(judge_prompt, judge_queue)

            judge_task = asyncio.create_task(run_judgment())

            async def typing_output(text: str) -> AsyncGenerator[Dict[str, Any], None]:
                nonlocal choice_index
                for i in range(0, len(text), 2):
                    chunk_text = text[i:i + 2]
                    yield PolicyStreamResponse(
                        id=stream_id,
                        model="deepseek-v3",
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
                        model="deepseek-v3",
                        created=created_ts,
                        part_id=req.part_id,
                        choices=[{
                            "index": choice_index,
                            "finish_reason": None,
                            "message": {"content": elem_chunk, "role": "assistant"}
                        }]
                    ).dict()
                    choice_index += 1

                session_manager.save_session_record(session_id, "", req.part_id)


            # ---------- 后续输出 ----------
            second_intro = (
                "经AI对政策申报要求与贵司画像特征智能分析，您当前还不满足政策申报条件，"
                "可能还存在以下条件需要由您确认：\n"
            )


            # 输出开头语
            async for chunk in typing_output(second_intro):
                yield chunk

                # 第二个缓冲区：收集大模型完整输出
                judge_buffer = ""

                while True:
                    judge_chunk = await judge_queue.get()
                    if judge_chunk is None:
                        break
                    judge_buffer += judge_chunk
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

                # 解析 judge_buffer，判断是否全部满足
                is_satisfied = False
                # 清洗
                normalized = judge_buffer.replace(" ", "").replace("\t", "").replace("\r", "").replace("\n", "")

                if "不满足项：无" in normalized and "不确定项：无" in normalized:
                    is_satisfied = True

                yield PolicyStreamResponse(
                    id=stream_id,
                    model="qwen3_32b",
                    created=created_ts,
                    part_id=req.part_id,
                    choices=[{
                        "index": choice_index,
                        "finish_reason": "stop",
                        "message": {
                            "content": "",
                            "role": "assistant",
                            "is_satisfied": str(is_satisfied).lower()
                        }
                    }]
                ).dict()



        return await chunked_response(event_stream())

    else:
        if not req.session_id or not req.session_id.strip():
            raise HTTPException(status_code=400, detail="必须传入 session_id")

        policy_info = get_policy_info(req.part_id)
        if "error" in policy_info:
            raise HTTPException(status_code=404, detail='未找到该申报专项政策ID。')

        session_id = req.session_id
        choice_index = 0

        async def event_stream() -> AsyncGenerator[Dict[str, Any], None]:
            nonlocal choice_index
            stream_id = str(uuid.uuid4())
            created_ts = int(time.time())

            # 获取最新公司信息
            sessions = session_manager.load_sessions()
            records = sessions.get(session_id, {}).get("records", [])
            if records:
                try:
                    last_record = next(rec for rec in reversed(records) if rec.get("content"))
                    merged_info = json.loads(last_record["content"])
                except Exception:
                    merged_info = req.metadata.dict().copy()
            else:
                merged_info = req.metadata.dict().copy()
            merged_info = baseutils.remove_empty_values(merged_info)

            # 收集历史输入
            history_inputs = [
                rec.get("user_input_text", "").strip()
                for rec in records
                if rec.get("user_input_text") and rec["part_id"] == req.part_id
            ]
            history_text = "\n".join(list(dict.fromkeys(history_inputs)))

            judge_prompt = build_company_judgment_prompt(
                merged_info,
                policy_info,
                extra_user_inputs=history_text,
                check_mode=req.check_mode
            )

            # 流式发送大模型判断结果
            async for chunk in llm_client.stream_model_response(judge_prompt):
                yield PolicyStreamResponse(
                    id=stream_id,
                    model="deepseek-v3",
                    created=created_ts,
                    part_id=req.part_id,
                    choices=[{
                        "index": choice_index,
                        "finish_reason": None,
                        "message": {"content": chunk, "role": "assistant"}
                    }]
                ).dict()
                choice_index += 1

            # 最终 stop
            yield PolicyStreamResponse(
                id=stream_id,
                model="deepseek-v3",
                created=created_ts,
                part_id=req.part_id,
                choices=[{
                    "index": choice_index,
                    "finish_reason": "stop",
                    "message": {"content": "", "role": "assistant"}
                }]
            ).dict()

        return await chunked_response(event_stream())


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app="deepseek_r1:app", workers=1, host="0.0.0.0", port=8001, reload=False)
