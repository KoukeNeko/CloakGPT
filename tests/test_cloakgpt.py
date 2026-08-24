import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import cloakgpt


class CloakGPTCliTests(unittest.TestCase):
    def test_windows_stdio_uses_utf8(self) -> None:
        stdin = Mock()
        stdout = Mock()
        stderr = Mock()

        with (
            patch.object(cloakgpt.os, "name", "nt"),
            patch.object(cloakgpt.sys, "stdin", stdin),
            patch.object(cloakgpt.sys, "stdout", stdout),
            patch.object(cloakgpt.sys, "stderr", stderr),
            patch.object(cloakgpt.ctypes, "WinDLL", create=True) as win_dll,
        ):
            cloakgpt._configure_windows_utf8_stdio()

        win_dll.assert_called_once_with("kernel32", use_last_error=True)
        win_dll.return_value.SetConsoleCP.assert_called_once_with(65001)
        win_dll.return_value.SetConsoleOutputCP.assert_called_once_with(65001)
        for stream in (stdin, stdout, stderr):
            stream.reconfigure.assert_called_once_with(
                encoding="utf-8",
                errors="strict",
            )

    @patch("cloakgpt.subprocess.run")
    @patch("cloakgpt.compute_driver_executable", return_value=("node", "cli.js"))
    def test_hidden_playwright_check_starts_driver(
        self,
        _compute_driver_executable,
        run,
    ) -> None:
        result = cloakgpt.main(["_playwright_check"])

        self.assertEqual(result, 0)
        run.assert_called_once_with(
            ["node", "cli.js", "run-driver"],
            stdin=cloakgpt.subprocess.DEVNULL,
            check=True,
        )

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
        login_page = Mock()
        login_page.url = "about:blank"
        extra_blank_page = Mock()
        extra_blank_page.url = "about:blank"
        existing_page = Mock()
        existing_page.url = "https://example.com/"
        context.pages = [login_page, extra_blank_page, existing_page]
        launch_persistent_context.return_value = context

        result = cloakgpt.main(["login", "--timezone", "Asia/Taipei"])

        self.assertEqual(result, 0)
        launch_persistent_context.assert_called_once_with(
            str(cloakgpt.DEFAULT_PROFILE_DIR),
            headless=False,
            locale="ja-JP",
            timezone="Asia/Taipei",
        )
        context.new_page.assert_not_called()
        login_page.goto.assert_called_once_with(
            cloakgpt.CHATGPT_URL,
            wait_until="domcontentloaded",
        )
        extra_blank_page.close.assert_called_once_with()
        existing_page.close.assert_not_called()
        user_input.assert_called_once()
        context.close.assert_called_once_with()

    @patch("builtins.input", return_value="")
    @patch("cloakgpt.launch_persistent_context")
    def test_login_creates_page_when_context_has_none(
        self,
        launch_persistent_context,
        _user_input,
    ) -> None:
        context = Mock()
        context.pages = []
        launch_persistent_context.return_value = context

        result = cloakgpt.main(["login"])

        self.assertEqual(result, 0)
        context.new_page.assert_called_once_with()
        context.new_page.return_value.goto.assert_called_once_with(
            cloakgpt.CHATGPT_URL,
            wait_until="domcontentloaded",
        )

    @patch("cloakgpt.launch_persistent_context")
    def test_login_reports_existing_profile_without_browser_log(
        self,
        launch_persistent_context,
    ) -> None:
        launch_persistent_context.side_effect = RuntimeError(
            "Target page, context or browser has been closed\n"
            "[out] 既存のブラウザ セッションで開いています。\n"
            "Browser logs: noisy details"
        )
        errors = io.StringIO()

        with redirect_stderr(errors):
            result = cloakgpt.main(["login"])

        self.assertEqual(result, 1)
        self.assertEqual(
            errors.getvalue().strip(),
            "error: the CloakGPT browser profile is already open. Close its "
            "Chromium window; if a persistent session owns it, run "
            "`cloakgpt daemon stop`; then retry `cloakgpt login`.",
        )

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
            headless=True,
            model=cloakgpt.ChatGPTModel.GPT_5_5,
            reasoning_level=cloakgpt.ReasoningLevel.HIGH,
            status_callback=cloakgpt.show_status,
        )

    @patch("cloakgpt.request_broker")
    def test_open_session_prints_motd_and_machine_readable_id(self, request) -> None:
        request.return_value = {
            "session_id": "session-123",
            "headless": True,
            "timezone": "Asia/Taipei",
            "ttl_seconds": 7200,
        }
        output = io.StringIO()
        errors = io.StringIO()

        with redirect_stdout(output), redirect_stderr(errors):
            result = cloakgpt.main(["session", "open"])

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "session-123")
        self.assertIn("persistent conversation ready", errors.getvalue())
        self.assertIn("idle lease=120 minutes", errors.getvalue())

    @patch("cloakgpt.request_broker")
    def test_ask_with_session_uses_persistent_broker(self, request) -> None:
        request.return_value = {"answer": "Persistent answer"}
        output = io.StringIO()

        with redirect_stdout(output):
            result = cloakgpt.main(
                ["ask", "Hello", "--session", "session-123", "--reasoning", "high"]
            )

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "Persistent answer")
        request.assert_called_once_with(
            {
                "operation": "send",
                "session_id": "session-123",
                "question": "Hello",
                "model": None,
                "reasoning": "high",
            },
            status_callback=cloakgpt.show_status,
        )

    @patch("cloakgpt.start_conversation", return_value="Visible answer")
    def test_headed_option_shows_browser(self, start_conversation) -> None:
        result = cloakgpt.main(["ask", "Hello", "--headed"])

        self.assertEqual(result, 0)
        self.assertFalse(start_conversation.call_args.kwargs["headless"])

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
