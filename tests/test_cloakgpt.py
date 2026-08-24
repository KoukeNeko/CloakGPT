import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import cloakgpt


class CloakGPTCliTests(unittest.TestCase):
    @patch("cloakgpt.cloakbrowser_main")
    def test_browser_command_delegates_to_cloakbrowser_cli(
        self,
        cloakbrowser_main,
    ) -> None:
        delegated_argv = []
        cloakbrowser_main.side_effect = lambda: delegated_argv.extend(cloakgpt.sys.argv)

        with patch.object(cloakgpt.sys, "argv", ["original-command"]):
            result = cloakgpt.main(["browser", "info", "--quick"])

            self.assertEqual(cloakgpt.sys.argv, ["original-command"])

        self.assertEqual(result, 0)
        self.assertEqual(delegated_argv, ["cloakbrowser", "info", "--quick"])
        cloakbrowser_main.assert_called_once_with()

    @patch("cloakgpt.cloakbrowser_main", side_effect=SystemExit(2))
    def test_browser_command_returns_cloakbrowser_exit_code(
        self,
        _cloakbrowser_main,
    ) -> None:
        result = cloakgpt.main(["browser"])

        self.assertEqual(result, 2)

    @patch("builtins.input", return_value="")
    @patch("cloakgpt.launch_persistent_context")
    def test_login_command(self, launch_persistent_context, user_input) -> None:
        context = Mock()
        launch_persistent_context.return_value = context

        result = cloakgpt.main(["login", "--timezone", "Asia/Taipei"])

        self.assertEqual(result, 0)
        launch_persistent_context.assert_called_once_with(
            str(cloakgpt.DEFAULT_PROFILE_DIR),
            headless=False,
            locale="ja-JP",
            timezone="Asia/Taipei",
        )
        context.new_page.return_value.goto.assert_called_once_with(
            cloakgpt.CHATGPT_URL,
            wait_until="domcontentloaded",
        )
        user_input.assert_called_once()
        context.close.assert_called_once_with()

    @patch("cloakgpt.start_conversation", return_value="First answer")
    def test_ask_command(self, start_conversation) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = cloakgpt.main(
                [
                    "ask",
                    "Hello",
                    "--model",
                    "gpt-5.5",
                    "--reasoning",
                    "high",
                    "--timezone",
                    "Asia/Taipei",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "First answer")
        start_conversation.assert_called_once_with(
            "Hello",
            timezone="Asia/Taipei",
            model=cloakgpt.ChatGPTModel.GPT_5_5,
            reasoning_level=cloakgpt.ReasoningLevel.HIGH,
            status_callback=cloakgpt.show_status,
        )

    @patch("cloakgpt.continue_conversation", return_value="Next answer")
    def test_continue_command(self, continue_conversation) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = cloakgpt.main(["continue", "More details"])

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "Next answer")
        continue_conversation.assert_called_once_with(
            "More details",
            timezone="Asia/Taipei",
            model=None,
            reasoning_level=None,
            status_callback=cloakgpt.show_status,
        )

    @patch("cloakgpt.start_conversation")
    def test_status_is_printed_to_stderr_only(self, start_conversation) -> None:
        def run(_question, **options):
            options["status_callback"]("Waiting for ChatGPT response...")
            return "Answer"

        start_conversation.side_effect = run
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello"])

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "Answer")
        self.assertEqual(
            errors.getvalue().strip(),
            "[status] Waiting for ChatGPT response...",
        )

    @patch("cloakgpt.start_conversation", side_effect=ValueError("not available"))
    def test_errors_are_reported_without_traceback(self, _start_conversation) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello"])

        self.assertEqual(result, 1)
        self.assertEqual(errors.getvalue().strip(), "error: not available")

    @patch("cloakgpt.start_conversation", side_effect=KeyboardInterrupt)
    def test_ctrl_c_stops_without_traceback(self, _start_conversation) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello"])

        self.assertEqual(result, 130)
        self.assertEqual(errors.getvalue().strip(), "stopped")


if __name__ == "__main__":
    unittest.main()
