"""Command-line interface for CloakGPT."""

import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from collections.abc import Sequence

from cloakbrowser.__main__ import main as cloakbrowser_main
from playwright._impl._driver import compute_driver_executable
from playwright.sync_api import Error as PlaywrightError

from chatgpt_browser import (
    CHATGPT_URL,
    ChatGPTModel,
    DEFAULT_PROFILE_DIR,
    REASONING_TRIGGER_SELECTOR,
    ReasoningLevel,
    SIGNED_OUT_CONTROL_TIMEOUT_MS,
    launch_chatgpt_context,
    page_is_signed_in,
)
from cloakgpt_display import (
    AUTO_BACKEND,
    BACKENDS,
    has_graphical_display,
    open_remote_display,
    ssh_tunnel_hint,
)
from cloakgpt_session import (
    DaemonNotRunningError,
    request_broker,
    run_broker,
)
from cloakgpt_skill import (
    bundled_skill_text,
    install_command_text,
    outdated_skill_paths,
    refresh_skill,
)
from cloakgpt_update import (
    consume_windows_update_result,
    update_cloakgpt,
    version_text,
)
from cloakgpt_server import OpenAIServer


def _configure_windows_utf8_stdio() -> None:
    """Use UTF-8 for the Windows console and Python standard streams."""
    if os.name != "nt":
        return

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetConsoleCP(65001)
        kernel32.SetConsoleOutputCP(65001)
    except (AttributeError, OSError):
        pass

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="strict")
            except (OSError, ValueError):
                pass


def _login_page(context):
    pages = list(context.pages)
    page = next(
        (candidate for candidate in pages if candidate.url == "about:blank"),
        pages[0] if pages else None,
    )
    if page is None:
        return context.new_page()

    for candidate in pages:
        if candidate is not page and candidate.url == "about:blank":
            candidate.close()
    return page


LOGIN_POLL_MS = 1_000
LOGIN_SAVE_DELAY_MS = 3_000


def _page_is_signed_in(page) -> bool:
    try:
        return page_is_signed_in(page)
    except PlaywrightError:
        # A page that is navigating or closing simply is not signed in yet.
        return False


def _starts_signed_in(page) -> bool:
    # ChatGPT renders its model control late, so a profile that is already
    # signed in gets the same grace period `_is_signed_out` allows.
    try:
        page.locator(REASONING_TRIGGER_SELECTOR).first.wait_for(
            state="visible",
            timeout=SIGNED_OUT_CONTROL_TIMEOUT_MS,
        )
    except PlaywrightError:
        return False
    return True


def _wait_for_enter(pressed: threading.Event) -> None:
    try:
        input()
    except (EOFError, OSError):
        return
    pressed.set()


def _wait_for_login(context, page, stop_requested: threading.Event) -> None:
    """Return once the user signs in, presses Enter, closes the browser, or stops."""
    pressed = threading.Event()
    interactive = sys.stdin.isatty()
    if interactive:
        threading.Thread(target=_wait_for_enter, args=(pressed,), daemon=True).start()

    # Finishing on its own is reserved for a sign-in that happens here, so a
    # profile opened to switch accounts stays open until the user is done.
    if _starts_signed_in(page):
        if not interactive:
            print("This ChatGPT profile is already signed in.")
            return
        print("This profile is already signed in. Press Enter here to close the browser...")
        auto_finish = False
    else:
        print(
            "Sign in to ChatGPT in the browser. CloakGPT saves the session once "
            "you are signed in"
            + (", or press Enter here to finish now." if interactive else "."),
            flush=True,
        )
        auto_finish = True

    while not pressed.is_set() and not stop_requested.is_set():
        pages = [candidate for candidate in context.pages if not candidate.is_closed()]
        if not pages:
            return
        if auto_finish and any(_page_is_signed_in(candidate) for candidate in pages):
            print("Signed in. Saving the session...")
            pages[0].wait_for_timeout(LOGIN_SAVE_DELAY_MS)
            return
        try:
            pages[0].wait_for_timeout(LOGIN_POLL_MS)
        except PlaywrightError:
            time.sleep(LOGIN_POLL_MS / 1_000)


@contextmanager
def _deferred_interrupts():
    """Turn Ctrl+C, a dropped SSH session, or `kill` into a request to stop.

    An exception raised inside a Playwright call leaves its sync API unable to
    close the browser, which would lose the profile and strand a virtual
    display. The first signal therefore only asks the login to wind down; a
    second one interrupts immediately.
    """
    requested = threading.Event()

    def request_stop(_signum, _frame) -> None:
        if requested.is_set():
            raise KeyboardInterrupt
        requested.set()

    previous = {}
    for name in ("SIGINT", "SIGHUP", "SIGTERM"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            previous[number] = signal.signal(number, request_stop)
        except ValueError:
            # Signal handlers can only be installed from the main thread.
            break
    try:
        yield requested
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _print_remote_login_instructions(display) -> None:
    print(f"Remote ChatGPT login is ready ({display.backend}, display :{display.display}).")
    print()
    print("On your own computer, open an SSH tunnel:")
    print(f"  {ssh_tunnel_hint(display.port)}")
    print("Then open this address in your browser:")
    print(f"  {display.viewer_url}")
    print()
    print(
        "Anyone who can open that page controls this login. Keep the port on "
        "127.0.0.1 and reach it only through SSH."
    )
    # A caller reading this through a pipe needs the address before login ends.
    print(flush=True)


def login(
    timezone: str,
    mode: str = "auto",
    vnc: str = AUTO_BACKEND,
    port: int | None = None,
) -> None:
    """Open the persistent browser profile for an interactive ChatGPT login."""
    remote = mode == "remote" or (mode == "auto" and not has_graphical_display())
    with _deferred_interrupts() as stop_requested:
        with open_remote_display(vnc, port) if remote else nullcontext() as display:
            if display is not None:
                _print_remote_login_instructions(display)
            context = launch_chatgpt_context(
                DEFAULT_PROFILE_DIR,
                headless=False,
                timezone=timezone,
                env=display.env if display is not None else None,
                args=display.browser_args if display is not None else None,
            )
            try:
                page = _login_page(context)
                page.goto(CHATGPT_URL, wait_until="domcontentloaded")
                _wait_for_login(context, page, stop_requested)
            finally:
                context.close()
    if stop_requested.is_set():
        raise KeyboardInterrupt


def _add_shared_options(
    parser: argparse.ArgumentParser,
    *,
    include_session: bool = False,
) -> None:
    parser.add_argument("question", help="message to send to ChatGPT")
    parser.add_argument(
        "--timezone",
        default="Asia/Taipei",
        help="user's IANA timezone (default: Asia/Taipei)",
    )
    parser.add_argument(
        "--model",
        type=ChatGPTModel,
        choices=list(ChatGPTModel),
        help="model; omit to keep ChatGPT's current setting",
    )
    parser.add_argument(
        "--reasoning",
        type=ReasoningLevel,
        choices=list(ReasoningLevel),
        help="reasoning level; omit to keep ChatGPT's current setting",
    )
    parser.add_argument(
        "--headed",
        action="store_false",
        dest="headless",
        help="show the browser window (default: run headless)",
    )
    if include_session:
        parser.add_argument(
            "--session",
            help="persistent session ID (or set CLOAKGPT_SESSION_ID)",
        )


def show_status(message: str) -> None:
    """Print browser progress without mixing it with the response text."""
    print(f"[status] {message}", file=sys.stderr, flush=True)


def _jsonl_status(message: str) -> None:
    print(
        json.dumps({"type": "status", "message": message}, ensure_ascii=False),
        flush=True,
    )


def _status_callback(output_format: str):
    return _jsonl_status if output_format == "jsonl" else show_status


def _print_answer(answer: str, output_format: str) -> None:
    if output_format == "jsonl":
        print(
            json.dumps({"type": "result", "answer": answer}, ensure_ascii=False),
            flush=True,
        )
        return
    print(answer)


def _print_command_error(message: str, output_format: str) -> None:
    if output_format == "jsonl":
        print(
            json.dumps({"type": "error", "message": message}, ensure_ascii=False),
            flush=True,
        )
        return
    print(f"error: {message}", file=sys.stderr)


def _start_one_shot(args, status_callback) -> str:
    status_callback("Submitting a new conversation to the shared browser...")
    result = request_broker(
        {
            "operation": "send_once",
            "question": args.question,
            "model": str(args.model) if args.model is not None else None,
            "reasoning": str(args.reasoning) if args.reasoning is not None else None,
        },
        headless=args.headless,
        timezone=args.timezone,
        status_callback=status_callback,
    )
    return str(result["answer"])


def run_browser_command(arguments: Sequence[str]) -> int:
    """Delegate browser management to CloakBrowser's official CLI."""
    original_argv = sys.argv
    sys.argv = ["cloakbrowser", *arguments]
    try:
        cloakbrowser_main()
    except SystemExit as error:
        if error.code is None:
            return 0
        if isinstance(error.code, int):
            return error.code
        print(error.code, file=sys.stderr)
        return 1
    finally:
        sys.argv = original_argv
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send messages through a user-owned ChatGPT browser session."
    )
    parser.add_argument("--version", action="version", version=version_text())
    commands = parser.add_subparsers(dest="command", required=True)

    login_parser = commands.add_parser(
        "login",
        help="open the persistent profile for interactive login",
    )
    login_parser.add_argument(
        "--timezone",
        default="Asia/Taipei",
        help="user's IANA timezone (default: Asia/Taipei)",
    )
    login_mode = login_parser.add_mutually_exclusive_group()
    login_mode.add_argument(
        "--local",
        action="store_const",
        const="local",
        dest="mode",
        help="open the browser on this machine's desktop",
    )
    login_mode.add_argument(
        "--remote",
        action="store_const",
        const="remote",
        dest="mode",
        help=(
            "Linux: show the browser in a temporary loopback-only web viewer to "
            "reach over SSH (default when no desktop is detected)"
        ),
    )
    login_parser.set_defaults(mode="auto")
    login_parser.add_argument(
        "--vnc",
        choices=(AUTO_BACKEND, *BACKENDS),
        default=AUTO_BACKEND,
        help="remote login VNC backend (default: auto, preferring tigervnc)",
    )
    login_parser.add_argument(
        "--port",
        type=int,
        help="remote login viewer port on 127.0.0.1 (default: first free from 6100)",
    )

    commands.add_parser(
        "browser",
        add_help=False,
        help="install, inspect, update, or clear the CloakBrowser binary",
    )

    update_parser = commands.add_parser(
        "update",
        help="check for or install a CloakGPT release",
    )
    update_parser.add_argument(
        "--check",
        action="store_true",
        help="report the selected release without changing files",
    )
    update_parser.add_argument(
        "--channel",
        choices=("stable", "prerelease"),
        help="release channel; omit to preserve the current channel",
    )
    update_parser.add_argument(
        "--version",
        dest="target_version",
        help="install an exact release tag",
    )
    update_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="write the final update result as JSON",
    )

    ask_parser = commands.add_parser(
        "ask",
        help="start a conversation or send to a persistent session",
    )
    _add_shared_options(ask_parser, include_session=True)
    ask_parser.add_argument(
        "--output",
        choices=("text", "jsonl"),
        default="text",
        dest="output_format",
        help="output protocol (default: text; jsonl streams agent events to stdout)",
    )

    session_parser = commands.add_parser(
        "session",
        help="open, inspect, or close a persistent agent session",
    )
    session_commands = session_parser.add_subparsers(
        dest="session_command",
        required=True,
    )
    session_open = session_commands.add_parser(
        "open",
        help="create a persistent conversation ID",
    )
    session_open.add_argument(
        "--timezone",
        default="Asia/Taipei",
        help="user's IANA timezone (default: Asia/Taipei)",
    )
    session_open.add_argument(
        "--headed",
        action="store_false",
        dest="headless",
        help="show the persistent browser window (default: run headless)",
    )
    for name in ("status", "close"):
        session_action = session_commands.add_parser(name)
        session_action.add_argument(
            "session_id",
            nargs="?",
            help="session ID (or set CLOAKGPT_SESSION_ID)",
        )

    daemon_parser = commands.add_parser(
        "daemon",
        help="inspect or stop the persistent browser broker",
    )
    daemon_commands = daemon_parser.add_subparsers(
        dest="daemon_command",
        required=True,
    )
    daemon_commands.add_parser("status")
    stop_parser = daemon_commands.add_parser("stop")
    stop_parser.add_argument(
        "--force",
        action="store_true",
        help="abandon requests that are still running instead of refusing to stop",
    )

    serve_parser = commands.add_parser(
        "serve",
        help="start an OpenAI-compatible HTTP API server",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="host to bind the HTTP server to (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="port to listen on (default: 8000)",
    )
    serve_parser.add_argument(
        "--api-key",
        help="optional API key required for requests (Authorization: Bearer <key>)",
    )
    serve_parser.add_argument(
        "--session",
        help="persistent session ID for requests (or set CLOAKGPT_SESSION_ID)",
    )
    serve_parser.add_argument(
        "--timezone",
        default="Asia/Taipei",
        help="user's IANA timezone (default: Asia/Taipei)",
    )
    serve_parser.add_argument(
        "--model",
        type=ChatGPTModel,
        choices=list(ChatGPTModel),
        help="default model override",
    )
    serve_parser.add_argument(
        "--reasoning",
        type=ReasoningLevel,
        choices=list(ReasoningLevel),
        help="reasoning level override",
    )
    serve_parser.add_argument(
        "--headed",
        action="store_false",
        dest="headless",
        help="show the browser window (default: run headless)",
    )
    serve_parser.add_argument(
        "--stateless",
        action="store_true",
        help="disable session continuity and open a new temporary conversation on every request",
    )
    return parser


def _run_hidden_daemon(arguments: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--timezone", default="Asia/Taipei")
    parser.add_argument("--headed", action="store_false", dest="headless")
    args = parser.parse_args(arguments)
    return run_broker(
        data_dir=DEFAULT_PROFILE_DIR.parent,
        headless=args.headless,
        timezone=args.timezone,
    )


def _run_hidden_playwright_check() -> int:
    driver_executable, driver_cli = compute_driver_executable()
    subprocess.run(
        [driver_executable, driver_cli, "run-driver"],
        stdin=subprocess.DEVNULL,
        check=True,
    )
    return 0


def _run_serve_command(args) -> int:
    session_id = args.session or os.environ.get("CLOAKGPT_SESSION_ID")
    server = OpenAIServer(
        host=args.host,
        port=args.port,
        api_key=args.api_key,
        session_id=session_id,
        stateless=args.stateless,
        default_model=str(args.model) if args.model is not None else None,
        reasoning=args.reasoning,
        headless=args.headless,
        timezone=args.timezone,
        verbose=True,
    )
    server.start()
    mode = "headless" if args.headless else "headed"
    print(
        f"[server] CloakGPT OpenAI-compatible API server running at http://{args.host}:{server.port}/v1",
        file=sys.stderr,
    )
    print(
        f"[server] Endpoints: /v1/models, /v1/chat/completions (Browser: {mode})",
        file=sys.stderr,
    )
    if args.stateless:
        print("[server] Session mode: stateless (send_once on every turn)", file=sys.stderr)
    elif session_id:
        print(f"[server] Session mode: pinned ({session_id})", file=sys.stderr)
    else:
        print(
            f"[server] Session mode: smart continuous session (active: {server.session_manager.active_session_id})",
            file=sys.stderr,
        )
    if args.api_key:
        print("[server] Authentication: Bearer token required", file=sys.stderr)
    print("[server] Press Ctrl+C to stop.", file=sys.stderr)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[server] Shutting down server...", file=sys.stderr)
    finally:
        server.shutdown()
        print("[server] Server stopped.", file=sys.stderr)
    return 0


def _required_session_id(value: str | None) -> str:
    session_id = value or os.environ.get("CLOAKGPT_SESSION_ID")
    if not session_id:
        raise ValueError(
            "session ID required; pass --session/SESSION_ID or set CLOAKGPT_SESSION_ID"
        )
    return session_id


def _print_session_motd(result: dict) -> None:
    session_id = result["session_id"]
    mode = "headless" if result["headless"] else "headed"
    print("[session] CloakGPT persistent conversation ready", file=sys.stderr)
    print(f"[session] ID: {session_id}", file=sys.stderr)
    print(
        f"[session] Browser: on demand ({mode}), timezone={result['timezone']}",
        file=sys.stderr,
    )
    print(
        "[session] Different session IDs can run concurrently.",
        file=sys.stderr,
    )
    print(
        f'[session] Next: cloakgpt ask --session {session_id} "message"',
        file=sys.stderr,
    )


def _run_session_command(args) -> int:
    if args.session_command == "open":
        result = request_broker(
            {
                "operation": "open",
                "headless": args.headless,
                "timezone": args.timezone,
            },
            headless=args.headless,
            timezone=args.timezone,
            status_callback=show_status,
        )
        _print_session_motd(result)
        print(result["session_id"])
        return 0

    session_id = _required_session_id(args.session_id)
    operation = "session_status" if args.session_command == "status" else "close"
    result = request_broker({"operation": operation, "session_id": session_id})
    print(json.dumps(result, indent=2))
    return 0


STOPPED_DAEMON_STATUS = {"running": False}
ALREADY_STOPPED_RESULT = {"stopped": True, "already_stopped": True}


def _run_daemon_control(command: str, force: bool) -> int:
    request = (
        {"operation": "ping"}
        if command == "status"
        else {"operation": "stop", "force": force}
    )
    try:
        result = request_broker(request, auto_start=False)
        if command == "status":
            # Older daemons predate the field, so state it from the reply itself.
            result = {"running": True, **result}
    except DaemonNotRunningError:
        # An absent daemon is an ordinary state: reporting it is what `status`
        # is for, and stopping what is already stopped is what was asked.
        result = (
            STOPPED_DAEMON_STATUS
            if command == "status"
            else ALREADY_STOPPED_RESULT
        )
    print(json.dumps(result, indent=2))
    return 0


def _stop_daemon_for_update() -> None:
    try:
        request_broker({"operation": "stop"}, auto_start=False)
    except DaemonNotRunningError:
        # Nothing owns the browser profile, so the update can go ahead.
        return
    # A daemon that is running but unreachable still owns the profile, so its
    # error is reported rather than swallowed; the update would otherwise
    # succeed and leave the next command to fail on a profile still in use.


SKILL_REFRESH_PROMPT = "Update the use-cloakgpt skill now? [Y/n] "
DECLINED_ANSWERS = {"n", "no"}


def _offer_skill_refresh(outdated: list[Path]) -> None:
    """Report a skill that no longer matches this build, and offer to refresh."""
    if not outdated:
        return
    print(
        f"The installed use-cloakgpt skill differs from this build "
        f"({len(outdated)} copy/copies)."
    )
    # An agent runs its instructions, so refreshing it needs a person's answer;
    # anywhere without one, the command is printed instead of being run.
    if sys.stdin.isatty():
        try:
            answer = input(SKILL_REFRESH_PROMPT)
        except EOFError:
            answer = "n"
        if answer.strip().lower() not in DECLINED_ANSWERS:
            if refresh_skill():
                print("Skill updated. Restart your agent to reload it.")
                return
            print("Could not run the skills installer.")
    print(f"Refresh it with: {install_command_text()}")


def _run_update_command(args) -> int:
    if args.channel and args.target_version:
        raise ValueError("--channel and --version cannot be used together")
    result = update_cloakgpt(
        channel=args.channel,
        version=args.target_version,
        check=args.check,
        status_callback=show_status,
        stop_daemon=_stop_daemon_for_update,
    )
    bundled = bundled_skill_text()
    outdated = outdated_skill_paths(bundled)
    if args.json_output:
        result = {
            **result,
            "skill": {
                "bundled": bundled is not None,
                "outdated": [str(path) for path in outdated],
                "install_command": install_command_text(),
            },
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0

    print(f"Current: {result['current']}")
    print(f"Target: {result['target']} ({result['asset']})")
    if result["status"] == "up_to_date":
        print("CloakGPT is up to date.")
    elif result["status"] == "update_available":
        print("An update is available.")
    elif result["status"] == "staged":
        print(
            "Update staged. Windows will finish replacing CloakGPT after "
            "this command exits."
        )
    else:
        print(f"Updated CloakGPT to {result['target']}.")
    _offer_skill_refresh(outdated)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    _configure_windows_utf8_stdio()
    previous_update = consume_windows_update_result()
    if previous_update:
        if previous_update.get("status") == "updated":
            show_status(
                f"Previous Windows update completed: {previous_update.get('version')}"
            )
        else:
            show_status(
                "Previous Windows update failed: "
                f"{previous_update.get('error', 'unknown error')}"
            )
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments[:1] == ["browser"]:
        return run_browser_command(arguments[1:])
    if arguments[:1] == ["_daemon"]:
        return _run_hidden_daemon(arguments[1:])
    if arguments == ["_playwright_check"]:
        return _run_hidden_playwright_check()

    args = build_parser().parse_args(arguments)

    try:
        if args.command == "login":
            login(args.timezone, args.mode, args.vnc, args.port)
            return 0
        if args.command == "session":
            return _run_session_command(args)
        if args.command == "daemon":
            return _run_daemon_control(
                args.daemon_command,
                getattr(args, "force", False),
            )
        if args.command == "update":
            return _run_update_command(args)
        if args.command == "serve":
            return _run_serve_command(args)

        status_callback = _status_callback(args.output_format)

        session_id = (
            args.session or os.environ.get("CLOAKGPT_SESSION_ID")
            if args.command == "ask"
            else None
        )
        if session_id:
            if not args.headless:
                raise ValueError(
                    "browser mode is selected by session open; omit --headed"
                )
            status_callback("Submitting the session message to the shared browser...")
            result = request_broker(
                {
                    "operation": "send",
                    "session_id": session_id,
                    "question": args.question,
                    "model": str(args.model) if args.model is not None else None,
                    "reasoning": str(args.reasoning)
                    if args.reasoning is not None
                    else None,
                },
                status_callback=status_callback,
            )
            _print_answer(result["answer"], args.output_format)
            return 0

        answer = _start_one_shot(args, status_callback)
    except KeyboardInterrupt:
        output_format = getattr(args, "output_format", "text")
        if output_format == "jsonl":
            _print_command_error("stopped", output_format)
        else:
            print("stopped", file=sys.stderr)
        return 130
    except Exception as error:
        _print_command_error(str(error), getattr(args, "output_format", "text"))
        return 1

    _print_answer(answer, args.output_format)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
