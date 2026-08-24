import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import chatgpt_browser


class ChatGPTBrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "conversation-url"
        self.profile_dir = Path(self.temp_dir.name) / "profile"

        self.editor = Mock()
        self.send_button = Mock()
        self.reasoning_trigger = Mock()
        self.root_menu = Mock()
        self.root_menu.first = self.root_menu
        self.advanced_view = Mock()
        self.advanced_view.count.return_value = 1
        self.model_item = Mock()
        self.model_item.inner_text.return_value = "模型 GPT-5.6 Sol"
        self.reasoning_item = Mock()
        self.submenu_items = Mock()
        self.submenu_items.count.return_value = 2
        self.submenu_items.nth.side_effect = (
            lambda index: [self.model_item, self.reasoning_item][index]
        )
        self.submenu_items.last = self.reasoning_item
        self.root_menu.locator.side_effect = {
            chatgpt_browser.ADVANCED_VIEW_SELECTOR: self.advanced_view,
            chatgpt_browser.REASONING_SUBMENU_ITEM_SELECTOR: self.submenu_items,
        }.get

        self.reasoning_menu = Mock()
        self.reasoning_menu.last = self.reasoning_menu
        self.reasoning_option = Mock()
        self.reasoning_option.inner_text.return_value = "高い"
        self.reasoning_options = Mock()
        self.reasoning_options.count.return_value = 3
        self.reasoning_options.nth.return_value = self.reasoning_option
        self.model_option = Mock()
        self.model_match = Mock()
        self.model_match.count.return_value = 1
        self.model_match.first = self.model_option
        self.reasoning_options.filter.return_value = self.model_match
        self.reasoning_menu.locator.return_value = self.reasoning_options
        self.responses = Mock()
        self.responses.count.return_value = 0
        self.responses.last.inner_text.return_value = "OK."
        self.responses.last.evaluate.side_effect = lambda script: (
            "conversation-turn-2"
            if script == chatgpt_browser.TURN_ID_SCRIPT
            else "OK."
        )
        self.citation_pills = Mock()
        self.citation_pills.count.return_value = 0
        self.responses.last.locator.return_value = self.citation_pills

        self.page = Mock()
        self.page.url = "https://chatgpt.com/c/test-conversation"
        locator_results = {
            chatgpt_browser.PROMPT_EDITOR_SELECTOR: self.editor,
            chatgpt_browser.SEND_BUTTON_SELECTOR: self.send_button,
            chatgpt_browser.ASSISTANT_MESSAGE_SELECTOR: self.responses,
            chatgpt_browser.REASONING_TRIGGER_SELECTOR: self.reasoning_trigger,
        }
        visible_menus = Mock()
        visible_menus.first = self.root_menu
        visible_menus.last = self.reasoning_menu

        def locate(selector):
            if selector == '[role="menu"]:visible':
                return visible_menus
            return locator_results.get(selector)

        self.page.locator.side_effect = locate
        self.page.evaluate.return_value = {"complete": True, "status": None}
        self.reasoning_trigger.inner_text.return_value = "高い"

        self.context = Mock()
        self.context.new_page.return_value = self.page
        self.launch_patch = patch(
            "chatgpt_browser.launch_persistent_context",
            return_value=self.context,
        )
        self.launch_patch.start()

    def tearDown(self) -> None:
        self.launch_patch.stop()
        self.temp_dir.cleanup()

    def test_start_and_continue_conversation(self) -> None:
        first_answer = chatgpt_browser.start_conversation(
            "First",
            profile_dir=self.profile_dir,
            state_file=self.state_file,
        )
        second_answer = chatgpt_browser.continue_conversation(
            "Second",
            profile_dir=self.profile_dir,
            state_file=self.state_file,
        )

        self.assertEqual(first_answer, "OK.")
        self.assertEqual(second_answer, "OK.")
        self.assertEqual(
            self.state_file.read_text(encoding="utf-8"),
            "https://chatgpt.com/c/test-conversation",
        )
        self.assertEqual(
            self.page.goto.call_args_list[1].args[0],
            "https://chatgpt.com/c/test-conversation",
        )
        self.editor.fill.assert_any_call("First")
        self.editor.fill.assert_any_call("Second")
        self.assertEqual(self.send_button.click.call_count, 2)
        self.model_option.click.assert_not_called()
        self.reasoning_option.click.assert_not_called()

    def test_selects_requested_model(self) -> None:
        chatgpt_browser.start_conversation(
            "Hello",
            model=chatgpt_browser.ChatGPTModel.GPT_5_5,
            profile_dir=self.profile_dir,
            state_file=self.state_file,
        )

        self.model_item.click.assert_called_once_with()
        self.reasoning_options.filter.assert_called_once_with(has_text="GPT-5.5")
        self.model_option.click.assert_called_once_with()

    def test_selects_requested_reasoning_level(self) -> None:
        chatgpt_browser.start_conversation(
            "Think",
            reasoning_level=chatgpt_browser.ReasoningLevel.HIGH,
            profile_dir=self.profile_dir,
            state_file=self.state_file,
        )

        self.assertEqual(self.reasoning_trigger.click.call_count, 2)
        self.advanced_view.click.assert_called_once_with()
        self.reasoning_item.click.assert_called_once_with()
        self.reasoning_options.nth.assert_called_once_with(2)
        self.reasoning_option.click.assert_called_once_with()

    def test_reports_unavailable_reasoning_level(self) -> None:
        self.submenu_items.count.return_value = 0
        self.root_menu.inner_text.return_value = "Log in to configure reasoning"

        with self.assertRaisesRegex(ValueError, "Log in to configure reasoning"):
            chatgpt_browser.start_conversation(
                "Think",
                reasoning_level=chatgpt_browser.ReasoningLevel.HIGH,
                profile_dir=self.profile_dir,
                state_file=self.state_file,
            )

    def test_keeps_reasoning_level_when_already_selected(self) -> None:
        self.reasoning_option.get_attribute.return_value = "true"

        chatgpt_browser.start_conversation(
            "Think",
            reasoning_level=chatgpt_browser.ReasoningLevel.HIGH,
            profile_dir=self.profile_dir,
            state_file=self.state_file,
        )

        self.reasoning_option.click.assert_not_called()
        self.assertGreaterEqual(self.page.keyboard.press.call_count, 2)
        self.page.keyboard.press.assert_called_with("Escape")

    def test_reports_page_and_response_status_without_response_timeout(self) -> None:
        status_callback = Mock()

        chatgpt_browser.start_conversation(
            "Hello",
            status_callback=status_callback,
            profile_dir=self.profile_dir,
            state_file=self.state_file,
        )

        status_callback.assert_any_call("Opening ChatGPT...")
        status_callback.assert_any_call(
            "Current page: model=GPT-5.6 Sol, reasoning=high, "
            "url=https://chatgpt.com/c/test-conversation"
        )
        status_callback.assert_any_call(
            "Waiting for ChatGPT response (Ctrl+C to stop)..."
        )
        status_callback.assert_any_call("ChatGPT is responding...")
        status_callback.assert_any_call("Collecting response and sources...")
        status_callback.assert_any_call("Response complete.")
        for call in self.page.wait_for_function.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 0)
        completion_predicate = chatgpt_browser.RESPONSE_STATE_SCRIPT
        self.assertIn('data-testid="stop-button"', completion_predicate)
        self.assertIn("request-placeholder-", completion_predicate)
        self.assertIn('aria-busy="true"', completion_predicate)
        self.assertIn("streaming-animation", completion_predicate)
        self.assertIn("ariaLabel.endsWith('中')", completion_predicate)

    def test_reports_native_chatgpt_activity_changes(self) -> None:
        status_callback = Mock()
        self.page.evaluate.side_effect = [
            {"complete": False, "status": "ウェブを検索中"},
            {"complete": False, "status": "2件のサイトを検索中"},
            {"complete": False, "status": "13s考えました"},
            {"complete": True, "status": "13s考えました"},
        ]

        chatgpt_browser.start_conversation(
            "Search",
            status_callback=status_callback,
            profile_dir=self.profile_dir,
            state_file=self.state_file,
        )

        status_callback.assert_any_call("ChatGPT activity: ウェブを検索中")
        status_callback.assert_any_call("ChatGPT activity: 2件のサイトを検索中")
        status_callback.assert_any_call("ChatGPT activity: 13s考えました")
        self.assertEqual(self.page.wait_for_timeout.call_count, 3)

    def test_rejects_invalid_saved_url(self) -> None:
        self.state_file.write_text("https://example.com/c/test", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "invalid ChatGPT conversation URL"):
            chatgpt_browser.continue_conversation(
                "Hello",
                profile_dir=self.profile_dir,
                state_file=self.state_file,
            )

    def test_formats_sources_as_markdown_and_deduplicates_urls(self) -> None:
        response = chatgpt_browser._format_response(
            "## Answer\n\nIt is rainy.",
            [
                chatgpt_browser.ChatGPTSource(
                    "example.com",
                    "https://example.com/weather",
                ),
                chatgpt_browser.ChatGPTSource(
                    "Weather [forecast]",
                    "https://example.com/weather",
                ),
                chatgpt_browser.ChatGPTSource(
                    "Second source",
                    "https://second.example/report",
                ),
            ],
        )

        self.assertEqual(
            response,
            "## Answer\n\nIt is rainy.\n\n## Sources\n\n"
            "1. [Weather \\[forecast\\]](https://example.com/weather)\n"
            "2. [Second source](https://second.example/report)",
        )

    def test_source_parser_removes_chatgpt_tracking_parameter(self) -> None:
        source = chatgpt_browser._source_from_link(
            "https://example.com/weather?id=1&utm_source=chatgpt.com#today",
            "example.com\nWeather forecast\nToday",
        )

        self.assertEqual(
            source,
            chatgpt_browser.ChatGPTSource(
                title="Weather forecast",
                url="https://example.com/weather?id=1#today",
            ),
        )

    def test_extracts_direct_source_when_popover_is_unavailable(self) -> None:
        response = Mock()
        pills = Mock()
        pills.count.return_value = 1
        pill = pills.nth.return_value
        direct_links = pill.locator.return_value
        direct_links.count.return_value = 1
        direct_link = direct_links.first
        direct_link.get_attribute.return_value = (
            "https://example.com/report?utm_source=chatgpt.com"
        )
        direct_link.inner_text.return_value = "example.com"
        response.locator.return_value = pills

        page = Mock()
        page.locator.return_value.count.return_value = 0

        sources = chatgpt_browser._extract_sources(page, response)

        self.assertEqual(
            sources,
            [
                chatgpt_browser.ChatGPTSource(
                    title="example.com",
                    url="https://example.com/report",
                )
            ],
        )
        pill.hover.assert_called_once_with(force=True, timeout=5_000)
        page.wait_for_timeout.assert_called_once_with(750)

    def test_extracts_all_sources_from_citation_carousel(self) -> None:
        response = Mock()
        pills = Mock()
        pills.count.return_value = 1
        pill = pills.nth.return_value
        pill.locator.return_value.count.return_value = 0
        response.locator.return_value = pills

        page = Mock()
        popovers = page.locator.return_value
        popovers.count.return_value = 1
        popover = popovers.first
        popover.inner_text.return_value = "1/2"
        links = Mock()
        links.count.return_value = 1
        link = links.first
        link.get_attribute.side_effect = [
            "https://first.example/report",
            "https://second.example/report",
        ]
        link.inner_text.side_effect = [
            "first.example\nFirst report",
            "second.example\nSecond report",
        ]
        buttons = Mock()
        buttons.count.return_value = 2
        popover.locator.side_effect = {
            "a[href]": links,
            "button": buttons,
        }.get

        sources = chatgpt_browser._extract_sources(page, response)

        self.assertEqual(
            sources,
            [
                chatgpt_browser.ChatGPTSource(
                    title="First report",
                    url="https://first.example/report",
                ),
                chatgpt_browser.ChatGPTSource(
                    title="Second report",
                    url="https://second.example/report",
                ),
            ],
        )
        buttons.nth.assert_called_once_with(1)
        buttons.nth.return_value.click.assert_called_once_with(
            force=True,
            timeout=5_000,
        )


if __name__ == "__main__":
    unittest.main()
