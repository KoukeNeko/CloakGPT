"""Browser automation core for a user-owned ChatGPT session."""

from enum import Enum
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse

from cloakbrowser import launch_persistent_context


CHATGPT_URL = "https://chatgpt.com/"
PROMPT_EDITOR_SELECTOR = "#prompt-textarea"
SEND_BUTTON_SELECTOR = '[data-testid="send-button"]'
ASSISTANT_MESSAGE_SELECTOR = '[data-message-author-role="assistant"]'
REASONING_TRIGGER_SELECTOR = (
    'form button[aria-haspopup="menu"]:not(#composer-plus-btn)'
)
ADVANCED_VIEW_SELECTOR = '[role="menuitem"][aria-label="詳細表示にする"]'
REASONING_SUBMENU_ITEM_SELECTOR = '[role="menuitem"][aria-haspopup="menu"]'
REASONING_OPTION_SELECTOR = '[role="menuitemradio"]'


class StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class ChatGPTModel(StringEnum):
    GPT_5_6_SOL = "gpt-5.6-sol"
    GPT_5_5 = "gpt-5.5"
    O3 = "o3"


class ReasoningLevel(StringEnum):
    FAST = "fast"
    MEDIUM = "medium"
    HIGH = "high"


MODEL_LABELS = {
    ChatGPTModel.GPT_5_6_SOL: "GPT-5.6 Sol",
    ChatGPTModel.GPT_5_5: "GPT-5.5",
    ChatGPTModel.O3: "o3",
}

REASONING_LEVEL_INDEXES = {
    ReasoningLevel.FAST: 0,
    ReasoningLevel.MEDIUM: 1,
    ReasoningLevel.HIGH: 2,
}

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


def _open_advanced_submenu(page, submenu_index: int, menu_name: str):
    trigger = page.locator(REASONING_TRIGGER_SELECTOR)
    trigger.wait_for(state="visible", timeout=10_000)
    trigger.click()

    root_menu = page.locator('[role="menu"]:visible').first
    root_menu.wait_for(state="visible", timeout=10_000)
    advanced_view = root_menu.locator(ADVANCED_VIEW_SELECTOR)
    if advanced_view.count():
        advanced_view.click()

    submenu_items = root_menu.locator(REASONING_SUBMENU_ITEM_SELECTOR)
    if submenu_items.count() <= submenu_index:
        available = " ".join(root_menu.inner_text().split())
        raise ValueError(f"{menu_name} menu is unavailable; menu: {available}")

    submenu_items.nth(submenu_index).click()
    submenu = page.locator('[role="menu"]:visible').last
    return trigger, submenu


def _close_advanced_menus(page) -> None:
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")


def _set_model(page, model: ChatGPTModel) -> None:
    label = MODEL_LABELS[model]
    _, model_menu = _open_advanced_submenu(page, 0, "model")
    options = model_menu.locator(REASONING_OPTION_SELECTOR)
    matches = options.filter(has_text=label)
    if matches.count() != 1:
        available = " ".join(model_menu.inner_text().split())
        raise ValueError(f"model {label!r} is unavailable; menu: {available}")

    option = matches.first
    if option.get_attribute("aria-checked") == "true":
        _close_advanced_menus(page)
        return
    option.click()


def _set_reasoning_level(page, reasoning_level: ReasoningLevel) -> None:
    option_index = REASONING_LEVEL_INDEXES[reasoning_level]
    trigger, reasoning_menu = _open_advanced_submenu(page, 1, "reasoning")
    options = reasoning_menu.locator(REASONING_OPTION_SELECTOR)
    if options.count() <= option_index:
        available = " ".join(reasoning_menu.inner_text().split())
        raise ValueError(
            f"reasoning level {reasoning_level!r} is unavailable; menu: {available}"
        )

    option = options.nth(option_index)
    selected_label = option.inner_text().strip()
    if option.get_attribute("aria-checked") == "true":
        _close_advanced_menus(page)
        return

    option.click()
    deadline = monotonic() + 5
    while monotonic() < deadline:
        if trigger.inner_text().strip() == selected_label:
            return
        page.wait_for_timeout(100)
    else:
        raise RuntimeError("ChatGPT did not apply the selected reasoning level")


def _send_message(
    url: str,
    question: str,
    timezone: str,
    timeout_seconds: int,
    profile_dir: Path,
    model: ChatGPTModel | None,
    reasoning_level: ReasoningLevel | None,
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

        if model is not None:
            _set_model(page, model)
        if reasoning_level is not None:
            _set_reasoning_level(page, reasoning_level)

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
    model: ChatGPTModel | None = None,
    reasoning_level: ReasoningLevel | None = None,
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
        model,
        reasoning_level,
    )
    _validate_conversation_url(conversation_url)
    state_file.write_text(conversation_url, encoding="utf-8")
    return answer


def continue_conversation(
    question: str,
    *,
    timezone: str = "Asia/Taipei",
    timeout_seconds: int = 120,
    model: ChatGPTModel | None = None,
    reasoning_level: ReasoningLevel | None = None,
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
        model,
        reasoning_level,
    )
    _validate_conversation_url(current_url)
    state_file.write_text(current_url, encoding="utf-8")
    return answer
