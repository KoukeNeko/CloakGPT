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
        status_callback.assert_any_call("Response complete.")
        for call in self.page.wait_for_function.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 0)
        completion_predicate = self.page.wait_for_function.call_args_list[1].args[0]
        self.assertIn('data-testid="stop-button"', completion_predicate)
        self.assertIn("request-placeholder-", completion_predicate)
        self.assertIn('aria-busy="true"', completion_predicate)
        self.assertIn("streaming-animation", completion_predicate)

    def test_rejects_invalid_saved_url(self) -> None:
        self.state_file.write_text("https://example.com/c/test", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "invalid ChatGPT conversation URL"):
            chatgpt_browser.continue_conversation(
                "Hello",
                profile_dir=self.profile_dir,
                state_file=self.state_file,
            )


if __name__ == "__main__":
    unittest.main()
