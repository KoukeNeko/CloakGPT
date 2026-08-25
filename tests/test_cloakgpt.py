import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import cloakgpt


class CloakGPTCliTests(unittest.TestCase):
    def test_version_option_reports_build_metadata(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as exit_error:
            cloakgpt.main(["--version"])

        self.assertEqual(exit_error.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), cloakgpt.version_text())

    @patch("cloakgpt.update_cloakgpt")
    def test_update_command_preserves_current_channel(self, update) -> None:
        update.return_value = {
            "current": "v0.1.0-pre.4",
            "target": "v0.1.0-pre.5",
            "channel": "prerelease",
            "asset": "cloakgpt-windows-x86_64.exe",
            "status": "update_available",
        }
        output = io.StringIO()

        with redirect_stdout(output):
            result = cloakgpt.main(["update", "--check"])

        self.assertEqual(result, 0)
        self.assertIn("An update is available.", output.getvalue())
        update.assert_called_once_with(
            channel=None,
            version=None,
            check=True,
            status_callback=cloakgpt.show_status,
            stop_daemon=cloakgpt._stop_daemon_for_update,
        )

    @patch("cloakgpt.update_cloakgpt")
    def test_update_command_supports_json(self, update) -> None:
        update.return_value = {
            "current": "v1.0.0",
            "target": "v1.0.0",
            "channel": "stable",
            "asset": "cloakgpt-linux-x86_64",
            "status": "up_to_date",
        }
        output = io.StringIO()

        with redirect_stdout(output):
            result = cloakgpt.main(["update", "--check", "--json"])

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "up_to_date")

    @patch("cloakgpt.update_cloakgpt")
    def test_update_rejects_channel_with_exact_version(self, update) -> None:
        errors = io.StringIO()

        with redirect_stderr(errors):
            result = cloakgpt.main(
                ["update", "--channel", "stable", "--version", "v1.0.0"]
            )

        self.assertEqual(result, 1)
        self.assertIn("--channel and --version", errors.getvalue())
        update.assert_not_called()

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
    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_command(self, launch_chatgpt_context, user_input) -> None:
        context = Mock()
        login_page = Mock()
        login_page.url = "about:blank"
        extra_blank_page = Mock()
        extra_blank_page.url = "about:blank"
        existing_page = Mock()
        existing_page.url = "https://example.com/"
        context.pages = [login_page, extra_blank_page, existing_page]
        launch_chatgpt_context.return_value = context

        result = cloakgpt.main(["login", "--timezone", "Asia/Taipei"])

        self.assertEqual(result, 0)
        launch_chatgpt_context.assert_called_once_with(
            cloakgpt.DEFAULT_PROFILE_DIR,
            headless=False,
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
    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_creates_page_when_context_has_none(
        self,
        launch_chatgpt_context,
        _user_input,
    ) -> None:
        context = Mock()
        context.pages = []
        launch_chatgpt_context.return_value = context

        result = cloakgpt.main(["login"])

        self.assertEqual(result, 0)
        context.new_page.assert_called_once_with()
        context.new_page.return_value.goto.assert_called_once_with(
            cloakgpt.CHATGPT_URL,
            wait_until="domcontentloaded",
        )

    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_reports_existing_profile_without_browser_log(
        self,
        launch_chatgpt_context,
    ) -> None:
        launch_chatgpt_context.side_effect = RuntimeError(
            "the CloakGPT browser profile is already in use. Close any "
            "CloakGPT Chromium window. If `cloakgpt daemon status` reports "
            "a running daemon, reuse its known `--session` ID or run "
            "`cloakgpt daemon stop`; then retry."
        )
        errors = io.StringIO()

        with redirect_stderr(errors):
            result = cloakgpt.main(["login"])

        self.assertEqual(result, 1)
        self.assertEqual(
            errors.getvalue().strip(),
            "error: the CloakGPT browser profile is already in use. Close any "
            "CloakGPT Chromium window. If `cloakgpt daemon status` reports "
            "a running daemon, reuse its known `--session` ID or run "
            "`cloakgpt daemon stop`; then retry.",
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
        self.assertIn("Browser: on demand (headless)", errors.getvalue())

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

    @patch("cloakgpt.request_broker")
    @patch("cloakgpt.start_conversation")
    def test_one_shot_ask_reuses_daemon_after_profile_conflict(
        self,
        start_conversation,
        request,
    ) -> None:
        start_conversation.side_effect = cloakgpt.ProfileInUseError("profile in use")
        request.return_value = {"answer": "New conversation answer"}
        output = io.StringIO()

        with redirect_stdout(output):
            result = cloakgpt.main(["ask", "Hello", "--output", "jsonl"])

        self.assertEqual(result, 0)
        self.assertEqual(
            [json.loads(line) for line in output.getvalue().splitlines()],
            [
                {"type": "result", "answer": "New conversation answer"},
            ],
        )
        request.assert_called_once_with(
            {
                "operation": "send_once",
                "question": "Hello",
                "model": None,
                "reasoning": None,
            },
            auto_start=False,
            status_callback=cloakgpt._jsonl_status,
        )

    @patch("cloakgpt.request_broker")
    @patch("cloakgpt.start_conversation")
    def test_one_shot_ask_preserves_profile_error_without_daemon(
        self,
        start_conversation,
        request,
    ) -> None:
        start_conversation.side_effect = cloakgpt.ProfileInUseError("profile in use")
        request.side_effect = RuntimeError("CloakGPT daemon is not running")
        errors = io.StringIO()

        with redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello"])

        self.assertEqual(result, 1)
        self.assertEqual(errors.getvalue().strip(), "error: profile in use")

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

    @patch("cloakgpt.start_conversation")
    def test_jsonl_output_streams_status_and_result_to_stdout(
        self,
        start_conversation,
    ) -> None:
        def run(_question, **options):
            options["status_callback"]("Opening ChatGPT...")
            options["status_callback"]("Sending message...")
            options["status_callback"]("ChatGPT is responding...")
            return "技術答案"

        start_conversation.side_effect = run
        output = io.StringIO()
        errors = io.StringIO()

        with redirect_stdout(output), redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello", "--output", "jsonl"])

        self.assertEqual(result, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(
            [json.loads(line) for line in output.getvalue().splitlines()],
            [
                {"type": "status", "message": "Opening ChatGPT..."},
                {"type": "status", "message": "Sending message..."},
                {"type": "status", "message": "ChatGPT is responding..."},
                {"type": "result", "answer": "技術答案"},
            ],
        )

    @patch("cloakgpt.start_conversation", side_effect=ValueError("not available"))
    def test_jsonl_output_reports_machine_readable_error(
        self,
        _start_conversation,
    ) -> None:
        output = io.StringIO()
        errors = io.StringIO()

        with redirect_stdout(output), redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello", "--output", "jsonl"])

        self.assertEqual(result, 1)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(
            json.loads(output.getvalue()),
            {"type": "error", "message": "not available"},
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
