"""OpenAI-compatible HTTP API server for CloakGPT.

Allows tools like LangChain, Open WebUI, Cline, and Cursor to interact
with CloakGPT via standard OpenAI chat completion and models endpoints.
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
import time
from collections.abc import Callable, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from chatgpt_browser import ChatGPTModel, ReasoningLevel
from cloakgpt_session import request_broker


DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 8000
DEFAULT_CHATGPT_MODEL = ChatGPTModel.GPT_5_5.value
SSE_DATA_PREFIX = "data: "
SSE_TERMINAL_MARKER = b"data: [DONE]\n\n"
JSON_CONTENT_TYPE = "application/json; charset=utf-8"
SSE_CONTENT_TYPE = "text/event-stream; charset=utf-8"
BEARER_AUTH_PREFIX = "Bearer "

# Models advertised in /v1/models
DEFAULT_SERVER_MODELS = [
    ChatGPTModel.GPT_5_6_SOL.value,
    ChatGPTModel.GPT_5_5.value,
]

BrokerRequester = Callable[..., dict[str, Any]]


class MessageNormalizer:
    """Normalizes OpenAI chat messages (strings or multipart parts) into a single prompt."""

    @staticmethod
    def _extract_part_text(part: dict[str, Any]) -> str:
        part_type = part.get("type", "")
        if part_type == "text":
            return str(part.get("text", ""))
        if part_type == "image_url":
            image_info = part.get("image_url", {})
            url = image_info.get("url", "")
            detail = image_info.get("detail", "auto")
            if url.startswith("data:image/"):
                mime = url.split(";")[0].replace("data:", "")
                return f"\n[附件圖片: base64 ({mime}), detail={detail}]\n"
            return f"\n[附件圖片連結: {url} (detail={detail})]\n"
        if part_type == "file":
            file_info = part.get("file", {})
            filename = file_info.get("filename", "unknown")
            file_id = file_info.get("file_id")
            if file_id:
                return f"\n[附件檔案 ID: {file_id} ({filename})]\n"
            return f"\n[附件檔案: {filename}]\n"
        return ""

    @classmethod
    def _content_to_text(cls, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            extracted_parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    part_text = cls._extract_part_text(part)
                    if part_text:
                        extracted_parts.append(part_text)
                elif isinstance(part, str):
                    extracted_parts.append(part)
            return "".join(extracted_parts)
        return str(content)

    @classmethod
    def normalize(cls, messages: Sequence[dict[str, Any]]) -> str:
        """Combine all conversation turns into a cohesive prompt for ChatGPT."""
        if not messages:
            return ""

        # For a single message, return its content directly to avoid unnecessary wrapping
        if len(messages) == 1:
            return cls._content_to_text(messages[0].get("content", "")).strip()

        formatted_turns: list[str] = []
        for message in messages:
            role = str(message.get("role", "user")).lower()
            text = cls._content_to_text(message.get("content", "")).strip()
            if not text:
                continue

            if role in ("system", "developer"):
                formatted_turns.append(f"[系統指令]\n{text}")
            elif role == "assistant":
                formatted_turns.append(f"[助手回答]\n{text}")
            else:
                formatted_turns.append(f"[使用者]\n{text}")

        return "\n\n".join(formatted_turns)

    @classmethod
    def extract_incremental(
        cls,
        current_messages: Sequence[dict[str, Any]],
        previous_messages: Sequence[dict[str, Any]] | None = None,
    ) -> str:
        """Extract only the new/incremental messages in a continuous conversation."""
        if not previous_messages or len(current_messages) <= len(previous_messages):
            return cls.normalize(current_messages)

        new_turns = current_messages[len(previous_messages):]
        user_turns = [
            m for m in new_turns if str(m.get("role", "")).lower() != "assistant"
        ]
        if not user_turns:
            user_turns = [current_messages[-1]]

        return cls.normalize(user_turns)


class ConversationSessionManager:
    """Tracks active session and determines conversation continuity vs task rotation."""

    def __init__(self, pinned_session_id: str | None = None):
        self.pinned_session_id = pinned_session_id
        self.active_session_id = pinned_session_id or f"serve-{secrets.token_hex(6)}"
        self.last_messages: list[dict[str, Any]] | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _extract_first_user_content(messages: Sequence[dict[str, Any]]) -> str:
        for msg in messages:
            if str(msg.get("role", "")).lower() == "user":
                return str(msg.get("content", ""))
        return ""

    def _is_continuation(self, messages: Sequence[dict[str, Any]]) -> bool:
        if not self.last_messages:
            return False
        if len(messages) <= len(self.last_messages):
            return False

        prev_first_user = self._extract_first_user_content(self.last_messages)
        curr_first_user = self._extract_first_user_content(messages)
        return bool(prev_first_user and prev_first_user == curr_first_user)

    def process_messages(
        self, messages: Sequence[dict[str, Any]]
    ) -> tuple[bool, str, str]:
        """Returns (is_continuation, prompt_text, session_id)."""
        with self._lock:
            if self._is_continuation(messages):
                prompt = MessageNormalizer.extract_incremental(
                    messages, self.last_messages
                )
                self.last_messages = list(messages)
                return True, prompt, self.active_session_id

            # New task detected or first turn
            if not self.pinned_session_id and self.last_messages is not None:
                # Rotate to a fresh session for the new task
                self.active_session_id = f"serve-{secrets.token_hex(6)}"

            prompt = MessageNormalizer.normalize(messages)
            self.last_messages = list(messages)
            return False, prompt, self.active_session_id


class OpenAIFormatter:
    """Formats completions, streaming chunks, and error responses according to OpenAI specs."""

    @staticmethod
    def generate_id() -> str:
        return f"chatcmpl-{secrets.token_hex(12)}"

    @classmethod
    def completion(
        cls,
        *,
        model: str,
        content: str,
        reasoning_content: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        created_time: int | None = None,
    ) -> dict[str, Any]:
        message_dict: dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }
        if reasoning_content is not None:
            message_dict["reasoning_content"] = reasoning_content

        return {
            "id": cls.generate_id(),
            "object": "chat.completion",
            "created": created_time or int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message_dict,
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    @staticmethod
    def chunk(
        *,
        completion_id: str,
        model: str,
        delta_content: str | None = None,
        reasoning_content: str | None = None,
        role: str | None = None,
        created_time: int | None = None,
        finish_reason: str | None = None,
    ) -> dict[str, Any]:
        delta: dict[str, Any] = {}
        if role is not None:
            delta["role"] = role
        if delta_content is not None:
            delta["content"] = delta_content
        if reasoning_content is not None:
            delta["reasoning_content"] = reasoning_content

        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_time or int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        }

    @staticmethod
    def model_list(models: Sequence[str]) -> dict[str, Any]:
        now = int(time.time())
        return {
            "object": "list",
            "data": [
                {
                    "id": model_id,
                    "object": "model",
                    "created": now,
                    "owned_by": "cloakgpt",
                }
                for model_id in models
            ],
        }

    @staticmethod
    def model_detail(model_id: str) -> dict[str, Any]:
        return {
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "cloakgpt",
        }

    @staticmethod
    def error(
        message: str,
        error_type: str = "invalid_request_error",
        status_code: int = HTTPStatus.BAD_REQUEST,
        code: str | None = None,
    ) -> tuple[dict[str, Any], int]:
        payload: dict[str, Any] = {
            "error": {
                "message": message,
                "type": error_type,
                "code": code,
            }
        }
        return payload, status_code

REASONING_EFFORT_MAP: dict[str, ReasoningLevel] = {
    "low": ReasoningLevel.FAST,
    "fast": ReasoningLevel.FAST,
    "medium": ReasoningLevel.MEDIUM,
    "high": ReasoningLevel.HIGH,
}


class ReasoningResolver:
    """Helper to resolve reasoning level from request body or server default."""

    @staticmethod
    def resolve(
        body: dict[str, Any],
        default_reasoning: ReasoningLevel | None = None,
    ) -> ReasoningLevel | None:
        raw = body.get("reasoning_effort") or body.get("reasoning")
        if raw is None:
            return default_reasoning
        normalized = str(raw).strip().lower()
        return REASONING_EFFORT_MAP.get(normalized, default_reasoning)


class OpenAIRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request handler implementing OpenAI-compatible endpoints."""

    server: OpenAIServer

    def _send_json_response(self, data: dict[str, Any], status_code: int = HTTPStatus.OK) -> None:
        response_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(response_bytes)

    def _send_error_response(
        self,
        message: str,
        error_type: str = "invalid_request_error",
        status_code: int = HTTPStatus.BAD_REQUEST,
        code: str | None = None,
    ) -> None:
        payload, code_val = OpenAIFormatter.error(
            message=message,
            error_type=error_type,
            status_code=status_code,
            code=code,
        )
        self._send_json_response(payload, status_code=code_val)

    def _check_auth(self) -> bool:
        expected_key = self.server.api_key
        if not expected_key:
            return True

        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith(BEARER_AUTH_PREFIX):
            self._send_error_response(
                "缺少或無效的 Authorization 標頭，格式應為 Bearer <API_KEY>",
                error_type="authentication_error",
                status_code=HTTPStatus.UNAUTHORIZED,
                code="invalid_api_key",
            )
            return False

        token = auth_header[len(BEARER_AUTH_PREFIX) :].strip()
        if not secrets.compare_digest(token, expected_key):
            self._send_error_response(
                "API Key 不符合",
                error_type="authentication_error",
                status_code=HTTPStatus.UNAUTHORIZED,
                code="invalid_api_key",
            )
            return False

        return True

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_HEAD(self) -> None:
        if not self._check_auth():
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._check_auth():
            return

        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/")

        if path == "/v1/models":
            self._handle_get_models()
            return

        if path.startswith("/v1/models/"):
            model_id = path[len("/v1/models/") :]
            self._handle_get_model_detail(model_id)
            return

        self._send_error_response(
            f"找不到請求的路徑: {self.path}",
            error_type="invalid_request_error",
            status_code=HTTPStatus.NOT_FOUND,
        )

    def do_POST(self) -> None:
        if not self._check_auth():
            return

        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/")

        if path == "/v1/chat/completions":
            self._handle_chat_completions()
            return

        self._send_error_response(
            f"找不到請求的路徑: {self.path}",
            error_type="invalid_request_error",
            status_code=HTTPStatus.NOT_FOUND,
        )

    def _handle_get_models(self) -> None:
        data = OpenAIFormatter.model_list(DEFAULT_SERVER_MODELS)
        self._send_json_response(data)

    def _handle_get_model_detail(self, model_id: str) -> None:
        if model_id not in DEFAULT_SERVER_MODELS:
            self._send_error_response(
                f"找不到模型: {model_id}",
                error_type="invalid_request_error",
                status_code=HTTPStatus.NOT_FOUND,
                code="model_not_found",
            )
            return
        data = OpenAIFormatter.model_detail(model_id)
        self._send_json_response(data)

    def _read_json_body(self) -> dict[str, Any] | None:
        content_length_str = self.headers.get("Content-Length")
        if not content_length_str:
            self._send_error_response("缺少 Content-Length 標頭")
            return None

        try:
            content_length = int(content_length_str)
            raw_body = self.rfile.read(content_length)
            return json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            self._send_error_response(f"無法解析 JSON 請求主體: {error}")
            return None

    def _resolve_model_name(self, requested_model: str | None) -> str:
        if not requested_model:
            return self.server.default_model or DEFAULT_CHATGPT_MODEL
        for model in ChatGPTModel:
            if requested_model == model.value:
                return model.value
        return self.server.default_model or DEFAULT_CHATGPT_MODEL

    def _handle_chat_completions(self) -> None:
        body = self._read_json_body()
        if body is None:
            return

        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            self._send_error_response("請求中必須包含非空的 messages 陣列")
            return

        if getattr(self.server, "stateless", False):
            prompt = MessageNormalizer.normalize(messages)
            session_id = None
            broker_operation = "send_once"
        else:
            session_mgr: ConversationSessionManager = getattr(
                self.server, "session_manager", None
            ) or ConversationSessionManager()
            is_continuation, prompt, session_id = session_mgr.process_messages(messages)
            broker_operation = "send"
            if self.server.verbose:
                print(
                    f"[server] Session: id={session_id}, continuation={is_continuation}",
                    file=sys.stderr,
                    flush=True,
                )

        if not prompt.strip():
            self._send_error_response("提取出的訊息內容不得為空")
            return

        requested_model = body.get("model")
        resolved_model = self._resolve_model_name(requested_model)
        is_stream = bool(body.get("stream", False))

        # Determine target model for broker (None keeps ChatGPT's active setting)
        target_model: str | None = None
        if self.server.default_model:
            target_model = self.server.default_model
        elif requested_model in [m.value for m in ChatGPTModel]:
            target_model = requested_model

        # Resolve reasoning level dynamically from request body, falling back to server default
        resolved_reasoning = ReasoningResolver.resolve(body, self.server.reasoning)

        # Prepare request payload for CloakGPT broker
        broker_request: dict[str, Any] = {
            "operation": broker_operation,
            "question": prompt,
            "model": target_model,
            "reasoning": str(resolved_reasoning) if resolved_reasoning else None,
        }
        if session_id:
            broker_request["session_id"] = session_id

        if is_stream:
            self._stream_chat_completion(resolved_model, broker_request)
        else:
            try:
                def on_status(message: str) -> None:
                    if self.server.verbose:
                        print(f"[server:status] {message}", file=sys.stderr, flush=True)

                broker_result = self.server.broker_requester(
                    broker_request,
                    headless=self.server.headless,
                    timezone=self.server.timezone,
                    status_callback=on_status,
                )
                answer = str(broker_result.get("answer", ""))
            except Exception as error:
                self._send_error_response(
                    f"向 ChatGPT 瀏覽器派送對話失敗: {error}",
                    error_type="api_error",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json_chat_completion(resolved_model, answer)

    def _send_json_chat_completion(self, model: str, answer: str) -> None:
        response_data = OpenAIFormatter.completion(
            model=model,
            content=answer,
            prompt_tokens=len(answer) // 2,
            completion_tokens=len(answer),
        )
        self._send_json_response(response_data)

    def _stream_chat_completion(
        self, model: str, broker_request: dict[str, Any]
    ) -> None:
        completion_id = OpenAIFormatter.generate_id()
        created_time = int(time.time())

        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", SSE_CONTENT_TYPE)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

        write_lock = threading.Lock()
        is_client_disconnected = False

        def send_chunk(chunk_dict: dict[str, Any]) -> bool:
            nonlocal is_client_disconnected
            if is_client_disconnected:
                return False
            chunk_line = f"{SSE_DATA_PREFIX}{json.dumps(chunk_dict, ensure_ascii=False)}\n\n"
            try:
                with write_lock:
                    self.wfile.write(chunk_line.encode("utf-8"))
                    self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError):
                is_client_disconnected = True
                return False

        def send_keepalive() -> bool:
            nonlocal is_client_disconnected
            if is_client_disconnected:
                return False
            try:
                with write_lock:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError):
                is_client_disconnected = True
                return False

        # Emit initial chunk establishing role immediately (solves 10s connect timeout)
        initial_chunk = OpenAIFormatter.chunk(
            completion_id=completion_id,
            model=model,
            role="assistant",
            delta_content="",
            created_time=created_time,
        )
        if not send_chunk(initial_chunk):
            return

        result_holder: dict[str, Any] = {}
        error_holder: list[Exception] = []
        done_event = threading.Event()

        def on_status(status_message: str) -> None:
            if not status_message:
                return
            if self.server.verbose:
                print(f"[server:status] {status_message}", file=sys.stderr, flush=True)
            clean_status = status_message.strip()
            if not clean_status:
                return
            reasoning_chunk = OpenAIFormatter.chunk(
                completion_id=completion_id,
                model=model,
                reasoning_content=f"• {clean_status}\n",
                created_time=created_time,
            )
            send_chunk(reasoning_chunk)

        def worker() -> None:
            try:
                res = self.server.broker_requester(
                    broker_request,
                    headless=self.server.headless,
                    timezone=self.server.timezone,
                    status_callback=on_status,
                )
                result_holder["result"] = res
            except Exception as exc:
                error_holder.append(exc)
            finally:
                done_event.set()

        worker_thread = threading.Thread(
            target=worker, name="BrokerWorkerThread", daemon=True
        )
        worker_thread.start()

        # Keep connection warm while ChatGPT is generating in browser
        while not done_event.wait(timeout=2.0):
            if not send_keepalive():
                return

        if is_client_disconnected:
            return

        if error_holder:
            error = error_holder[0]
            error_payload = {
                "error": {
                    "message": f"向 ChatGPT 瀏覽器派送對話失敗: {error}",
                    "type": "api_error",
                    "code": None,
                }
            }
            send_chunk(error_payload)
            try:
                with write_lock:
                    self.wfile.write(SSE_TERMINAL_MARKER)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        answer = str(result_holder.get("result", {}).get("answer", ""))

        # Emit content in progressive chunks
        chunk_size = 32
        try:
            for offset in range(0, len(answer), chunk_size):
                if is_client_disconnected:
                    return
                slice_text = answer[offset : offset + chunk_size]
                content_chunk = OpenAIFormatter.chunk(
                    completion_id=completion_id,
                    model=model,
                    delta_content=slice_text,
                    created_time=created_time,
                )
                if not send_chunk(content_chunk):
                    return
                time.sleep(0.01)

            # Emit final stop chunk
            final_chunk = OpenAIFormatter.chunk(
                completion_id=completion_id,
                model=model,
                created_time=created_time,
                finish_reason="stop",
            )
            if not send_chunk(final_chunk):
                return

            # Emit standard SSE [DONE] signal
            with write_lock:
                self.wfile.write(SSE_TERMINAL_MARKER)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: Any) -> None:
        # Avoid polluting stderr during automated requests
        if self.server.verbose:
            super().log_message(format, *args)


class OpenAIServer:
    """Threaded HTTP Server for OpenAI-compatible CloakGPT endpoints."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_SERVER_HOST,
        port: int = DEFAULT_SERVER_PORT,
        api_key: str | None = None,
        session_id: str | None = None,
        stateless: bool = False,
        default_model: str | None = None,
        reasoning: ReasoningLevel | None = None,
        headless: bool = True,
        timezone: str = "Asia/Taipei",
        verbose: bool = False,
        broker_requester: BrokerRequester | None = None,
    ) -> None:
        self.host = host
        self.requested_port = port
        self.api_key = api_key
        self.session_id = session_id
        self.stateless = stateless
        self.default_model = default_model
        self.reasoning = reasoning
        self.headless = headless
        self.timezone = timezone
        self.verbose = verbose
        self.broker_requester = broker_requester or request_broker
        self.session_manager = ConversationSessionManager(pinned_session_id=session_id)

        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = port

    def start(self) -> None:
        """Start the HTTP server on a background worker thread."""
        self._httpd = ThreadingHTTPServer(
            (self.host, self.requested_port),
            OpenAIRequestHandler,
        )
        # Inherit configurations onto the request handler
        self._httpd.api_key = self.api_key  # type: ignore[attr-defined]
        self._httpd.session_id = self.session_id  # type: ignore[attr-defined]
        self._httpd.stateless = self.stateless  # type: ignore[attr-defined]
        self._httpd.session_manager = self.session_manager  # type: ignore[attr-defined]
        self._httpd.default_model = self.default_model  # type: ignore[attr-defined]
        self._httpd.reasoning = self.reasoning  # type: ignore[attr-defined]
        self._httpd.headless = self.headless  # type: ignore[attr-defined]
        self._httpd.timezone = self.timezone  # type: ignore[attr-defined]
        self._httpd.verbose = self.verbose  # type: ignore[attr-defined]
        self._httpd.broker_requester = self.broker_requester  # type: ignore[attr-defined]

        self.port = self._httpd.server_address[1]

        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="OpenAIServerThread",
            daemon=True,
        )
        self._thread.start()

    def shutdown(self) -> None:
        """Gracefully terminate the HTTP server and release sockets."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
