"""Temporary virtual displays for signing in on a machine without a desktop."""

import getpass
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode


BACKENDS = ("tigervnc", "kasmvnc")
AUTO_BACKEND = "auto"
FIRST_DISPLAY = 100
LAST_DISPLAY = 199
FIRST_VIEWER_PORT = 6100
FIRST_RFB_PORT = 5999
PORT_SEARCH_LIMIT = 100
LOOPBACK = "127.0.0.1"
DEFAULT_GEOMETRY = (1280, 800)
READY_TIMEOUT_SECONDS = 10.0
READY_POLL_SECONDS = 0.1
STOP_TIMEOUT_SECONDS = 5.0
LOG_TAIL_CHARS = 2_000
X11_SOCKET_DIR = Path("/tmp/.X11-unix")
X11_LOCK_DIR = Path("/tmp")
NOVNC_WEB_DIR = Path("/usr/share/novnc")
KASMVNC_WEB_DIR = Path("/usr/share/kasmvnc/www")
DEFAULT_SSH_PORT = "22"
INSTALL_HINT = (
    "remote login needs a VNC server with a web viewer. On Ubuntu or Debian run "
    "`sudo apt install tigervnc-standalone-server novnc websockify`, or install "
    "KasmVNC from https://github.com/kasmtech/KasmVNC/releases; then retry."
)


class RemoteDisplayError(RuntimeError):
    """A virtual display for remote login could not be provided."""


@dataclass(frozen=True)
class RemoteDisplay:
    backend: str
    display: int
    port: int
    viewer_url: str
    env: dict[str, str]
    geometry: tuple[int, int]

    @property
    def browser_args(self) -> list[str]:
        # The virtual screen has no window manager to maximize the browser,
        # so the window is placed to fill it explicitly.
        width, height = self.geometry
        return ["--window-position=0,0", f"--window-size={width},{height}"]


def has_graphical_display(
    environ: Mapping[str, str] = os.environ,
    system: str | None = None,
) -> bool:
    """Whether a visible browser window can open where this command runs."""
    if (system or platform.system()) != "Linux":
        return True
    return bool(environ.get("DISPLAY") or environ.get("WAYLAND_DISPLAY"))


def select_backend(
    requested: str = AUTO_BACKEND,
    which: Callable[[str], str | None] = shutil.which,
    exists: Callable[[Path], bool] = Path.exists,
) -> str:
    """Pick an installed backend, preferring TigerVNC for its distro packages."""
    available = {
        "tigervnc": bool(
            which("Xtigervnc")
            and which("websockify")
            and exists(NOVNC_WEB_DIR / "vnc.html")
        ),
        # TigerVNC can also register an `Xvnc` alternative, so KasmVNC is
        # recognized by the web client it installs alongside its server.
        "kasmvnc": bool(which("Xvnc") and exists(KASMVNC_WEB_DIR)),
    }
    if requested == AUTO_BACKEND:
        for backend in BACKENDS:
            if available[backend]:
                return backend
        raise RemoteDisplayError(INSTALL_HINT)
    if requested not in available:
        raise ValueError(f"unknown VNC backend: {requested}")
    if not available[requested]:
        raise RemoteDisplayError(f"{requested} is not installed; {INSTALL_HINT}")
    return requested


def free_display(
    socket_dir: Path = X11_SOCKET_DIR,
    lock_dir: Path = X11_LOCK_DIR,
) -> int:
    for display in range(FIRST_DISPLAY, LAST_DISPLAY + 1):
        if not (socket_dir / f"X{display}").exists() and not (
            lock_dir / f".X{display}-lock"
        ).exists():
            return display
    raise RemoteDisplayError(
        f"no free X display between :{FIRST_DISPLAY} and :{LAST_DISPLAY}"
    )


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((LOOPBACK, port))
        except OSError:
            return False
    return True


def free_port(
    first: int,
    is_free: Callable[[int], bool] = port_is_free,
    exclude: tuple[int, ...] = (),
) -> int:
    for port in range(first, first + PORT_SEARCH_LIMIT):
        if port not in exclude and is_free(port):
            return port
    raise RemoteDisplayError(f"no free local port from {first}")


def tigervnc_commands(
    display: int,
    port: int,
    rfb_port: int,
    geometry: tuple[int, int],
) -> list[list[str]]:
    width, height = geometry
    return [
        [
            "Xtigervnc",
            f":{display}",
            "-rfbport",
            str(rfb_port),
            "-interface",
            LOOPBACK,
            "-SecurityTypes",
            "None",
            "-AlwaysShared",
            "-geometry",
            f"{width}x{height}",
            "-depth",
            "24",
            "-nolisten",
            "tcp",
        ],
        [
            "websockify",
            "--web",
            NOVNC_WEB_DIR.as_posix(),
            f"{LOOPBACK}:{port}",
            f"{LOOPBACK}:{rfb_port}",
        ],
    ]


def kasmvnc_commands(
    display: int,
    port: int,
    geometry: tuple[int, int],
) -> list[list[str]]:
    width, height = geometry
    return [
        [
            "Xvnc",
            f":{display}",
            "-websocketPort",
            str(port),
            # The raw VNC port stays closed; only the local web viewer listens.
            "-rfbport",
            "-1",
            "-interface",
            LOOPBACK,
            "-SecurityTypes",
            "None",
            "-DisableBasicAuth",
            "-AlwaysShared",
            "-geometry",
            f"{width}x{height}",
            "-depth",
            "24",
            "-httpd",
            KASMVNC_WEB_DIR.as_posix(),
        ],
    ]


def viewer_url(backend: str, port: int) -> str:
    if backend == "tigervnc":
        query = urlencode({"autoconnect": "1", "resize": "remote"})
        return f"http://{LOOPBACK}:{port}/vnc.html?{query}"
    return f"http://{LOOPBACK}:{port}/"


def display_env(
    display: int,
    environ: Mapping[str, str] = os.environ,
) -> dict[str, str]:
    # Playwright replaces the browser's environment instead of merging it, so
    # the whole environment is passed along with the virtual display. Wayland
    # is dropped so Chromium cannot pick a session the viewer does not show.
    env = {
        name: value
        for name, value in environ.items()
        if name != "WAYLAND_DISPLAY"
    }
    env["DISPLAY"] = f":{display}"
    return env


def port_accepts(port: int) -> bool:
    try:
        with socket.create_connection((LOOPBACK, port), timeout=0.5):
            return True
    except OSError:
        return False


def _log_tail(log) -> str:
    log.flush()
    log.seek(0)
    return log.read()[-LOG_TAIL_CHARS:].strip()


def wait_until_ready(
    processes: list[tuple[str, subprocess.Popen, object]],
    display: int,
    port: int,
    *,
    socket_dir: Path = X11_SOCKET_DIR,
    accepts: Callable[[int], bool] = port_accepts,
    timeout: float = READY_TIMEOUT_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    deadline = clock() + timeout
    while True:
        for name, process, log in processes:
            if process.poll() is not None:
                detail = _log_tail(log)
                raise RemoteDisplayError(
                    f"{name} exited with code {process.returncode}"
                    + (f":\n{detail}" if detail else "")
                )
        if (socket_dir / f"X{display}").exists() and accepts(port):
            return
        if clock() >= deadline:
            raise RemoteDisplayError(
                f"the virtual display did not become ready within {timeout:g} seconds"
            )
        sleep(READY_POLL_SECONDS)


def stop_processes(processes: list[tuple[str, subprocess.Popen, object]]) -> None:
    for _name, process, _log in reversed(processes):
        if process.poll() is not None:
            continue
        process.terminate()
        try:
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@contextmanager
def open_remote_display(
    backend: str = AUTO_BACKEND,
    port: int | None = None,
    geometry: tuple[int, int] = DEFAULT_GEOMETRY,
) -> Iterator[RemoteDisplay]:
    """Run a loopback-only virtual display and web viewer for the block's duration."""
    if platform.system() != "Linux":
        raise RemoteDisplayError("remote login is only available on Linux")
    selected = select_backend(backend)
    display = free_display()
    if port is None:
        port = free_port(FIRST_VIEWER_PORT)
    elif not port_is_free(port):
        raise RemoteDisplayError(f"port {port} is already in use on {LOOPBACK}")

    if selected == "tigervnc":
        rfb_port = free_port(FIRST_RFB_PORT, exclude=(port,))
        commands = tigervnc_commands(display, port, rfb_port, geometry)
    else:
        commands = kasmvnc_commands(display, port, geometry)

    processes: list[tuple[str, subprocess.Popen, object]] = []
    try:
        for command in commands:
            log = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            processes.append((command[0], process, log))
        wait_until_ready(processes, display, port)
        yield RemoteDisplay(
            backend=selected,
            display=display,
            port=port,
            viewer_url=viewer_url(selected, port),
            env=display_env(display),
            geometry=geometry,
        )
    finally:
        stop_processes(processes)
        for _name, _process, log in processes:
            log.close()


def ssh_tunnel_hint(
    port: int,
    environ: Mapping[str, str] = os.environ,
    user: str | None = None,
) -> str:
    """The command a user runs on their own computer to reach the viewer."""
    user = user or getpass.getuser()
    fields = environ.get("SSH_CONNECTION", "").split()
    if len(fields) == 4:
        # SSH_CONNECTION is "client_ip client_port server_ip server_port".
        host, ssh_port = fields[2], fields[3]
    else:
        host, ssh_port = "<this-server>", DEFAULT_SSH_PORT
    port_option = "" if ssh_port == DEFAULT_SSH_PORT else f" -p {ssh_port}"
    return f"ssh -N -L {port}:{LOOPBACK}:{port}{port_option} {user}@{host}"
