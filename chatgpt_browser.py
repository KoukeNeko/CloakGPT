"""Browser automation core for a user-owned ChatGPT session."""

from pathlib import Path
from time import monotonic
from urllib.parse import urlparse

from cloakbrowser import launch_persistent_context


CHATGPT_URL = "https://chatgpt.com/"
PROMPT_EDITOR_SELECTOR = "#prompt-textarea"
SEND_BUTTON_SELECTOR = '[data-testid="send-button"]'
ASSISTANT_MESSAGE_SELECTOR = '[data-message-author-role="assistant"]'

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILE_DIR = PROJECT_DIR / "chatgpt-profile"
DEFAULT_STATE_FILE = PROJECT_DIR / ".chatgpt-conversation-url"


def _validate_question(question: str) -> None:
    if not question.strip():
        raise ValueError("question must not be empty")


def _validate_conversation_url(url: str) -> None:
    parsed_url = urlparse(url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != "chatgpt.com"
        or "/c/" not in parsed_url.path
    ):
        raise ValueError("invalid ChatGPT conversation URL")


def _wait_for_reply(page, previous_count: int, timeout_seconds: int) -> str:
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


def _send_message(
    url: str,
    question: str,
    timezone: str,
    timeout_seconds: int,
    profile_dir: Path,
) -> tuple[str, str]:
    _validate_question(question)
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    context = launch_persistent_context(
        str(profile_dir),
        headless=False,
        locale="ja-JP",
        timezone=timezone,
    )
    try:
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        editor = page.locator(PROMPT_EDITOR_SELECTOR)
        editor.wait_for(state="visible", timeout=timeout_seconds * 1_000)
        previous_count = page.locator(ASSISTANT_MESSAGE_SELECTOR).count()
        editor.fill(question)

        send_button = page.locator(SEND_BUTTON_SELECTOR)
        send_button.wait_for(state="visible", timeout=10_000)
        send_button.click()

        answer = _wait_for_reply(page, previous_count, timeout_seconds)
        return answer, page.url
    finally:
        context.close()


def start_conversation(
    question: str,
    *,
    timezone: str = "Asia/Taipei",
    timeout_seconds: int = 120,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    state_file: Path = DEFAULT_STATE_FILE,
) -> str:
    """Start a new ChatGPT conversation and return the response text."""
    answer, conversation_url = _send_message(
        CHATGPT_URL,
        question,
        timezone,
        timeout_seconds,
        profile_dir,
    )
    _validate_conversation_url(conversation_url)
    state_file.write_text(conversation_url, encoding="utf-8")
    return answer


def continue_conversation(
    question: str,
    *,
    timezone: str = "Asia/Taipei",
    timeout_seconds: int = 120,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    state_file: Path = DEFAULT_STATE_FILE,
) -> str:
    """Continue the saved ChatGPT conversation and return the response text."""
    if not state_file.exists():
        raise ValueError("no saved conversation; start a conversation first")

    conversation_url = state_file.read_text(encoding="utf-8").strip()
    _validate_conversation_url(conversation_url)
    answer, current_url = _send_message(
        conversation_url,
        question,
        timezone,
        timeout_seconds,
        profile_dir,
    )
    _validate_conversation_url(current_url)
    state_file.write_text(current_url, encoding="utf-8")
    return answer
