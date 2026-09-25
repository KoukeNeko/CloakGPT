#!/usr/bin/env python3
"""Check CloakGPT's reply-state script against ChatGPT's real turn markup.

Each scenario rebuilds a conversation turn the way ChatGPT rendered it on
2026-09-26, including the alert it shows when a reply is lost, and runs the
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

TURN_KEY = "a5260bf4-22b1-4e24-a53f-01c5b8e59bae"
RECONNECTING_NOTICE = "接続が中断されました。回答の完了を待っています"
DELIVERY_TIMEOUT_NOTICE = "メッセージ配信がタイムアウトしました。もう一度お試しください。"
FAILED_FETCH_NOTICE = "Failed to fetch"
RETRY_LABEL = "再試行"
SEARCHING_LABEL = "ウェブを検索中"
CHECKED_FIELDS = ("complete", "generating", "notice", "status")


@dataclass(frozen=True)
class Scenario:
    name: str
    turn_html: str
    stop_visible: bool
    expected: dict


def user_part_html() -> str:
    return (
        "<h4>あなたの発言:</h4>"
        '<div data-chatgpt-search-unit-key="fallback-turn-0:0:user" '
        f'data-chatgpt-search-message-ids="{TURN_KEY}">'
        '<div data-content-search-unit-key="fallback-turn-0:0:user"><div>'
        '<div data-user-message-bubble="true"><div dir="auto">Hello</div></div>'
        '<span data-state="closed"><button type="button" '
        'aria-label="メッセージをコピーする"><svg></svg></button></span>'
        "</div></div></div>"
    )


def answer_unit_html(answer_html: str, streaming: bool) -> str:
    animated = " data-markdown-animated=\"\"" if streaming else ""
    return (
        '<div data-content-search-unit-key="fallback-turn-0:2:assistant" '
        'data-chatgpt-search-unit-key="fallback-turn-0:2:assistant">'
        '<h4 data-conversation-role="assistant" tabindex="-1">ChatGPT の発言:</h4>'
        '<div data-chatgpt-selection-conversation-id="6ab6b7c6-ccd4-83ee-801f-61dbdd622094">'
        '<span hidden=""></span>'
        f'<div dir="auto"{animated} data-markdown-text-style="assistant-message">'
        f"{answer_html}</div></div></div>"
    )


def activity_html(label: str) -> str:
    # The label is doubled by an aria-hidden shimmer overlay.
    return (
        "<div><div><div><span><span><svg></svg></span><span><span><span>"
        f'{label}<span aria-hidden="true"><span>{label}</span></span>'
        "</span></span></span></span></div></div></div>"
    )


def agent_area_html(content_html: str) -> str:
    return (
        '<div><span hidden="" data-chatgpt-agent-turn-start=""></span>'
        f'{content_html}<span hidden=""></span></div>'
    )


def action_bar_html() -> str:
    return (
        '<div><div><span data-state="closed"><button type="button" '
        'aria-label="コピーする"><svg></svg></button></span>'
        '<span data-state="closed"><button type="button" aria-label="共有">'
        "<svg></svg></button></span>"
        '<button type="button" aria-label="回答を再生成" aria-haspopup="menu">'
        "<svg></svg></button></div></div>"
    )


def waiting_status_html() -> str:
    return (
        '<div><span aria-busy="true" role="status"><span>ChatGPT が応答中</span>'
        '<span aria-hidden="true"></span></span></div>'
    )


def alert_html(notice: str) -> str:
    return (
        '<div><aside role="alert"><div aria-hidden="true"></div><div><div><div>'
        f"<div>{notice}</div></div></div><div><button type=\"button\">{RETRY_LABEL}"
        "</button></div></div></aside></div>"
    )


def turn_html(reply_html: str) -> str:
    return (
        f'<div data-turn-key="{TURN_KEY}"><div data-content-search-turn-key="fallback-turn-0">'
        f"<div><div>{user_part_html()}</div>{reply_html}</div></div></div>"
    )


def composer_html(stop_visible: bool) -> str:
    button = (
        '<button type="button" aria-label="停止"><svg></svg></button>'
        if stop_visible
        else '<button type="submit" aria-label="送信"><svg></svg></button>'
    )
    return (
        '<form><div contenteditable="true" role="textbox" data-composer-markdown="">'
        f"</div>{button}</form>"
    )


def state(complete=False, generating=False, notice=None, status=None) -> dict:
    return {
        "complete": complete,
        "generating": generating,
        "notice": notice,
        "status": status,
    }


def build_scenarios() -> list[Scenario]:
    finished = state(complete=True)
    return [
        Scenario(
            "waiting before ChatGPT shows anything",
            turn_html(waiting_status_html()),
            stop_visible=True,
            expected=state(generating=True),
        ),
        Scenario(
            "searching the web before the answer",
            turn_html(agent_area_html(activity_html(SEARCHING_LABEL))),
            stop_visible=True,
            expected=state(generating=True, status=SEARCHING_LABEL),
        ),
        Scenario(
            "answer still streaming",
            turn_html(agent_area_html(answer_unit_html("<p>OK so</p>", streaming=True))),
            stop_visible=True,
            expected=state(generating=True),
        ),
        Scenario(
            "answer animating after the stop button left",
            turn_html(agent_area_html(answer_unit_html("<p>OK so</p>", streaming=True))),
            stop_visible=False,
            expected=state(generating=True),
        ),
        Scenario(
            "answer text before its controls render",
            turn_html(agent_area_html(answer_unit_html("<p>OK.</p>", streaming=False))),
            stop_visible=False,
            expected=state(),
        ),
        Scenario(
            "finished answer with its copy control",
            turn_html(
                agent_area_html(answer_unit_html("<p>OK.</p>", streaming=False))
                + action_bar_html()
            ),
            stop_visible=False,
            expected=finished,
        ),
        Scenario(
            "finished answer that quotes a notice",
            turn_html(
                agent_area_html(answer_unit_html(
                    f"<p>你收到的「{RECONNECTING_NOTICE}」是連線提示。</p>",
                    streaming=False,
                ))
                + action_bar_html()
            ),
            stop_visible=False,
            expected=finished,
        ),
        Scenario(
            "reply lost before it started",
            turn_html(alert_html(FAILED_FETCH_NOTICE)),
            stop_visible=False,
            expected=state(notice=FAILED_FETCH_NOTICE),
        ),
        Scenario(
            "reply lost after part of the answer",
            turn_html(
                agent_area_html(answer_unit_html("<p>OK so</p>", streaming=False))
                + alert_html(DELIVERY_TIMEOUT_NOTICE)
            ),
            stop_visible=False,
            expected=state(notice=DELIVERY_TIMEOUT_NOTICE),
        ),
        Scenario(
            "known notice wording beside the answer while ChatGPT retries",
            turn_html(agent_area_html(activity_html(RECONNECTING_NOTICE))),
            stop_visible=True,
            expected=state(generating=True, notice=RECONNECTING_NOTICE),
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
        chatgpt_browser.reply_state_argument(previous_count=0, turn_id=TURN_KEY),
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
