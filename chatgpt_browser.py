"""Browser automation core for a user-owned ChatGPT session."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

from cloakbrowser import launch_persistent_context


CHATGPT_URL = "https://chatgpt.com/"
PROMPT_EDITOR_SELECTOR = "#prompt-textarea"
SEND_BUTTON_SELECTOR = '[data-testid="send-button"]'
ASSISTANT_MESSAGE_SELECTOR = '[data-message-author-role="assistant"]'
COPY_ACTION_SELECTOR = '[data-testid="copy-turn-action-button"]'
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

REASONING_LABELS = {
    ReasoningLevel.FAST: "最速",
    ReasoningLevel.MEDIUM: "中程度",
    ReasoningLevel.HIGH: "高い",
}

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILE_DIR = PROJECT_DIR / "chatgpt-profile"
DEFAULT_STATE_FILE = PROJECT_DIR / ".chatgpt-conversation-url"

StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class ChatGPTPageStatus:
    url: str
    model: str
    reasoning: str


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


def _emit_status(callback: StatusCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _wait_for_reply(
    page,
    previous_count: int,
    previous_copy_count: int,
    status_callback: StatusCallback | None,
) -> str:
    page.wait_for_function(
        """previousCount =>
        document.querySelectorAll('[data-message-author-role="assistant"]').length
        > previousCount""",
        arg=previous_count,
        timeout=0,
    )
    _emit_status(status_callback, "ChatGPT is responding...")
    page.wait_for_function(
        """previousCount =>
        document.querySelectorAll('[data-testid="copy-turn-action-button"]').length
        > previousCount""",
        arg=previous_copy_count,
        timeout=0,
    )
    return page.locator(ASSISTANT_MESSAGE_SELECTOR).last.inner_text().strip()


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


def _read_page_status(page) -> ChatGPTPageStatus:
    trigger = page.locator(REASONING_TRIGGER_SELECTOR)
    trigger.wait_for(state="visible", timeout=10_000)
    reasoning_text = trigger.inner_text().strip()
    reasoning = next(
        (
            level.value
            for level, label in REASONING_LABELS.items()
            if label in reasoning_text
        ),
        reasoning_text,
    )
    trigger.click()
    try:
        root_menu = page.locator('[role="menu"]:visible').first
        root_menu.wait_for(state="visible", timeout=10_000)
        submenu_items = root_menu.locator(REASONING_SUBMENU_ITEM_SELECTOR)
        if submenu_items.count() < 2:
            available = " ".join(root_menu.inner_text().split())
            raise ValueError(f"ChatGPT status is unavailable; menu: {available}")

        model_text = " ".join(submenu_items.nth(0).inner_text().split())
        model = next(
            (label for label in MODEL_LABELS.values() if label in model_text),
            model_text,
        )
        return ChatGPTPageStatus(page.url, model, reasoning)
    finally:
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
    for _ in range(50):
        if trigger.inner_text().strip() == selected_label:
            return
        page.wait_for_timeout(100)
    raise RuntimeError("ChatGPT did not apply the selected reasoning level")


def _send_message(
    url: str,
    question: str,
    timezone: str,
    profile_dir: Path,
    model: ChatGPTModel | None,
    reasoning_level: ReasoningLevel | None,
    status_callback: StatusCallback | None,
) -> tuple[str, str]:
    _validate_question(question)

    _emit_status(status_callback, "Opening ChatGPT...")
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
            _emit_status(status_callback, f"Selecting model: {model}")
            _set_model(page, model)
        if reasoning_level is not None:
            _emit_status(status_callback, f"Selecting reasoning: {reasoning_level}")
            _set_reasoning_level(page, reasoning_level)

        status = _read_page_status(page)
        _emit_status(
            status_callback,
            f"Current page: model={status.model}, reasoning={status.reasoning}, url={status.url}",
        )

        editor = page.locator(PROMPT_EDITOR_SELECTOR)
        editor.wait_for(state="visible", timeout=30_000)
        previous_count = page.locator(ASSISTANT_MESSAGE_SELECTOR).count()
        previous_copy_count = page.locator(COPY_ACTION_SELECTOR).count()
        editor.fill(question)

        send_button = page.locator(SEND_BUTTON_SELECTOR)
        send_button.wait_for(state="visible", timeout=10_000)
        _emit_status(status_callback, "Sending message...")
        send_button.click()

        _emit_status(status_callback, "Waiting for ChatGPT response (Ctrl+C to stop)...")
        answer = _wait_for_reply(
            page,
            previous_count,
            previous_copy_count,
            status_callback,
        )
        _emit_status(status_callback, "Response complete.")
        return answer, page.url
    finally:
        context.close()


def start_conversation(
    question: str,
    *,
    timezone: str = "Asia/Taipei",
    model: ChatGPTModel | None = None,
    reasoning_level: ReasoningLevel | None = None,
    status_callback: StatusCallback | None = None,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    state_file: Path = DEFAULT_STATE_FILE,
) -> str:
    """Start a new ChatGPT conversation and return the response text."""
    answer, conversation_url = _send_message(
        CHATGPT_URL,
        question,
        timezone,
        profile_dir,
        model,
        reasoning_level,
        status_callback,
    )
    _validate_conversation_url(conversation_url)
    state_file.write_text(conversation_url, encoding="utf-8")
    return answer


def continue_conversation(
    question: str,
    *,
    timezone: str = "Asia/Taipei",
    model: ChatGPTModel | None = None,
    reasoning_level: ReasoningLevel | None = None,
    status_callback: StatusCallback | None = None,
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
        profile_dir,
        model,
        reasoning_level,
        status_callback,
    )
    _validate_conversation_url(current_url)
    state_file.write_text(current_url, encoding="utf-8")
    return answer
