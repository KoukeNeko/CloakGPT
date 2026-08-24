"""Command-line interface for CloakGPT."""

import argparse
import sys
from collections.abc import Sequence

from cloakbrowser import launch_persistent_context
from cloakbrowser.__main__ import main as cloakbrowser_main

from chatgpt_browser import (
    CHATGPT_URL,
    ChatGPTModel,
    DEFAULT_PROFILE_DIR,
    ReasoningLevel,
    continue_conversation,
    start_conversation,
)


def login(timezone: str) -> None:
    """Open the persistent browser profile for an interactive ChatGPT login."""
    context = launch_persistent_context(
        str(DEFAULT_PROFILE_DIR),
        headless=False,
        locale="ja-JP",
        timezone=timezone,
    )
    try:
        page = context.new_page()
        page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        input("Sign in in the browser window, then press Enter here to save the session...")
    finally:
        context.close()


def _add_shared_options(parser: argparse.ArgumentParser) -> None:
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

    ask_parser = commands.add_parser("ask", help="start a new conversation")
    _add_shared_options(ask_parser)

    continue_parser = commands.add_parser(
        "continue",
        help="continue the last saved conversation",
    )
    _add_shared_options(continue_parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments[:1] == ["browser"]:
        return run_browser_command(arguments[1:])

    args = build_parser().parse_args(arguments)

    try:
        if args.command == "login":
            login(args.timezone)
            return 0

        operation = (
            start_conversation if args.command == "ask" else continue_conversation
        )
        answer = operation(
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
