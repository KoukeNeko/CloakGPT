import io
from pathlib import Path
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import cloakgpt
import cloakgpt_session


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

    @patch("cloakgpt.request_broker", return_value={"answer": "First answer"})
    def test_ask_command(self, request) -> None:
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
        request.assert_called_once_with(
            {
                "operation": "send_once",
                "question": "Hello",
                "model": "gpt-5.5",
                "reasoning": "high",
            },
            headless=True,
            timezone="Asia/Taipei",
            status_callback=cloakgpt.show_status,
        )

    @patch("cloakgpt.request_broker")
    def test_open_session_prints_motd_and_machine_readable_id(self, request) -> None:
        request.return_value = {
            "session_id": "session-123",
            "headless": True,
            "timezone": "Asia/Taipei",
        }
        output = io.StringIO()
        errors = io.StringIO()

        with redirect_stdout(output), redirect_stderr(errors):
            result = cloakgpt.main(["session", "open"])

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "session-123")
        self.assertIn("persistent conversation ready", errors.getvalue())
        self.assertIn("Browser: on demand (headless)", errors.getvalue())
        self.assertIn("Different session IDs can run concurrently", errors.getvalue())

    @patch("cloakgpt.request_broker")
    def test_ask_with_session_uses_persistent_broker(self, request) -> None:
        request.return_value = {"answer": "Persistent answer"}
        output = io.StringIO()
        errors = io.StringIO()

        with redirect_stdout(output), redirect_stderr(errors):
            result = cloakgpt.main(
                ["ask", "Hello", "--session", "session-123", "--reasoning", "high"]
            )

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "Persistent answer")
        self.assertEqual(
            errors.getvalue().strip(),
            "[status] Submitting the session message to the shared browser...",
        )
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

    def _update_result(self):
        return {
            "current": "v0.1.1-pre.11",
            "target": "v0.1.1-pre.12",
            "channel": "prerelease",
            "asset": "cloakgpt-macos-arm64",
            "status": "updated",
        }

    @patch("cloakgpt.refresh_skill")
    @patch("cloakgpt.outdated_skill_paths")
    @patch("cloakgpt.update_cloakgpt")
    def test_update_prints_the_skill_command_when_not_interactive(
        self, update, outdated, refresh
    ) -> None:
        update.return_value = self._update_result()
        outdated.return_value = [Path("/home/someone/.claude/skills/x/SKILL.md")]
        output = io.StringIO()

        with patch("sys.stdin.isatty", return_value=False):
            with redirect_stdout(output):
                result = cloakgpt.main(["update", "--channel", "prerelease"])

        self.assertEqual(result, 0)
        self.assertIn("skills add", output.getvalue())
        refresh.assert_not_called()

    @patch("cloakgpt.refresh_skill")
    @patch("cloakgpt.outdated_skill_paths")
    @patch("cloakgpt.update_cloakgpt")
    def test_update_offers_to_refresh_the_skill_when_interactive(
        self, update, outdated, refresh
    ) -> None:
        update.return_value = self._update_result()
        outdated.return_value = [Path("/home/someone/.claude/skills/x/SKILL.md")]
        refresh.return_value = True

        with patch("sys.stdin.isatty", return_value=True):
            with patch("builtins.input", return_value=""):
                with redirect_stdout(io.StringIO()):
                    result = cloakgpt.main(["update", "--channel", "prerelease"])

        self.assertEqual(result, 0)
        refresh.assert_called_once_with()

    @patch("cloakgpt.refresh_skill")
    @patch("cloakgpt.outdated_skill_paths")
    @patch("cloakgpt.update_cloakgpt")
    def test_declining_the_offer_leaves_the_skill_alone(
        self, update, outdated, refresh
    ) -> None:
        update.return_value = self._update_result()
        outdated.return_value = [Path("/home/someone/.claude/skills/x/SKILL.md")]
        output = io.StringIO()

        with patch("sys.stdin.isatty", return_value=True):
            with patch("builtins.input", return_value="n"):
                with redirect_stdout(output):
                    cloakgpt.main(["update", "--channel", "prerelease"])

        refresh.assert_not_called()
        self.assertIn("skills add", output.getvalue())

    @patch("cloakgpt.refresh_skill")
    @patch("cloakgpt.outdated_skill_paths")
    @patch("cloakgpt.update_cloakgpt")
    def test_matching_skill_is_not_mentioned(self, update, outdated, refresh) -> None:
        update.return_value = self._update_result()
        outdated.return_value = []
        output = io.StringIO()

        with patch("sys.stdin.isatty", return_value=True):
            with redirect_stdout(output):
                cloakgpt.main(["update", "--channel", "prerelease"])

        self.assertNotIn("skill", output.getvalue().lower())
        refresh.assert_not_called()

    @patch("cloakgpt.outdated_skill_paths")
    @patch("cloakgpt.update_cloakgpt")
    def test_json_output_reports_the_skill_state(self, update, outdated) -> None:
        update.return_value = self._update_result()
        outdated.return_value = [Path("/home/someone/.claude/skills/x/SKILL.md")]
        output = io.StringIO()

        with redirect_stdout(output):
            cloakgpt.main(["update", "--channel", "prerelease", "--json"])

        payload = json.loads(output.getvalue())
        self.assertTrue(payload["skill"]["bundled"])
        self.assertEqual(
            payload["skill"]["outdated"],
            ["/home/someone/.claude/skills/x/SKILL.md"],
        )
        self.assertIn("skills add", payload["skill"]["install_command"])

    @patch("cloakgpt.request_broker")
    def test_update_refuses_while_an_unreachable_daemon_holds_the_profile(
        self, request
    ) -> None:
        # An unreachable daemon is alive and still owns the browser profile.
        request.side_effect = cloakgpt_session.DaemonUnavailableError(
            "could not connect to the CloakGPT daemon (pid 42)"
        )

        with self.assertRaises(cloakgpt_session.DaemonUnavailableError):
            cloakgpt._stop_daemon_for_update()

    @patch("cloakgpt.request_broker")
    def test_update_proceeds_when_no_daemon_is_running(self, request) -> None:
        request.side_effect = cloakgpt.DaemonNotRunningError(
            "CloakGPT daemon is not running"
        )

        self.assertIsNone(cloakgpt._stop_daemon_for_update())

    @patch("cloakgpt.request_broker")
    def test_status_reports_a_stopped_daemon_as_normal_output(self, request) -> None:
        request.side_effect = cloakgpt.DaemonNotRunningError(
            "CloakGPT daemon is not running"
        )
        output = io.StringIO()
        errors = io.StringIO()

        with redirect_stdout(output), redirect_stderr(errors):
            result = cloakgpt.main(["daemon", "status"])

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue()), {"running": False})
        self.assertEqual(errors.getvalue(), "")

    @patch("cloakgpt.request_broker")
    def test_status_marks_a_reachable_daemon_as_running(self, request) -> None:
        # An older daemon predates the field, so the CLI supplies it.
        request.return_value = {"pid": 7, "browser": "stopped"}
        output = io.StringIO()

        with redirect_stdout(output):
            result = cloakgpt.main(["daemon", "status"])

        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"running": True, "pid": 7, "browser": "stopped"},
        )

    @patch("cloakgpt.request_broker")
    def test_stopping_a_stopped_daemon_succeeds(self, request) -> None:
        request.side_effect = cloakgpt.DaemonNotRunningError(
            "CloakGPT daemon is not running"
        )
        output = io.StringIO()

        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            result = cloakgpt.main(["daemon", "stop"])

        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"stopped": True, "already_stopped": True},
        )

    @patch("cloakgpt.request_broker")
    def test_an_unreachable_daemon_is_still_an_error(self, request) -> None:
        request.side_effect = cloakgpt_session.DaemonUnavailableError(
            "could not connect to the CloakGPT daemon (pid 42)"
        )
        errors = io.StringIO()

        with redirect_stdout(io.StringIO()), redirect_stderr(errors):
            result = cloakgpt.main(["daemon", "status"])

        self.assertEqual(result, 1)
        self.assertIn("pid 42", errors.getvalue())

    @patch("cloakgpt.request_broker")
    def test_one_shot_ask_uses_shared_daemon(self, request) -> None:
        request.return_value = {"answer": "New conversation answer"}
        output = io.StringIO()

        with redirect_stdout(output):
            result = cloakgpt.main(["ask", "Hello", "--output", "jsonl"])

        self.assertEqual(result, 0)
        self.assertEqual(
            [json.loads(line) for line in output.getvalue().splitlines()],
            [
                {
                    "type": "status",
                    "message": "Submitting a new conversation to the shared browser...",
                },
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
            headless=True,
            timezone="Asia/Taipei",
            status_callback=cloakgpt._jsonl_status,
        )

    @patch("cloakgpt.request_broker")
    def test_one_shot_ask_reports_broker_error(self, request) -> None:
        request.side_effect = RuntimeError("profile in use")
        errors = io.StringIO()

        with redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello"])

        self.assertEqual(result, 1)
        self.assertEqual(
            errors.getvalue().strip(),
            "[status] Submitting a new conversation to the shared browser...\n"
            "error: profile in use",
        )

    @patch("cloakgpt.request_broker", return_value={"answer": "Visible answer"})
    def test_headed_option_shows_browser(self, request) -> None:
        result = cloakgpt.main(["ask", "Hello", "--headed"])

        self.assertEqual(result, 0)
        self.assertFalse(request.call_args.kwargs["headless"])

    @patch("cloakgpt.request_broker")
    def test_status_is_printed_to_stderr_only(self, request) -> None:
        def run(_request, **options):
            options["status_callback"]("Waiting for ChatGPT response...")
            return {"answer": "Answer"}

        request.side_effect = run
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello"])

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "Answer")
        self.assertEqual(
            errors.getvalue().strip(),
            "[status] Submitting a new conversation to the shared browser...\n"
            "[status] Waiting for ChatGPT response...",
        )

    @patch("cloakgpt.request_broker")
    def test_jsonl_output_streams_status_and_result_to_stdout(
        self,
        request,
    ) -> None:
        def run(_request, **options):
            options["status_callback"]("Opening ChatGPT...")
            options["status_callback"]("Sending message...")
            options["status_callback"]("ChatGPT is responding...")
            return {"answer": "技術答案"}

        request.side_effect = run
        output = io.StringIO()
        errors = io.StringIO()

        with redirect_stdout(output), redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello", "--output", "jsonl"])

        self.assertEqual(result, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(
            [json.loads(line) for line in output.getvalue().splitlines()],
            [
                {
                    "type": "status",
                    "message": "Submitting a new conversation to the shared browser...",
                },
                {"type": "status", "message": "Opening ChatGPT..."},
                {"type": "status", "message": "Sending message..."},
                {"type": "status", "message": "ChatGPT is responding..."},
                {"type": "result", "answer": "技術答案"},
            ],
        )

    @patch("cloakgpt.request_broker", side_effect=ValueError("not available"))
    def test_jsonl_output_reports_machine_readable_error(
        self,
        _request,
    ) -> None:
        output = io.StringIO()
        errors = io.StringIO()

        with redirect_stdout(output), redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello", "--output", "jsonl"])

        self.assertEqual(result, 1)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(
            [json.loads(line) for line in output.getvalue().splitlines()],
            [
                {
                    "type": "status",
                    "message": "Submitting a new conversation to the shared browser...",
                },
                {"type": "error", "message": "not available"},
            ],
        )

    @patch("cloakgpt.request_broker", side_effect=ValueError("not available"))
    def test_errors_are_reported_without_traceback(self, _request) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello"])

        self.assertEqual(result, 1)
        self.assertEqual(
            errors.getvalue().strip(),
            "[status] Submitting a new conversation to the shared browser...\n"
            "error: not available",
        )

    @patch("cloakgpt.request_broker", side_effect=KeyboardInterrupt)
    def test_ctrl_c_stops_without_traceback(self, _request) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello"])

        self.assertEqual(result, 130)
        self.assertEqual(
            errors.getvalue().strip(),
            "[status] Submitting a new conversation to the shared browser...\n"
            "stopped",
        )


if __name__ == "__main__":
    unittest.main()
