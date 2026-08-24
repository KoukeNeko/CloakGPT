"""Command-line interface for CloakGPT."""

import argparse
import sys
from collections.abc import Sequence

from chatgpt_browser import (
    REASONING_LEVEL_LABELS,
    continue_conversation,
    start_conversation,
)


def _add_shared_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("question", help="message to send to ChatGPT")
    parser.add_argument(
        "--timezone",
        default="Asia/Taipei",
        help="user's IANA timezone (default: Asia/Taipei)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="maximum wait in seconds (default: 120)",
    )
    parser.add_argument(
        "--reasoning",
        choices=REASONING_LEVEL_LABELS,
        help="reasoning level; omit to keep ChatGPT's current setting",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send messages through a user-owned ChatGPT browser session."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ask_parser = commands.add_parser("ask", help="start a new conversation")
    _add_shared_options(ask_parser)

    continue_parser = commands.add_parser(
        "continue",
        help="continue the last saved conversation",
    )
    _add_shared_options(continue_parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    operation = start_conversation if args.command == "ask" else continue_conversation

    try:
        answer = operation(
            args.question,
            timezone=args.timezone,
            timeout_seconds=args.timeout,
            reasoning_level=args.reasoning,
        )
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
