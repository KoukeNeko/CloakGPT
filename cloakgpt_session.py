"""Persistent local browser sessions for CloakGPT agents."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any, Callable

from cloakbrowser import launch_persistent_context

from chatgpt_browser import (
    CHATGPT_URL,
    DEFAULT_DATA_DIR,
    DEFAULT_PROFILE_DIR,
    ChatGPTModel,
    DeliveryStateUnknownError,
    ReasoningLevel,
    _validate_conversation_url,
    send_message_on_page,
)


DEFAULT_SESSION_TTL_SECONDS = 2 * 60 * 60
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


def _session_ttl() -> int:
    value = os.environ.get("CLOAKGPT_SESSION_TTL_SECONDS")
    if value is None:
        return DEFAULT_SESSION_TTL_SECONDS
    try:
        ttl = int(value)
    except ValueError as error:
        raise ValueError("CLOAKGPT_SESSION_TTL_SECONDS must be an integer") from error
    if ttl <= 0:
        raise ValueError("CLOAKGPT_SESSION_TTL_SECONDS must be greater than zero")
    return ttl


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
    """Own one browser context and a page for every persistent session."""

    def __init__(
        self,
        *,
        data_dir: Path,
        headless: bool,
        timezone: str,
        ttl_seconds: int,
    ) -> None:
        self.data_dir = data_dir
        self.profile_dir = data_dir / DEFAULT_PROFILE_DIR.name
        self.headless = headless
        self.timezone = timezone
        self.ttl_seconds = ttl_seconds
        self.context = None
        self.pages: dict[str, Any] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.running = True
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
                "version": 1,
                "headless": self.headless,
                "timezone": self.timezone,
                "ttl_seconds": self.ttl_seconds,
                "sessions": self.sessions,
            },
        )

    def _ensure_context(self):
        if self.context is None:
            self.context = launch_persistent_context(
                str(self.profile_dir),
                headless=self.headless,
                locale="ja-JP",
                timezone=self.timezone,
            )
        return self.context

    def _close_context(self) -> None:
        context, self.context = self.context, None
        self.pages.clear()
        if context is not None:
            try:
                context.close()
            except Exception:
                pass

    def _page_for(self, session_id: str):
        record = self.sessions.get(session_id)
        if record is None:
            raise ValueError(f"unknown session: {session_id}")
        page = self.pages.get(session_id)
        if page is None or page.is_closed():
            try:
                page = self._ensure_context().new_page()
            except Exception:
                self._close_context()
                page = self._ensure_context().new_page()
            self.pages[session_id] = page
        return page

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

        self._reap_stale()
        session_id = uuid.uuid4().hex
        page = self._ensure_context().new_page()
        self.pages[session_id] = page
        try:
            status("Opening ChatGPT...")
            page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        except Exception:
            self.pages.pop(session_id, None)
            try:
                page.close()
            except Exception:
                pass
            raise
        now = time.time()
        self.sessions[session_id] = {
            "conversation_url": None,
            "created_at": now,
            "last_used": now,
        }
        self._save_state()
        return self.session_status(session_id)

    def send(self, request: dict[str, Any], status: StatusCallback) -> dict[str, Any]:
        self._reap_stale()
        session_id = str(request["session_id"])
        record = self.sessions.get(session_id)
        if record is None:
            raise ValueError(f"unknown session: {session_id}")

        url = record.get("conversation_url") or CHATGPT_URL
        model = ChatGPTModel(request["model"]) if request.get("model") else None
        reasoning = (
            ReasoningLevel(request["reasoning"]) if request.get("reasoning") else None
        )

        def deliver(page):
            return send_message_on_page(
                page,
                url,
                str(request["question"]),
                model,
                reasoning,
                status,
                reuse_page=True,
            )

        page = self._page_for(session_id)
        try:
            answer, current_url = deliver(page)
        except DeliveryStateUnknownError:
            raise
        except Exception:
            status("Browser page failed before delivery; restarting it once...")
            self.pages.pop(session_id, None)
            try:
                page.close()
            except Exception:
                pass
            page = self._page_for(session_id)
            answer, current_url = deliver(page)

        _validate_conversation_url(current_url)
        record["conversation_url"] = current_url
        record["last_used"] = time.time()
        self._save_state()
        return {"answer": answer, **self.session_status(session_id)}

    def session_status(self, session_id: str) -> dict[str, Any]:
        record = self.sessions.get(session_id)
        if record is None:
            raise ValueError(f"unknown session: {session_id}")
        return {
            "session_id": session_id,
            "headless": self.headless,
            "timezone": self.timezone,
            "ttl_seconds": self.ttl_seconds,
            "conversation_url": record.get("conversation_url"),
            "created_at": record.get("created_at"),
            "last_used": record.get("last_used"),
            "warm": session_id in self.pages,
        }

    def close_session(self, session_id: str) -> dict[str, Any]:
        if session_id not in self.sessions:
            raise ValueError(f"unknown session: {session_id}")
        page = self.pages.pop(session_id, None)
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        del self.sessions[session_id]
        self._save_state()
        if not self.sessions:
            self._close_context()
        return {"session_id": session_id, "closed": True}

    def _reap_stale(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        expired = [
            session_id
            for session_id, record in self.sessions.items()
            if session_id in self.pages
            and float(record.get("last_used", 0)) < cutoff
        ]
        for session_id in expired:
            page = self.pages.pop(session_id, None)
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
        if expired:
            if not self.pages:
                self._close_context()

    def dispatch(self, request: dict[str, Any], status: StatusCallback) -> dict[str, Any]:
        operation = request.get("operation")
        if operation == "ping":
            return {
                "pid": os.getpid(),
                "headless": self.headless,
                "timezone": self.timezone,
                "ttl_seconds": self.ttl_seconds,
                "sessions": len(self.sessions),
            }
        if operation == "open":
            return self.open_session(request, status)
        if operation == "send":
            return self.send(request, status)
        if operation == "session_status":
            return self.session_status(str(request["session_id"]))
        if operation == "close":
            return self.close_session(str(request["session_id"]))
        if operation == "stop":
            self.running = False
            return {"stopped": True}
        raise ValueError(f"unknown broker operation: {operation}")

    def close(self) -> None:
        self._close_context()


def _send_event(connection, event: dict[str, Any]) -> None:
    try:
        connection.send(event)
    except (BrokenPipeError, EOFError, OSError):
        pass


def run_broker(*, data_dir: Path, headless: bool, timezone: str) -> int:
    data_dir.mkdir(parents=True, exist_ok=True)
    family, address = _endpoint(data_dir)
    if family == "AF_UNIX":
        _remove_file(Path(address))
    auth_key = os.urandom(32)
    broker = SessionBroker(
        data_dir=data_dir,
        headless=headless,
        timezone=timezone,
        ttl_seconds=_session_ttl(),
    )
    listener = Listener(address, family=family, authkey=auth_key)
    _write_json(
        _metadata_path(data_dir),
        {
            "version": 1,
            "pid": os.getpid(),
            "family": family,
            "address": address,
            "auth_key": base64.b64encode(auth_key).decode("ascii"),
            "headless": headless,
            "timezone": timezone,
        },
    )

    connections: queue.Queue[Any] = queue.Queue()

    def accept_connections() -> None:
        while broker.running:
            try:
                connections.put(listener.accept())
            except (OSError, EOFError):
                return

    accept_thread = threading.Thread(target=accept_connections, daemon=True)
    accept_thread.start()
    try:
        while broker.running:
            broker._reap_stale()
            try:
                connection = connections.get(timeout=1)
            except queue.Empty:
                continue
            try:
                request = connection.recv()
                if not isinstance(request, dict):
                    raise ValueError("invalid broker request")
                result = broker.dispatch(
                    request,
                    lambda message: _send_event(
                        connection, {"type": "status", "message": message}
                    ),
                )
                _send_event(connection, {"type": "result", "result": result})
            except Exception as error:
                _send_event(connection, {"type": "error", "message": str(error)})
            finally:
                connection.close()
    finally:
        broker.close()
        listener.close()
        _remove_file(_metadata_path(data_dir))
        if family == "AF_UNIX":
            _remove_file(Path(address))
    return 0


def _load_metadata(data_dir: Path) -> dict[str, Any] | None:
    metadata = _read_json(_metadata_path(data_dir))
    if metadata and _pid_is_alive(metadata.get("pid")):
        return metadata
    return None


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
            options: dict[str, Any] = {
                "stdin": subprocess.DEVNULL,
                "stdout": log,
                "stderr": log,
            }
            if getattr(sys, "frozen", False):
                environment = os.environ.copy()
                environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
                options["env"] = environment
            if os.name == "nt":
                options["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                )
            else:
                options["start_new_session"] = True
            process = subprocess.Popen(
                _broker_command(selected_headless, selected_timezone),
                **options,
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
        raise RuntimeError("CloakGPT daemon is not running")
    try:
        auth_key = base64.b64decode(metadata["auth_key"], validate=True)
        connection = Client(
            metadata["address"],
            family=metadata["family"],
            authkey=auth_key,
        )
    except Exception as error:
        raise RuntimeError("could not connect to the CloakGPT daemon") from error

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
                return result
            raise RuntimeError("invalid event from the CloakGPT daemon")
    finally:
        connection.close()
