"""Manually send one test prompt to ChatGPT and print its response.

Run this script locally, then sign in to your own ChatGPT account in the
browser window if the saved profile is not already authenticated.
"""

import argparse
from time import monotonic

from cloakbrowser import launch_persistent_context


CHATGPT_URL = "https://chatgpt.com/"
CHATGPT_PROFILE_DIR = "chatgpt-profile"
QUESTION_PLACEHOLDER = "質問してみましょう"
ASSISTANT_MESSAGE_SELECTOR = '[data-message-author-role="assistant"]'


def wait_for_reply(page, previous_count: int, timeout_seconds: int) -> str:
    """Wait for a new assistant message whose text has stopped changing."""
    page.wait_for_function(
        """previousCount =>
        document.querySelectorAll('[data-message-author-role="assistant"]').length
        > previousCount""",
        arg=previous_count,
        timeout=timeout_seconds * 1_000,
    )

    response = page.locator(ASSISTANT_MESSAGE_SELECTOR).last
    deadline = monotonic() + timeout_seconds
    previous_text = ""
    unchanged_checks = 0

    while monotonic() < deadline:
        current_text = response.inner_text().strip()
        if current_text and current_text == previous_text:
            unchanged_checks += 1
            if unchanged_checks == 3:
                return current_text
        else:
            unchanged_checks = 0
        previous_text = current_text
        page.wait_for_timeout(1_000)

    raise TimeoutError("ChatGPT did not finish responding before the timeout")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default="Reply only: OK.")
    parser.add_argument("--timezone", default="Asia/Taipei")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    context = launch_persistent_context(
        CHATGPT_PROFILE_DIR,
        headless=False,
        locale="ja-JP",
        timezone=args.timezone,
    )
    try:
        page = context.new_page()
        page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        print("Sign in to ChatGPT in the browser window if prompted.")

        question_box = page.get_by_placeholder(QUESTION_PLACEHOLDER)
        question_box.wait_for(timeout=args.timeout * 1_000)
        previous_count = page.locator(ASSISTANT_MESSAGE_SELECTOR).count()
        question_box.fill(args.question)
        question_box.press("Enter")

        print("Waiting for ChatGPT's response...")
        print(wait_for_reply(page, previous_count, args.timeout))
    finally:
        context.close()


if __name__ == "__main__":
    main()
