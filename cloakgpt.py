"""Command-line interface for CloakGPT."""

import argparse
import ctypes
import json
import os
import subprocess
import sys
from collections.abc import Sequence

from cloakbrowser.__main__ import main as cloakbrowser_main
from playwright._impl._driver import compute_driver_executable

from chatgpt_browser import (
    CHATGPT_URL,
    ChatGPTModel,
    DEFAULT_PROFILE_DIR,
    ReasoningLevel,
    launch_chatgpt_context,
    start_conversation,
)
from cloakgpt_session import request_broker, run_broker
from cloakgpt_update import (
    consume_windows_update_result,
    update_cloakgpt,
    version_text,
)


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


def login(timezone: str) -> None:
    """Open the persistent browser profile for an interactive ChatGPT login."""
    context = launch_chatgpt_context(
        DEFAULT_PROFILE_DIR,
        headless=False,
        timezone=timezone,
    )
    try:
        page = _login_page(context)
        page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        input("Sign in in the browser window, then press Enter here to save the session...")
    finally:
        context.close()


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
        help="open a persistent browser page and print its session ID",
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
    daemon_commands.add_parser("stop")
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
    lease_minutes = int(result["ttl_seconds"]) // 60
    print("[session] CloakGPT persistent conversation ready", file=sys.stderr)
    print(f"[session] ID: {session_id}", file=sys.stderr)
    print(
        f"[session] Browser: {mode}, timezone={result['timezone']}, "
        f"idle lease={lease_minutes} minutes",
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


def _run_daemon_control(command: str) -> int:
    result = request_broker(
        {"operation": "ping" if command == "status" else "stop"},
        auto_start=False,
    )
    print(json.dumps(result, indent=2))
    return 0


def _stop_daemon_for_update() -> None:
    try:
        request_broker({"operation": "stop"}, auto_start=False)
    except RuntimeError as error:
        if str(error) != "CloakGPT daemon is not running":
            raise


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
    if args.json_output:
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
            login(args.timezone)
            return 0
        if args.command == "session":
            return _run_session_command(args)
        if args.command == "daemon":
            return _run_daemon_control(args.daemon_command)
        if args.command == "update":
            return _run_update_command(args)

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
                status_callback=show_status,
            )
            print(result["answer"])
            return 0

        answer = start_conversation(
            args.question,
            timezone=args.timezone,
            headless=args.headless,
            model=args.model,
            reasoning_level=args.reasoning,
            status_callback=show_status,
        )
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
