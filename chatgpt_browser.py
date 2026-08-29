"""Browser automation core for a user-owned ChatGPT session."""

import asyncio
import os
import platform
import random
import re
import time
from contextlib import asynccontextmanager
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from cloakbrowser import launch_persistent_context, launch_persistent_context_async
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


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
INLINE_REASONING_SELECTOR = (
    '[role="slider"][aria-valuenow], '
    '[aria-valuenow][aria-valuemin][aria-valuemax], '
    '[aria-posinset][aria-setsize]:not([role="menuitemradio"])'
)
PROFILE_IN_USE_MARKERS = (
    "exitCode=21",
    "Opening in existing browser session",
    "既存のブラウザ セッションで開いています",
)
HUMAN_TYPING_TARGET_DURATION_MS = 4_500
HUMAN_TYPING_MIN_DELAY_MS = 6
HUMAN_TYPING_MAX_DELAY_MS = 90
HUMAN_TYPING_JITTER = 0.35
LINE_BREAK_SHORTCUT = "Shift+Enter"
DEFAULT_RESPONSE_STALL_SECONDS = 900
RESPONSE_STALL_ENV_VAR = "CLOAKGPT_RESPONSE_STALL_SECONDS"
UNLIMITED_RESPONSE_STALL = 0
MILLISECONDS_PER_SECOND = 1_000
KEEPALIVE_SCROLL_MIN_INTERVAL_SECONDS = 8.0
KEEPALIVE_SCROLL_MAX_INTERVAL_SECONDS = 18.0
KEEPALIVE_SCROLL_MIN_DISTANCE = 120
KEEPALIVE_SCROLL_MAX_DISTANCE = 360
KEEPALIVE_SCROLL_MIN_RETURN_DELAY_SECONDS = 0.2
KEEPALIVE_SCROLL_MAX_RETURN_DELAY_SECONDS = 0.7
KEEPALIVE_SCROLL_SKIP_CHANCE = 0.4


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


class ProfileInUseError(RuntimeError):
    """Raised when Chromium cannot own CloakGPT's persistent profile."""


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

StatusCallback = Callable[[str], None]


@asynccontextmanager
async def _without_composer_lock():
    yield


def launch_chatgpt_context(
    profile_dir: Path,
    *,
    headless: bool,
    timezone: str,
):
    """Launch CloakGPT's profile and replace Chromium's noisy lock error."""
    try:
        return launch_persistent_context(
            str(profile_dir),
            headless=headless,
            locale="ja-JP",
            timezone=timezone,
        )
    except Exception as error:
        message = str(error)
        if any(marker in message for marker in PROFILE_IN_USE_MARKERS):
            raise ProfileInUseError(
                "the CloakGPT browser profile is already in use. Close any "
                "CloakGPT Chromium window. If `cloakgpt daemon status` reports "
                "a running daemon, reuse its known `--session` ID or run "
                "`cloakgpt daemon stop`; then retry."
            ) from None
        raise


async def launch_chatgpt_context_async(
    profile_dir: Path,
    *,
    headless: bool,
    timezone: str,
):
    """Launch CloakGPT's profile with the async Playwright API."""
    try:
        return await launch_persistent_context_async(
            str(profile_dir),
            headless=headless,
            locale="ja-JP",
            timezone=timezone,
        )
    except Exception as error:
        message = str(error)
        if any(marker in message for marker in PROFILE_IN_USE_MARKERS):
            raise ProfileInUseError(
                "the CloakGPT browser profile is already in use. Close any "
                "CloakGPT Chromium window. If `cloakgpt daemon status` reports "
                "a running daemon, reuse its known `--session` ID or run "
                "`cloakgpt daemon stop`; then retry."
            ) from None
        raise


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
    progress: (response?.innerText || '').length,
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


def response_stall_seconds() -> float | None:
    """Return how long ChatGPT may show no progress, or None to wait forever."""
    value = os.environ.get(RESPONSE_STALL_ENV_VAR)
    if value is None:
        return DEFAULT_RESPONSE_STALL_SECONDS
    try:
        stall = int(value)
    except ValueError as error:
        raise ValueError(f"{RESPONSE_STALL_ENV_VAR} must be an integer") from error
    if stall < UNLIMITED_RESPONSE_STALL:
        raise ValueError(f"{RESPONSE_STALL_ENV_VAR} must not be negative")
    if stall == UNLIMITED_RESPONSE_STALL:
        return None
    return stall


def _validate_question(question: str) -> None:
    if not question.strip():
        raise ValueError("question must not be empty")


def _human_typing_delay_range(question: str) -> tuple[int, int]:
    average_delay = max(
        HUMAN_TYPING_MIN_DELAY_MS,
        min(
            HUMAN_TYPING_MAX_DELAY_MS,
            HUMAN_TYPING_TARGET_DURATION_MS / len(question),
        ),
    )
    minimum_delay = max(
        HUMAN_TYPING_MIN_DELAY_MS,
        round(average_delay * (1 - HUMAN_TYPING_JITTER)),
    )
    maximum_delay = min(
        HUMAN_TYPING_MAX_DELAY_MS,
        round(average_delay * (1 + HUMAN_TYPING_JITTER)),
    )
    return minimum_delay, maximum_delay


def _normalize_line_endings(question: str) -> str:
    return question.replace("\r\n", "\n").replace("\r", "\n")


async def _type_question_like_human(editor, question: str) -> None:
    await editor.fill("")
    await editor.focus()
    normalized_question = _normalize_line_endings(question)
    minimum_delay, maximum_delay = _human_typing_delay_range(normalized_question)
    for character in normalized_question:
        delay = random.randint(minimum_delay, maximum_delay)
        # A literal newline reaches the composer as a plain Enter key press, which
        # submits the prompt and splits a multi-line question into one message per
        # line; the soft-break shortcut keeps the whole prompt in a single message.
        if character == "\n":
            await editor.press(LINE_BREAK_SHORTCUT, delay=delay)
            continue
        await editor.press_sequentially(character, delay=delay)


async def _keep_page_active(page) -> None:
    scroll_deferred = False
    while True:
        await asyncio.sleep(
            random.uniform(
                KEEPALIVE_SCROLL_MIN_INTERVAL_SECONDS,
                KEEPALIVE_SCROLL_MAX_INTERVAL_SECONDS,
            )
        )
        if not scroll_deferred and random.random() < KEEPALIVE_SCROLL_SKIP_CHANCE:
            scroll_deferred = True
            continue
        scroll_deferred = False
        distance = random.randint(
            KEEPALIVE_SCROLL_MIN_DISTANCE,
            KEEPALIVE_SCROLL_MAX_DISTANCE,
        )
        try:
            await page.mouse.wheel(0, -distance)
            await asyncio.sleep(
                random.uniform(
                    KEEPALIVE_SCROLL_MIN_RETURN_DELAY_SECONDS,
                    KEEPALIVE_SCROLL_MAX_RETURN_DELAY_SECONDS,
                )
            )
            await page.mouse.wheel(0, distance)
        except Exception:
            return


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


async def _extract_sources(page, response) -> list[ChatGPTSource]:
    sources: list[ChatGPTSource] = []
    pills = response.locator(CITATION_PILL_SELECTOR)
    for index in range(await pills.count()):
        pill = pills.nth(index)
        direct_links = pill.locator("a[href]")
        if await direct_links.count():
            direct_link = direct_links.first
            direct_source = _source_from_link(
                await direct_link.get_attribute("href"), await direct_link.inner_text()
            )
            if direct_source is not None:
                sources.append(direct_source)

        await pill.hover(force=True, timeout=5_000)
        await page.wait_for_timeout(750)
        popovers = page.locator(SOURCE_POPOVER_SELECTOR)
        if not await popovers.count():
            continue
        popover = popovers.first
        counter = re.search(r"\b\d+/(\d+)\b", await popover.inner_text())
        source_count = int(counter.group(1)) if counter else 1
        for source_index in range(source_count):
            links = popover.locator("a[href]")
            if not await links.count():
                break
            link = links.first
            source = _source_from_link(
                await link.get_attribute("href"), await link.inner_text()
            )
            if source is not None:
                sources.append(source)
            if source_index + 1 < source_count:
                buttons = popover.locator("button")
                if await buttons.count() < 2:
                    break
                await buttons.nth(1).click(force=True, timeout=5_000)
                await page.wait_for_timeout(300)
        await page.keyboard.press("Escape")
    return sources


async def _extract_response(page) -> str:
    response = page.locator(ASSISTANT_MESSAGE_SELECTOR).last
    markdown = await response.evaluate(RENDER_MARKDOWN_SCRIPT)
    return _format_response(markdown, await _extract_sources(page, response))


class ResponseStalledError(Exception):
    """ChatGPT showed no progress for the whole stall window."""


def _raise_if_stalled(progressed_at: float, stall_seconds: float | None) -> None:
    if stall_seconds is None:
        return
    if time.monotonic() - progressed_at < stall_seconds:
        return
    raise ResponseStalledError(_stall_message(stall_seconds))


def _first_response_timeout_ms(stall_seconds: float | None) -> float:
    # Playwright reads 0 as "no timeout", which is what unlimited waiting means.
    if stall_seconds is None:
        return 0
    return stall_seconds * MILLISECONDS_PER_SECOND


def _stall_message(stall_seconds: float) -> str:
    return (
        f"ChatGPT showed no progress for {stall_seconds:g}s; the prompt was sent "
        f"but completion could not be confirmed "
        f"(raise or disable this with {RESPONSE_STALL_ENV_VAR})"
    )


async def _wait_for_first_response(
    page,
    previous_count: int,
    stall_seconds: float | None,
) -> None:
    try:
        await page.wait_for_function(
            """previousCount =>
            document.querySelectorAll('[data-message-author-role="assistant"]').length
            > previousCount""",
            arg=previous_count,
            timeout=_first_response_timeout_ms(stall_seconds),
        )
    except PlaywrightTimeoutError as error:
        # Unlimited waiting passes timeout=0, so Playwright only times out when a
        # window is configured. An assistant turn that never appears is the same
        # inert page as one that stops growing, so report it the same way.
        raise ResponseStalledError(_stall_message(stall_seconds)) from error


async def _wait_for_reply(
    page,
    previous_count: int,
    status_callback: StatusCallback | None,
    stall_seconds: float | None,
) -> str:
    keepalive_task = asyncio.create_task(_keep_page_active(page))
    try:
        await _wait_for_first_response(page, previous_count, stall_seconds)
        _emit_status(status_callback, "ChatGPT is responding...")
        response = page.locator(ASSISTANT_MESSAGE_SELECTOR).last
        turn_id = await response.evaluate(TURN_ID_SCRIPT)
        previous_status = None
        previous_progress = None
        progressed_at = time.monotonic()
        while True:
            state = await page.evaluate(
                RESPONSE_STATE_SCRIPT,
                {"previousCount": previous_count, "turnId": turn_id},
            )
            current_status = state["status"]
            if current_status and current_status != previous_status:
                _emit_status(status_callback, f"ChatGPT activity: {current_status}")
            # Growing text or a changed activity label both mean ChatGPT is still
            # working, so only a completely inert page runs the stall window down.
            current_progress = (current_status, state.get("progress"))
            if current_progress != previous_progress:
                previous_progress = current_progress
                progressed_at = time.monotonic()
            previous_status = current_status
            if state["complete"]:
                break
            _raise_if_stalled(progressed_at, stall_seconds)
            await page.wait_for_timeout(250)
    finally:
        keepalive_task.cancel()
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass
    _emit_status(status_callback, "Collecting response and sources...")
    return await _extract_response(page)


async def _open_configuration_menu(page):
    trigger = page.locator(REASONING_TRIGGER_SELECTOR)
    await trigger.wait_for(state="visible", timeout=10_000)
    await trigger.click()

    root_menu = page.locator('[role="menu"]:visible').first
    await root_menu.wait_for(state="visible", timeout=10_000)
    advanced_view = root_menu.locator(ADVANCED_VIEW_SELECTOR)
    if await advanced_view.count():
        await advanced_view.click()
    return trigger, root_menu


async def _reasoning_index_from_control(control) -> int | None:
    value = await control.get_attribute("aria-valuenow")
    minimum = await control.get_attribute("aria-valuemin")
    if value is not None:
        try:
            index = round(float(value) - float(minimum or 0))
        except ValueError:
            pass
        else:
            if index in REASONING_LEVEL_INDEXES.values():
                return index

    position = await control.get_attribute("aria-posinset")
    if position is not None:
        try:
            index = int(position) - 1
        except ValueError:
            pass
        else:
            if index in REASONING_LEVEL_INDEXES.values():
                return index
    return None


async def _inline_reasoning_control(menu):
    controls = menu.locator(INLINE_REASONING_SELECTOR)
    if await controls.count() != 1:
        return None
    return controls.first


async def _selected_model_from_menu(menu) -> str | None:
    options = menu.locator(REASONING_OPTION_SELECTOR)
    for label in MODEL_LABELS.values():
        matches = options.filter(has_text=label)
        for index in range(await matches.count()):
            option = matches.nth(index)
            if (
                await option.get_attribute("aria-checked") == "true"
                or await option.get_attribute("data-state") == "checked"
                or await option.get_attribute("aria-current") == "true"
            ):
                return label
    return None


async def _close_advanced_menus(page) -> None:
    await page.keyboard.press("Escape")
    await page.keyboard.press("Escape")


async def _read_page_status(page) -> ChatGPTPageStatus:
    trigger = page.locator(REASONING_TRIGGER_SELECTOR)
    await trigger.wait_for(state="visible", timeout=10_000)
    if await trigger.count() != 1:
        return ChatGPTPageStatus(page.url, "unknown", "unknown")
    reasoning_text = (await trigger.inner_text()).strip()
    reasoning = next(
        (
            level.value
            for level, label in REASONING_LABELS.items()
            if label in reasoning_text
        ),
        reasoning_text,
    )
    await trigger.click()
    try:
        root_menu = page.locator('[role="menu"]:visible').first
        await root_menu.wait_for(state="visible", timeout=10_000)
        inline_reasoning = await _inline_reasoning_control(root_menu)
        if inline_reasoning is not None:
            reasoning_index = await _reasoning_index_from_control(inline_reasoning)
            if reasoning_index is not None:
                reasoning = list(ReasoningLevel)[reasoning_index].value

        selected_model = await _selected_model_from_menu(root_menu)
        if selected_model is not None:
            return ChatGPTPageStatus(page.url, selected_model, reasoning)

        submenu_items = root_menu.locator(REASONING_SUBMENU_ITEM_SELECTOR)
        if await submenu_items.count() < 2:
            return ChatGPTPageStatus(page.url, "unknown", reasoning)

        model_text = " ".join((await submenu_items.nth(0).inner_text()).split())
        model = next(
            (label for label in MODEL_LABELS.values() if label in model_text),
            model_text,
        )
        return ChatGPTPageStatus(page.url, model, reasoning)
    finally:
        await page.keyboard.press("Escape")


class ChatGPTDOMChangedError(RuntimeError):
    """ChatGPT's model/reasoning controls cannot be identified safely."""


def _unknown_status_message(status: ChatGPTPageStatus) -> str:
    return (
        "ChatGPT's model/reasoning controls could not be identified; the "
        "ChatGPT UI or DOM may have changed. No message was sent. "
        f"Detected model={status.model!r}, reasoning={status.reasoning!r}. "
        "Update CloakGPT and retry; if it is already up to date, report the "
        "current model/reasoning menu DOM."
    )


async def _read_page_status_required(page) -> ChatGPTPageStatus:
    try:
        status = await _read_page_status(page)
    except Exception as exc:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        status = ChatGPTPageStatus(page.url, "unknown", "unknown")
        raise ChatGPTDOMChangedError(_unknown_status_message(status)) from exc

    known_models = set(MODEL_LABELS.values())
    known_reasoning = {level.value for level in ReasoningLevel}
    if status.model not in known_models or status.reasoning not in known_reasoning:
        raise ChatGPTDOMChangedError(_unknown_status_message(status))
    return status


async def _set_model(page, model: ChatGPTModel) -> None:
    label = MODEL_LABELS[model]
    _, root_menu = await _open_configuration_menu(page)
    inline_options = root_menu.locator(REASONING_OPTION_SELECTOR)
    inline_matches = inline_options.filter(has_text=label)
    if await inline_matches.count() == 1:
        option = inline_matches.first
        if await option.get_attribute("aria-checked") == "true":
            await _close_advanced_menus(page)
            return
        await option.click()
        return

    submenu_items = root_menu.locator(REASONING_SUBMENU_ITEM_SELECTOR)
    if await submenu_items.count() < 1:
        available = " ".join((await root_menu.inner_text()).split())
        raise ValueError(f"model {label!r} is unavailable; menu: {available}")
    await submenu_items.nth(0).click()
    model_menu = page.locator('[role="menu"]:visible').last
    options = model_menu.locator(REASONING_OPTION_SELECTOR)
    matches = options.filter(has_text=label)
    if await matches.count() != 1:
        available = " ".join((await model_menu.inner_text()).split())
        raise ValueError(f"model {label!r} is unavailable; menu: {available}")

    option = matches.first
    if await option.get_attribute("aria-checked") == "true":
        await _close_advanced_menus(page)
        return
    await option.click()


async def _set_reasoning_level(page, reasoning_level: ReasoningLevel) -> None:
    option_index = REASONING_LEVEL_INDEXES[reasoning_level]
    trigger, root_menu = await _open_configuration_menu(page)
    inline_reasoning = await _inline_reasoning_control(root_menu)
    if inline_reasoning is not None:
        current_index = await _reasoning_index_from_control(inline_reasoning)
        if current_index == option_index:
            await _close_advanced_menus(page)
            return
        for _ in REASONING_LEVEL_INDEXES:
            await inline_reasoning.press("ArrowLeft")
        for _ in range(option_index):
            await inline_reasoning.press("ArrowRight")
        for _ in range(50):
            if await _reasoning_index_from_control(inline_reasoning) == option_index:
                await _close_advanced_menus(page)
                return
            await page.wait_for_timeout(100)
        raise RuntimeError("ChatGPT did not apply the selected reasoning level")

    submenu_items = root_menu.locator(REASONING_SUBMENU_ITEM_SELECTOR)
    if await submenu_items.count() < 2:
        available = " ".join((await root_menu.inner_text()).split())
        raise ValueError(f"reasoning menu is unavailable; menu: {available}")
    await submenu_items.nth(1).click()
    reasoning_menu = page.locator('[role="menu"]:visible').last
    options = reasoning_menu.locator(REASONING_OPTION_SELECTOR)
    if await options.count() <= option_index:
        available = " ".join((await reasoning_menu.inner_text()).split())
        raise ValueError(
            f"reasoning level {reasoning_level!r} is unavailable; menu: {available}"
        )

    option = options.nth(option_index)
    selected_label = (await option.inner_text()).strip()
    if await option.get_attribute("aria-checked") == "true":
        await _close_advanced_menus(page)
        return

    await option.click()
    for _ in range(50):
        if (await trigger.inner_text()).strip() == selected_label:
            return
        await page.wait_for_timeout(100)
    raise RuntimeError("ChatGPT did not apply the selected reasoning level")


class DeliveryStateUnknownError(RuntimeError):
    """The prompt was clicked, but completion could not be confirmed."""


async def send_message_on_page(
    page,
    url: str,
    question: str,
    model: ChatGPTModel | None,
    reasoning_level: ReasoningLevel | None,
    status_callback: StatusCallback | None,
    *,
    reuse_page: bool = False,
    composer_lock=None,
) -> tuple[str, str]:
    _validate_question(question)

    _emit_status(status_callback, "Opening ChatGPT...")
    if not reuse_page or page.url != url:
        await page.goto(url, wait_until="domcontentloaded")

    async with composer_lock or _without_composer_lock():
        editor = page.locator(PROMPT_EDITOR_SELECTOR)
        await editor.wait_for(state="visible", timeout=30_000)

        if model is not None:
            _emit_status(status_callback, f"Selecting model: {model}")
            await _set_model(page, model)
        if reasoning_level is not None:
            _emit_status(status_callback, f"Selecting reasoning: {reasoning_level}")
            await _set_reasoning_level(page, reasoning_level)

        status = await _read_page_status_required(page)
        _emit_status(
            status_callback,
            f"Current page: model={status.model}, reasoning={status.reasoning}, url={status.url}",
        )

        previous_count = await page.locator(ASSISTANT_MESSAGE_SELECTOR).count()
        _emit_status(status_callback, "Typing message...")
        await _type_question_like_human(editor, question)

        send_button = page.locator(SEND_BUTTON_SELECTOR)
        await send_button.wait_for(state="visible", timeout=10_000)
        _emit_status(status_callback, "Sending message...")
        await send_button.click()

    stall_seconds = response_stall_seconds()
    try:
        _emit_status(status_callback, "Waiting for ChatGPT response (Ctrl+C to stop)...")
        answer = await _wait_for_reply(
            page,
            previous_count,
            status_callback,
            stall_seconds,
        )
        _emit_status(status_callback, "Response complete.")
        return answer, page.url
    except ResponseStalledError as error:
        raise DeliveryStateUnknownError(str(error)) from error
    except Exception as error:
        raise DeliveryStateUnknownError(
            "delivery state unknown; the prompt was sent but completion could not be confirmed"
        ) from error


async def _send_message(
    url: str,
    question: str,
    timezone: str,
    profile_dir: Path,
    headless: bool,
    model: ChatGPTModel | None,
    reasoning_level: ReasoningLevel | None,
    status_callback: StatusCallback | None,
) -> tuple[str, str]:
    context = await launch_chatgpt_context_async(
        profile_dir,
        headless=headless,
        timezone=timezone,
    )
    try:
        page = await context.new_page()
        return await send_message_on_page(
            page,
            url,
            question,
            model,
            reasoning_level,
            status_callback,
        )
    finally:
        await context.close()


def start_conversation(
    question: str,
    *,
    timezone: str = "Asia/Taipei",
    headless: bool = True,
    model: ChatGPTModel | None = None,
    reasoning_level: ReasoningLevel | None = None,
    status_callback: StatusCallback | None = None,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
) -> str:
    """Start a new ChatGPT conversation and return the response text."""
    answer, _ = asyncio.run(
        _send_message(
            CHATGPT_URL,
            question,
            timezone,
            profile_dir,
            headless,
            model,
            reasoning_level,
            status_callback,
        )
    )
    return answer
