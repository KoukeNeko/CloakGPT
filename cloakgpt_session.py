"""Persistent local conversation sessions for CloakGPT agents."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any, Callable

from chatgpt_browser import (
    CHATGPT_URL,
    DEFAULT_DATA_DIR,
    DEFAULT_PROFILE_DIR,
    ChatGPTModel,
    DeliveryStateUnknownError,
    ReasoningLevel,
    _validate_conversation_url,
    launch_chatgpt_context_async,
    send_message_on_page,
)


STOP_DRAIN_TIMEOUT_SECONDS = 30
FORCED_STOP_GRACE_SECONDS = 5
SHUTDOWN_TASK_TIMEOUT_SECONDS = 10
METADATA_NAME = "cloakgpt-daemon.json"
STATE_NAME = "cloakgpt-sessions.json"
LOCK_NAME = "cloakgpt-daemon.lock"
LOG_NAME = "cloakgpt-daemon.log"
StatusCallback = Callable[[str], None]


def _metadata_path(data_dir: Path) -> Path:
    return data_dir / METADATA_NAME


def _state_path(data_dir: Path) -> Path:
    return data_dir / STATE_NAME


def _endpoint(data_dir: Path) -> tuple[str, str]:
    digest = hashlib.sha256(str(data_dir.resolve()).encode("utf-8")).hexdigest()[:16]
    if os.name == "nt":
        return "AF_PIPE", rf"\\.\pipe\cloakgpt-{digest}"
    return "AF_UNIX", str(Path(tempfile.gettempdir()) / f"cloakgpt-{digest}.sock")


class DaemonUnavailableError(RuntimeError):
    """The daemon cannot be reached, so there is nothing to talk to."""


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)
    if os.name != "nt":
        path.chmod(0o600)


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _pid_is_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        return False
    return True


class SessionBroker:
    """Persist conversation URLs and run different sessions concurrently."""

    def __init__(
        self,
        *,
        data_dir: Path,
        headless: bool,
        timezone: str,
    ) -> None:
        self.data_dir = data_dir
        self.profile_dir = data_dir / DEFAULT_PROFILE_DIR.name
        self.headless = headless
        self.timezone = timezone
        self.context = None
        self.pages: dict[str, Any] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self._context_lock = asyncio.Lock()
        self._composer_lock = asyncio.Lock()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._inflight_jobs: dict[str, str | None] = {}
        self._jobs_done = asyncio.Event()
        self._jobs_done.set()
        self.running = True
        self.draining = False
        self._load_state()

    def _load_state(self) -> None:
        state = _read_json(_state_path(self.data_dir))
        if not state:
            return
        sessions = state.get("sessions")
        if isinstance(sessions, dict):
            self.sessions = {
                session_id: record
                for session_id, record in sessions.items()
                if isinstance(session_id, str) and isinstance(record, dict)
            }

    def _save_state(self) -> None:
        _write_json(
            _state_path(self.data_dir),
            {
                "version": 2,
                "headless": self.headless,
                "timezone": self.timezone,
                "sessions": self.sessions,
            },
        )

    async def _ensure_context(self):
        async with self._context_lock:
            if self.context is None:
                context = await launch_chatgpt_context_async(
                    self.profile_dir,
                    headless=self.headless,
                    timezone=self.timezone,
                )
                self.context = context
                for page in list(context.pages):
                    try:
                        await page.close()
                    except Exception:
                        pass
            return self.context

    async def _close_context_if_idle(
        self,
        status: StatusCallback | None = None,
        *,
        force: bool = False,
    ) -> None:
        async with self._context_lock:
            if not force and self._inflight_jobs:
                return
            context, self.context = self.context, None
            if context is None:
                return
            if status is not None:
                status("Closing browser...")
            try:
                await context.close()
            except Exception:
                pass

    async def _new_page(self, request_id: str):
        context = await self._ensure_context()
        try:
            page = await context.new_page()
        except Exception:
            async with self._context_lock:
                if self.context is not context or self.pages:
                    raise
                self.context = None
                try:
                    await context.close()
                except Exception:
                    pass
            context = await self._ensure_context()
            page = await context.new_page()
        self.pages[request_id] = page
        return page

    async def _close_page(self, request_id: str) -> None:
        page = self.pages.pop(request_id, None)
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass

    def _begin_job(self, session_id: str | None) -> str:
        if self.draining:
            raise RuntimeError("CloakGPT daemon is stopping")
        request_id = uuid.uuid4().hex
        self._inflight_jobs[request_id] = session_id
        self._jobs_done.clear()
        return request_id

    async def _finish_job(self, request_id: str, status: StatusCallback) -> None:
        await self._close_page(request_id)
        self._inflight_jobs.pop(request_id, None)
        if not self._inflight_jobs:
            await self._close_context_if_idle(status)
            if not self._inflight_jobs:
                self._jobs_done.set()

    async def _drain_jobs(self, timeout: float) -> int:
        """Wait for running requests and report how many are still running."""
        try:
            await asyncio.wait_for(self._jobs_done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return len(self._inflight_jobs)
        return 0

    async def stop(self, *, force: bool) -> dict[str, Any]:
        self.draining = True
        remaining = await self._drain_jobs(STOP_DRAIN_TIMEOUT_SECONDS)
        if remaining and not force:
            self.draining = False
            raise RuntimeError(
                f"{remaining} request(s) are still running; "
                "retry once they finish or stop with --force"
            )
        if remaining:
            # Closing the context fails every pending page call, so each stuck
            # request unwinds through its own cleanup and releases its page.
            await self._close_context_if_idle(force=True)
            await self._drain_jobs(FORCED_STOP_GRACE_SECONDS)
        self.running = False
        await self._close_context_if_idle(force=True)
        return {"stopped": True, "abandoned_requests": remaining}

    def open_session(self, request: dict[str, Any], status: StatusCallback) -> dict[str, Any]:
        requested_headless = bool(request["headless"])
        requested_timezone = str(request["timezone"])
        if requested_headless != self.headless:
            mode = "headless" if self.headless else "headed"
            raise ValueError(
                f"daemon is already running in {mode} mode; stop it before changing mode"
            )
        if requested_timezone != self.timezone:
            raise ValueError(
                f"daemon timezone is {self.timezone}; stop it before changing timezone"
            )

        session_id = uuid.uuid4().hex
        status("Creating persistent conversation ID...")
        now = time.time()
        self.sessions[session_id] = {
            "conversation_url": None,
            "created_at": now,
            "last_used": now,
        }
        self._save_state()
        return self.session_status(session_id)

    async def send(
        self, request: dict[str, Any], status: StatusCallback
    ) -> dict[str, Any]:
        session_id = str(request["session_id"])
        if session_id not in self.sessions:
            raise ValueError(f"unknown session: {session_id}")
        request_id = self._begin_job(session_id)
        session_lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        try:
            if session_lock.locked():
                status("Waiting for an earlier message in this session...")
            async with session_lock:
                record = self.sessions.get(session_id)
                if record is None:
                    raise ValueError(f"unknown session: {session_id}")
                url = record.get("conversation_url") or CHATGPT_URL
                model = (
                    ChatGPTModel(request["model"]) if request.get("model") else None
                )
                reasoning = (
                    ReasoningLevel(request["reasoning"])
                    if request.get("reasoning")
                    else None
                )

                async def deliver(page):
                    return await send_message_on_page(
                        page,
                        url,
                        str(request["question"]),
                        model,
                        reasoning,
                        status,
                        reuse_page=True,
                        composer_lock=self._composer_lock,
                    )

                page = await self._new_page(request_id)
                try:
                    answer, current_url = await deliver(page)
                except DeliveryStateUnknownError:
                    raise
                except Exception:
                    status("Browser page failed before delivery; restarting it once...")
                    await self._close_page(request_id)
                    page = await self._new_page(request_id)
                    answer, current_url = await deliver(page)

                _validate_conversation_url(current_url)
                record["conversation_url"] = current_url
                record["last_used"] = time.time()
                self._save_state()
        finally:
            await self._finish_job(request_id, status)
        return {"answer": answer, **self.session_status(session_id)}

    async def send_once(
        self, request: dict[str, Any], status: StatusCallback
    ) -> dict[str, Any]:
        """Send a new conversation through the daemon without saving a session."""
        request_id = self._begin_job(None)
        status("Opening a temporary new conversation...")
        model = ChatGPTModel(request["model"]) if request.get("model") else None
        reasoning = (
            ReasoningLevel(request["reasoning"]) if request.get("reasoning") else None
        )
        try:
            page = await self._new_page(request_id)
            answer, _ = await send_message_on_page(
                page,
                CHATGPT_URL,
                str(request["question"]),
                model,
                reasoning,
                status,
                reuse_page=True,
                composer_lock=self._composer_lock,
            )
            return {"answer": answer}
        finally:
            await self._finish_job(request_id, status)

    def session_status(self, session_id: str) -> dict[str, Any]:
        record = self.sessions.get(session_id)
        if record is None:
            raise ValueError(f"unknown session: {session_id}")
        jobs = [
            request_id
            for request_id, job_session_id in self._inflight_jobs.items()
            if job_session_id == session_id
        ]
        running = sum(request_id in self.pages for request_id in jobs)
        return {
            "session_id": session_id,
            "headless": self.headless,
            "timezone": self.timezone,
            "conversation_url": record.get("conversation_url"),
            "created_at": record.get("created_at"),
            "last_used": record.get("last_used"),
            "warm": running > 0,
            "running_requests": running,
            "queued_requests": len(jobs) - running,
        }

    def close_session(self, session_id: str) -> dict[str, Any]:
        if session_id not in self.sessions:
            raise ValueError(f"unknown session: {session_id}")
        if session_id in self._inflight_jobs.values():
            raise RuntimeError(f"session is busy: {session_id}")
        del self.sessions[session_id]
        self._session_locks.pop(session_id, None)
        self._save_state()
        return {"session_id": session_id, "closed": True}

    async def dispatch(
        self, request: dict[str, Any], status: StatusCallback
    ) -> dict[str, Any]:
        operation = request.get("operation")
        if operation == "ping":
            return {
                "pid": os.getpid(),
                "headless": self.headless,
                "timezone": self.timezone,
                "sessions": len(self.sessions),
                "browser": "running" if self.context is not None else "stopped",
                "active_requests": len(self.pages),
                "queued_requests": len(self._inflight_jobs) - len(self.pages),
                "open_pages": len(self.pages),
            }
        if operation == "stop":
            return await self.stop(force=bool(request.get("force", False)))
        if self.draining:
            raise RuntimeError("CloakGPT daemon is stopping")
        if operation == "open":
            return self.open_session(request, status)
        if operation == "send":
            return await self.send(request, status)
        if operation == "send_once":
            return await self.send_once(request, status)
        if operation == "session_status":
            return self.session_status(str(request["session_id"]))
        if operation == "close":
            return self.close_session(str(request["session_id"]))
        raise ValueError(f"unknown broker operation: {operation}")

    async def close(self) -> None:
        self.draining = True
        await self._drain_jobs(STOP_DRAIN_TIMEOUT_SECONDS)
        await self._close_context_if_idle(force=True)


def _send_event(connection, event: dict[str, Any]) -> None:
    try:
        connection.send(event)
    except (BrokenPipeError, EOFError, OSError):
        pass


async def _finish_connection_tasks(tasks: set[asyncio.Task[Any]]) -> None:
    """Let handlers finish, then cancel whatever refuses to unwind in time."""
    _done, pending = await asyncio.wait(tasks, timeout=SHUTDOWN_TASK_TIMEOUT_SECONDS)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _run_broker_async(*, data_dir: Path, headless: bool, timezone: str) -> int:
    data_dir.mkdir(parents=True, exist_ok=True)
    family, address = _endpoint(data_dir)
    if family == "AF_UNIX":
        _remove_file(Path(address))
    auth_key = os.urandom(32)
    broker = SessionBroker(
        data_dir=data_dir,
        headless=headless,
        timezone=timezone,
    )
    listener = Listener(address, family=family, authkey=auth_key)
    _write_json(
        _metadata_path(data_dir),
        {
            "version": 2,
            "pid": os.getpid(),
            "family": family,
            "address": address,
            "auth_key": base64.b64encode(auth_key).decode("ascii"),
            "headless": headless,
            "timezone": timezone,
            "capabilities": ["parallel_sessions"],
        },
    )

    connections: asyncio.Queue[Any] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def accept_connections() -> None:
        while broker.running:
            try:
                connection = listener.accept()
                loop.call_soon_threadsafe(connections.put_nowait, connection)
            except (OSError, EOFError):
                return

    accept_thread = threading.Thread(target=accept_connections, daemon=True)
    accept_thread.start()

    async def write_events(connection, events: asyncio.Queue[Any]) -> None:
        while True:
            event = await events.get()
            if event is None:
                return
            await asyncio.to_thread(_send_event, connection, event)

    async def handle_connection(connection) -> None:
        events: asyncio.Queue[Any] = asyncio.Queue()
        writer = asyncio.create_task(write_events(connection, events))
        try:
            request = await asyncio.to_thread(connection.recv)
            if not isinstance(request, dict):
                raise ValueError("invalid broker request")
            result = await broker.dispatch(
                request,
                lambda message: events.put_nowait(
                    {"type": "status", "message": message}
                ),
            )
            events.put_nowait({"type": "result", "result": result})
        except Exception as error:
            events.put_nowait({"type": "error", "message": str(error)})
        finally:
            events.put_nowait(None)
            await writer
            connection.close()

    tasks: set[asyncio.Task[Any]] = set()
    try:
        while broker.running:
            try:
                connection = await asyncio.wait_for(connections.get(), timeout=1)
            except TimeoutError:
                continue
            task = asyncio.create_task(handle_connection(connection))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    finally:
        listener.close()
        while not connections.empty():
            connection = connections.get_nowait()
            task = asyncio.create_task(handle_connection(connection))
            tasks.add(task)
        if tasks:
            await _finish_connection_tasks(tasks)
        await broker.close()
        _remove_file(_metadata_path(data_dir))
        if family == "AF_UNIX":
            _remove_file(Path(address))
    return 0


def run_broker(*, data_dir: Path, headless: bool, timezone: str) -> int:
    return asyncio.run(
        _run_broker_async(data_dir=data_dir, headless=headless, timezone=timezone)
    )


def _load_metadata(data_dir: Path) -> dict[str, Any] | None:
    metadata = _read_json(_metadata_path(data_dir))
    if metadata and _pid_is_alive(metadata.get("pid")):
        return metadata
    return None


def _wait_for_broker_exit(pid: object, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while _pid_is_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _pid_is_alive(pid):
        raise RuntimeError("CloakGPT daemon did not stop")


def _broker_command(headless: bool, timezone: str) -> list[str]:
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).with_name("cloakgpt.py")))
    command.extend(["_daemon", "--timezone", timezone])
    if not headless:
        command.append("--headed")
    return command


def _saved_broker_options(data_dir: Path) -> tuple[bool, str]:
    state = _read_json(_state_path(data_dir)) or {}
    return bool(state.get("headless", True)), str(state.get("timezone", "Asia/Taipei"))


def _broker_process_options(log) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    if getattr(sys, "frozen", False):
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"

    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log,
        "stderr": log,
        "env": environment,
    }
    if os.name == "nt":
        options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    else:
        options["start_new_session"] = True
    return options


def ensure_broker(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    headless: bool | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    metadata = _load_metadata(data_dir)
    if metadata:
        return metadata

    saved_headless, saved_timezone = _saved_broker_options(data_dir)
    selected_headless = saved_headless if headless is None else headless
    selected_timezone = saved_timezone if timezone is None else timezone
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / LOCK_NAME
    deadline = time.monotonic() + 20
    lock_descriptor: int | None = None
    while lock_descriptor is None:
        try:
            lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            metadata = _load_metadata(data_dir)
            if metadata:
                return metadata
            try:
                if time.time() - lock_path.stat().st_mtime > 30:
                    _remove_file(lock_path)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise RuntimeError("timed out waiting for the CloakGPT daemon startup lock")
            time.sleep(0.1)

    try:
        metadata = _load_metadata(data_dir)
        if metadata:
            return metadata
        _remove_file(_metadata_path(data_dir))
        log_path = data_dir / LOG_NAME
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                _broker_command(selected_headless, selected_timezone),
                **_broker_process_options(log),
            )

        while time.monotonic() < deadline:
            metadata = _load_metadata(data_dir)
            if metadata:
                return metadata
            if process.poll() is not None:
                raise RuntimeError(
                    f"CloakGPT daemon exited during startup; see {log_path}"
                )
            time.sleep(0.1)
        raise RuntimeError(f"CloakGPT daemon did not start; see {log_path}")
    finally:
        os.close(lock_descriptor)
        _remove_file(lock_path)


def request_broker(
    request: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    status_callback: StatusCallback | None = None,
    auto_start: bool = True,
    headless: bool | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    metadata = (
        ensure_broker(data_dir=data_dir, headless=headless, timezone=timezone)
        if auto_start
        else _load_metadata(data_dir)
    )
    if metadata is None:
        raise DaemonUnavailableError("CloakGPT daemon is not running")
    try:
        auth_key = base64.b64decode(metadata["auth_key"], validate=True)
        connection = Client(
            metadata["address"],
            family=metadata["family"],
            authkey=auth_key,
        )
    except Exception as error:
        raise DaemonUnavailableError(
            f"could not connect to the CloakGPT daemon (pid {metadata.get('pid')}); "
            "it is running but unreachable, so end that process and retry"
        ) from error

    try:
        connection.send(request)
        while True:
            event = connection.recv()
            if event.get("type") == "status":
                if status_callback is not None:
                    status_callback(str(event["message"]))
                continue
            if event.get("type") == "error":
                raise RuntimeError(str(event["message"]))
            if event.get("type") == "result":
                result = event.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("invalid response from the CloakGPT daemon")
                if request.get("operation") == "stop":
                    connection.close()
                    _wait_for_broker_exit(metadata.get("pid"))
                return result
            raise RuntimeError("invalid event from the CloakGPT daemon")
    finally:
        connection.close()
