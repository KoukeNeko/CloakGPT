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
        self.responses = Mock()
        self.responses.count.return_value = 0
        self.responses.last.inner_text.return_value = "OK."

        self.page = Mock()
        self.page.url = "https://chatgpt.com/c/test-conversation"
        self.page.locator.side_effect = {
            chatgpt_browser.PROMPT_EDITOR_SELECTOR: self.editor,
            chatgpt_browser.SEND_BUTTON_SELECTOR: self.send_button,
            chatgpt_browser.ASSISTANT_MESSAGE_SELECTOR: self.responses,
        }.get

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
