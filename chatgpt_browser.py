"""Browser automation core for a user-owned ChatGPT session."""

import os
import platform
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from cloakbrowser import launch_persistent_context


CHATGPT_URL = "https://chatgpt.com/"
PROMPT_EDITOR_SELECTOR = "#prompt-textarea"
SEND_BUTTON_SELECTOR = '[data-testid="send-button"]'
ASSISTANT_MESSAGE_SELECTOR = '[data-message-author-role="assistant"]'
STOP_BUTTON_SELECTOR = '[data-testid="stop-button"]'
CITATION_PILL_SELECTOR = '[data-testid="webpage-citation-pill"]'
SOURCE_POPOVER_SELECTOR = '[data-radix-popper-content-wrapper]:visible'
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

SOURCE_DIR = Path(__file__).resolve().parent


def get_default_data_dir() -> Path:
    custom_dir = os.environ.get("CLOAKGPT_DATA_DIR")
    if custom_dir:
        return Path(custom_dir).expanduser()
    if not getattr(sys, "frozen", False):
        return SOURCE_DIR

    system = platform.system()
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base_dir = (
            Path(local_app_data)
            if local_app_data
            else Path.home() / "AppData" / "Local"
        )
        return base_dir / "CloakGPT"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "CloakGPT"

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base_dir = (
        Path(xdg_data_home)
        if xdg_data_home
        else Path.home() / ".local" / "share"
    )
    return base_dir / "CloakGPT"


DEFAULT_DATA_DIR = get_default_data_dir()
DEFAULT_PROFILE_DIR = DEFAULT_DATA_DIR / "chatgpt-profile"
DEFAULT_STATE_FILE = DEFAULT_DATA_DIR / ".chatgpt-conversation-url"

StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class ChatGPTPageStatus:
    url: str
    model: str
    reasoning: str


@dataclass(frozen=True)
class ChatGPTSource:
    title: str
    url: str


RENDER_MARKDOWN_SCRIPT = r"""response => {
  const citationSelector = '[data-testid="webpage-citation-pill"]';
  const interactiveWidgetSelector = '[data-testid="dil-widget-shell"]';

  function children(node) {
    return [...node.childNodes].map(render).join('');
  }

  function list(node, ordered, depth = 0) {
    let number = Number(node.getAttribute('start') || 1);
    const items = [...node.children].filter(child => child.tagName === 'LI');
    return items.map(item => {
      const nestedLists = [...item.children].filter(
        child => child.tagName === 'UL' || child.tagName === 'OL'
      );
      const body = [...item.childNodes]
        .filter(child => !nestedLists.includes(child))
        .map(render)
        .join('')
        .trim()
        .replace(/\n+/g, ' ');
      const prefix = ordered ? `${number++}. ` : '- ';
      const nested = nestedLists.map(
        child => list(child, child.tagName === 'OL', depth + 1).trimEnd()
      ).join('\n');
      return `${'  '.repeat(depth)}${prefix}${body}${nested ? `\n${nested}` : ''}`;
    }).join('\n') + '\n\n';
  }

  function table(node) {
    const rows = [...node.querySelectorAll('tr')].map(row =>
      [...row.querySelectorAll(':scope > th, :scope > td')]
        .map(cell => children(cell).trim().replace(/\|/g, '\\|'))
    ).filter(row => row.length);
    if (!rows.length) return '';
    const width = Math.max(...rows.map(row => row.length));
    const normalized = rows.map(row => [
      ...row,
      ...Array(Math.max(0, width - row.length)).fill('')
    ]);
    return normalized.map((row, index) => {
      const line = `| ${row.join(' | ')} |`;
      return index === 0
        ? `${line}\n| ${row.map(() => '---').join(' | ')} |`
        : line;
    }).join('\n') + '\n\n';
  }

  function render(node) {
    if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || '';
    if (node.nodeType !== Node.ELEMENT_NODE) return '';
    if (node.matches(`${citationSelector}, ${interactiveWidgetSelector}`)) return '';

    const tag = node.tagName;
    const content = () => children(node);
    if (/^H[1-6]$/.test(tag)) {
      return `${'#'.repeat(Number(tag[1]))} ${content().trim()}\n\n`;
    }
    if (tag === 'P') return `${content().trim()}\n\n`;
    if (tag === 'BR') return '\n';
    if (tag === 'UL') return list(node, false);
    if (tag === 'OL') return list(node, true);
    if (tag === 'LI') return content();
    if (tag === 'BLOCKQUOTE') {
      return content().trim().split('\n').map(line => `> ${line}`).join('\n') + '\n\n';
    }
    if (tag === 'PRE') {
      const code = node.querySelector('code');
      const text = (code || node).innerText.replace(/\n$/, '');
      const languageClass = [...(code?.classList || [])].find(
        name => name.startsWith('language-')
      );
      const language = languageClass ? languageClass.slice(9) : '';
      const fence = text.includes('```') ? '````' : '```';
      return `${fence}${language}\n${text}\n${fence}\n\n`;
    }
    if (tag === 'CODE') return `\`${content()}\``;
    if (tag === 'STRONG' || tag === 'B') return `**${content()}**`;
    if (tag === 'EM' || tag === 'I') return `*${content()}*`;
    if (tag === 'DEL' || tag === 'S') return `~~${content()}~~`;
    if (tag === 'A') {
      const text = content().trim();
      const href = node.getAttribute('href');
      return href ? `[${text || href}](${href})` : text;
    }
    if (tag === 'IMG') {
      const source = node.getAttribute('src');
      return source ? `![${node.getAttribute('alt') || ''}](${source})` : '';
    }
    if (tag === 'HR') return '---\n\n';
    if (tag === 'TABLE') return table(node);
    if (tag === 'SUP') return `<sup>${content()}</sup>`;
    if (tag === 'SUB') return `<sub>${content()}</sub>`;
    return content();
  }

  const body = response.querySelector('.markdown') || response;
  return render(body)
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}"""

TURN_ID_SCRIPT = """response => response
  .closest('section[data-turn="assistant"]')
  ?.getAttribute('data-testid') || null"""

RESPONSE_STATE_SCRIPT = r"""({previousCount, turnId}) => {
  const messages = document.querySelectorAll(
    '[data-message-author-role="assistant"]'
  );
  const response = messages[messages.length - 1];
  const turn = [...document.querySelectorAll('section[data-turn="assistant"]')]
    .find(element => element.getAttribute('data-testid') === turnId);
  const visible = element => !!(element && (
    element.offsetWidth
    || element.offsetHeight
    || element.getClientRects().length
  ));
  const stopButtonVisible = [...document.querySelectorAll(
    '[data-testid="stop-button"]'
  )].some(visible);
  const messageId = response?.getAttribute('data-message-id') || '';
  const statusButton = [...(turn?.querySelectorAll('button') || [])]
    .filter(visible)
    .find(button => {
      const text = (button.innerText || '').trim();
      const ariaLabel = button.getAttribute('aria-label') || '';
      return /思考中|考えました/.test(text)
        || ariaLabel.endsWith('中');
    });
  return {
    complete: messages.length > previousCount
      && !!response?.innerText.trim()
      && !messageId.startsWith('request-placeholder-')
      && !response.querySelector('[aria-busy="true"]')
      && !response.querySelector('.streaming-animation')
      && !stopButtonVisible,
    status: statusButton
      ? ((statusButton.innerText || '').trim()
        || statusButton.getAttribute('aria-label'))
      : null
  };
}"""


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


def _clean_source_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() != "utm_source"
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _source_from_link(href: str | None, text: str) -> ChatGPTSource | None:
    if not href:
        return None
    url = _clean_source_url(href)
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        return None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[1] if len(lines) > 1 else parsed_url.hostname
    return ChatGPTSource(title=title, url=url)


def _format_response(markdown: str, sources: list[ChatGPTSource]) -> str:
    sources_by_url: dict[str, ChatGPTSource] = {}
    for source in sources:
        existing = sources_by_url.get(source.url)
        if existing is None or len(source.title) > len(existing.title):
            sources_by_url[source.url] = source
    unique_sources = list(sources_by_url.values())
    if not unique_sources:
        return markdown.strip()

    source_lines = []
    for index, source in enumerate(unique_sources, start=1):
        title = source.title.replace("\\", "\\\\").replace("[", "\\[").replace(
            "]", "\\]"
        )
        source_lines.append(f"{index}. [{title}]({source.url})")
    return f"{markdown.strip()}\n\n## Sources\n\n" + "\n".join(source_lines)


def _extract_sources(page, response) -> list[ChatGPTSource]:
    sources: list[ChatGPTSource] = []
    pills = response.locator(CITATION_PILL_SELECTOR)
    for index in range(pills.count()):
        pill = pills.nth(index)
        direct_links = pill.locator("a[href]")
        if direct_links.count():
            direct_link = direct_links.first
            direct_source = _source_from_link(
                direct_link.get_attribute("href"), direct_link.inner_text()
            )
            if direct_source is not None:
                sources.append(direct_source)

        pill.hover(force=True, timeout=5_000)
        page.wait_for_timeout(750)
        popovers = page.locator(SOURCE_POPOVER_SELECTOR)
        if not popovers.count():
            continue
        popover = popovers.first
        counter = re.search(r"\b\d+/(\d+)\b", popover.inner_text())
        source_count = int(counter.group(1)) if counter else 1
        for source_index in range(source_count):
            links = popover.locator("a[href]")
            if not links.count():
                break
            link = links.first
            source = _source_from_link(link.get_attribute("href"), link.inner_text())
            if source is not None:
                sources.append(source)
            if source_index + 1 < source_count:
                buttons = popover.locator("button")
                if buttons.count() < 2:
                    break
                buttons.nth(1).click(force=True, timeout=5_000)
                page.wait_for_timeout(300)
        page.keyboard.press("Escape")
    return sources


def _extract_response(page) -> str:
    response = page.locator(ASSISTANT_MESSAGE_SELECTOR).last
    markdown = response.evaluate(RENDER_MARKDOWN_SCRIPT)
    return _format_response(markdown, _extract_sources(page, response))


def _wait_for_reply(
    page,
    previous_count: int,
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
    response = page.locator(ASSISTANT_MESSAGE_SELECTOR).last
    turn_id = response.evaluate(TURN_ID_SCRIPT)
    previous_status = None
    while True:
        state = page.evaluate(
            RESPONSE_STATE_SCRIPT,
            {"previousCount": previous_count, "turnId": turn_id},
        )
        current_status = state["status"]
        if current_status and current_status != previous_status:
            _emit_status(status_callback, f"ChatGPT activity: {current_status}")
            previous_status = current_status
        if state["complete"]:
            break
        page.wait_for_timeout(250)
    _emit_status(status_callback, "Collecting response and sources...")
    return _extract_response(page)


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
    headless: bool,
    model: ChatGPTModel | None,
    reasoning_level: ReasoningLevel | None,
    status_callback: StatusCallback | None,
) -> tuple[str, str]:
    _validate_question(question)

    _emit_status(status_callback, "Opening ChatGPT...")
    context = launch_persistent_context(
        str(profile_dir),
        headless=headless,
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
        editor.fill(question)

        send_button = page.locator(SEND_BUTTON_SELECTOR)
        send_button.wait_for(state="visible", timeout=10_000)
        _emit_status(status_callback, "Sending message...")
        send_button.click()

        _emit_status(status_callback, "Waiting for ChatGPT response (Ctrl+C to stop)...")
        answer = _wait_for_reply(
            page,
            previous_count,
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
    headless: bool = True,
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
        headless,
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
    headless: bool = True,
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
        headless,
        model,
        reasoning_level,
        status_callback,
    )
    _validate_conversation_url(current_url)
    state_file.write_text(current_url, encoding="utf-8")
    return answer
