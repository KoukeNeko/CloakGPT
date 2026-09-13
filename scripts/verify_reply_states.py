#!/usr/bin/env python3
"""Check CloakGPT's reply-state script against ChatGPT's real turn markup.

Each scenario rebuilds an assistant turn the way ChatGPT rendered it on
2026-09-13, including the notices it shows when a reply is lost, and runs the
same state script CloakGPT polls with in a real Chromium page.

Usage:
    python3 scripts/verify_reply_states.py
"""

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from cloakbrowser import launch_async  # noqa: E402

import chatgpt_browser  # noqa: E402

TURN_TEST_ID = "conversation-turn-2"
RECONNECTING_NOTICE = "接続が中断されました。回答の完了を待っています"
DELIVERY_TIMEOUT_NOTICE = "メッセージ配信がタイムアウトしました。もう一度お試しください。"
RETRY_LABEL = "再試行"
THINKING_LABEL = "思考中"
CHECKED_FIELDS = ("complete", "generating", "notice")


@dataclass(frozen=True)
class Scenario:
    name: str
    turn_html: str
    stop_visible: bool
    expected: dict


def message_html(message_id: str, content_html: str) -> str:
    return (
        f'<div data-message-author-role="assistant" data-message-id="{message_id}" '
        'class="min-h-8 text-message relative flex w-full flex-col items-end gap-2 '
        f'text-start break-words whitespace-normal">{content_html}</div>'
    )


def answer_message_html(answer_html: str) -> str:
    body = (
        '<div class="flex w-full flex-col gap-1 empty:hidden"><div>'
        '<div class="QKycbG_markdown text-token-text-primary text-base leading-6 '
        'markdown prose dark:prose-invert wrap-break-word w-full dark '
        f'markdown-new-styling">{answer_html}</div></div></div>'
    )
    return message_html("e9542774-ab48-4ebe-8984-a67dc964fcaa", body)


def notice_message_html(banner_classes: str, notice: str, retry: bool) -> str:
    retry_button = (
        '<button data-testid="regenerate-thread-error-button" '
        'class="btn relative btn-secondary"><div class="flex w-full items-center '
        f'justify-center gap-1.5">{RETRY_LABEL}</div></button>'
        if retry
        else ""
    )
    paragraph = f"<p>{notice}</p>" if notice else ""
    body = (
        '<div class="flex w-full flex-col gap-1 empty:hidden"></div>'
        f'<div class="{banner_classes}"><div class="flex min-w-0 grow gap-3 items-start">'
        '<div class="min-w-0 grow pt-[2px] ps-1"><div class="flex flex-row items-center '
        'justify-between gap-4"><div class="min-w-0 text-pretty break-words '
        'whitespace-pre-wrap"><div class="markdown break-words [&>:last-child]:mb-0">'
        f"{paragraph}</div></div></div></div></div>{retry_button}</div>"
    )
    return message_html("c1af10f4-be59-4e55-a1d5-71d37db420a7", body)


def reconnecting_notice_html() -> str:
    return notice_message_html(
        "text-token-text-primary border-token-border-default flex items-center gap-6 "
        "rounded-2xl border text-sm px-3 py-2.5 mb-2 w-full self-start mask-shimmer-muted",
        RECONNECTING_NOTICE,
        retry=False,
    )


def error_notice_html(notice: str) -> str:
    return notice_message_html(
        "text-token-text-error border-token-surface-error/15 bg-token-surface-error/5 "
        "flex items-center gap-6 rounded-2xl border text-sm px-3 py-2.5 mb-2 w-full self-start",
        notice,
        retry=True,
    )


def placeholder_message_html() -> str:
    body = (
        '<div class="flex w-full flex-col gap-1 empty:hidden"><div aria-busy="true" '
        'class="text-token-text-tertiary flex min-h-8 items-start gap-2 text-base">'
        '<div class="loading-shimmer-tertiary text-token-text-tertiary pb-0.5 select-none">'
        f"{THINKING_LABEL}</div></div></div>"
    )
    return message_html(
        "request-placeholder-request-6aa64a35-b130-83e8-8301-10250033e7f3-0", body
    )


def action_bar_html() -> str:
    return (
        '<div class="flex justify-start"><div role="group" aria-label="応答アクション">'
        '<button aria-label="回答をコピーする" data-testid="copy-turn-action-button" '
        'data-state="closed" type="button"><span>copy</span></button>'
        '<button aria-label="共有する" data-state="closed" type="button">share</button>'
        "</div></div>"
    )


def turn_html(messages_html: str, controls_html: str = "") -> str:
    return (
        f'<section data-testid="{TURN_TEST_ID}" data-turn="assistant">'
        '<h4 class="sr-only select-none">ChatGPT:</h4><div class="text-base my-auto mx-auto">'
        '<div data-conversation-screenshot-content="" class="flex w-full min-w-0 flex-col">'
        f'<div class="flex max-w-full flex-col gap-4 grow">{messages_html}</div>'
        f"{controls_html}</div></div></section>"
    )


def composer_html(stop_visible: bool) -> str:
    button = (
        '<button data-testid="stop-button" aria-label="ストリーミングの停止">stop</button>'
        if stop_visible
        else '<button data-testid="send-button" aria-label="プロンプトを送信する">send</button>'
    )
    return f'<form><div id="prompt-textarea" contenteditable="true"></div>{button}</form>'


def build_scenarios() -> list[Scenario]:
    finished = {"complete": True, "generating": False, "notice": None}
    return [
        Scenario(
            "reconnecting while ChatGPT still polls",
            turn_html(reconnecting_notice_html() + placeholder_message_html()),
            stop_visible=True,
            expected={"complete": False, "generating": True, "notice": RECONNECTING_NOTICE},
        ),
        Scenario(
            "reconnecting notice left after polling stopped",
            turn_html(reconnecting_notice_html()),
            stop_visible=False,
            expected={"complete": False, "generating": False, "notice": RECONNECTING_NOTICE},
        ),
        Scenario(
            "delivery timeout with a retry button",
            turn_html(error_notice_html(DELIVERY_TIMEOUT_NOTICE)),
            stop_visible=False,
            expected={"complete": False, "generating": False, "notice": DELIVERY_TIMEOUT_NOTICE},
        ),
        Scenario(
            "retry button without a message",
            turn_html(error_notice_html("")),
            stop_visible=False,
            expected={"complete": False, "generating": False, "notice": RETRY_LABEL},
        ),
        Scenario(
            "finished answer with its copy control",
            turn_html(answer_message_html("<p>OK.</p>"), action_bar_html()),
            stop_visible=False,
            expected=finished,
        ),
        Scenario(
            "finished answer that quotes a notice",
            turn_html(
                answer_message_html(f"<p>你收到的「{RECONNECTING_NOTICE}」是連線提示。</p>"),
                action_bar_html(),
            ),
            stop_visible=False,
            expected=finished,
        ),
        Scenario(
            "finished answer nesting markdown that quotes a notice",
            turn_html(
                answer_message_html(
                    f'<blockquote><div class="markdown"><p>{DELIVERY_TIMEOUT_NOTICE}</p>'
                    "</div></blockquote>"
                ),
                action_bar_html(),
            ),
            stop_visible=False,
            expected=finished,
        ),
        Scenario(
            "answer text before its controls render",
            turn_html(answer_message_html("<p>OK.</p>")),
            stop_visible=False,
            expected={"complete": False, "generating": False, "notice": None},
        ),
        Scenario(
            "answer still streaming",
            turn_html(answer_message_html("<p>OK so far</p>")),
            stop_visible=True,
            expected={"complete": False, "generating": True, "notice": None},
        ),
    ]


async def evaluate_scenario(page, scenario: Scenario) -> dict:
    # CloakBrowser's stealth page never settles Playwright's set_content, so the
    # fixture is written into the blank page's body directly.
    await page.evaluate(
        "html => { document.body.innerHTML = html; }",
        f"<main>{scenario.turn_html}</main>{composer_html(scenario.stop_visible)}",
    )
    return await page.evaluate(
        chatgpt_browser.RESPONSE_STATE_SCRIPT,
        chatgpt_browser.reply_state_argument(previous_count=0, turn_id=TURN_TEST_ID),
    )


def mismatched_fields(actual: dict, expected: dict) -> list[str]:
    return [
        f"{field}: expected {expected[field]!r}, got {actual.get(field)!r}"
        for field in CHECKED_FIELDS
        if actual.get(field) != expected[field]
    ]


def report_scenario(scenario: Scenario, actual: dict) -> bool:
    mismatches = mismatched_fields(actual, scenario.expected)
    if mismatches:
        print(f"[FAIL] {scenario.name}")
        for mismatch in mismatches:
            print(f"       {mismatch}")
        return False
    print(f"[PASS] {scenario.name}")
    return True


async def run_scenarios() -> bool:
    browser = await launch_async(headless=True)
    try:
        page = await browser.new_page()
        results = [
            report_scenario(scenario, await evaluate_scenario(page, scenario))
            for scenario in build_scenarios()
        ]
    finally:
        await browser.close()
    return all(results)


def main() -> int:
    passed = asyncio.run(run_scenarios())
    print("[SUCCESS] every reply state matched" if passed else "[FAILURE] see mismatches above")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
