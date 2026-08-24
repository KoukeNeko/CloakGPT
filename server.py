"""A minimal Model Context Protocol (MCP) server using FastMCP."""

from time import monotonic
from urllib.parse import urlparse

from cloakbrowser import launch, launch_persistent_context
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("example-python-mcp")
CHATGPT_PROFILE_DIR = "chatgpt-profile"
ASSISTANT_MESSAGE_SELECTOR = '[data-message-author-role="assistant"]'


@mcp.tool()
def greet(name: str) -> str:
    """Return a friendly greeting for the supplied name."""
    return f"Hello, {name}!"


@mcp.tool()
def add(first: float, second: float) -> float:
    """Add two numbers."""
    return first + second


@mcp.tool()
def get_page_title(url: str, timezone: str) -> str:
    """Get a public page title using the user's IANA timezone.

    The caller must have permission to access the supplied URL. For example,
    use ``Asia/Taipei`` for a user in Taiwan.
    """
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("url must be an absolute http or https URL")

    browser = launch(timezone=timezone)
    try:
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        return page.title()
    finally:
        browser.close()


@mcp.tool()
def ask_chatgpt(question: str, timezone: str) -> str:
    """Send a question to ChatGPT and return its text response.

    Requires a user-signed-in ChatGPT session in the persistent local profile.
    This tool sends the provided question to chatgpt.com.
    """
    if not question.strip():
        raise ValueError("question must not be empty")

    context = launch_persistent_context(
        CHATGPT_PROFILE_DIR,
        headless=False,
        locale="ja-JP",
        timezone=timezone,
    )
    try:
        page = context.new_page()
        page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
        question_box = page.get_by_placeholder("質問してみましょう")
        question_box.wait_for(timeout=10_000)
        previous_count = page.locator(ASSISTANT_MESSAGE_SELECTOR).count()
        question_box.fill(question)
        question_box.press("Enter")
        page.wait_for_function(
            """previousCount =>
            document.querySelectorAll('[data-message-author-role="assistant"]').length
            > previousCount""",
            arg=previous_count,
            timeout=120_000,
        )

        response = page.locator(ASSISTANT_MESSAGE_SELECTOR).last
        deadline = monotonic() + 120
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
    finally:
        context.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
