import io
from pathlib import Path
import json
import signal
import time
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import cloakgpt
import cloakgpt_display
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

    def _open_page(self, url: str = "about:blank") -> Mock:
        page = Mock()
        page.url = url
        page.is_closed.return_value = False
        return page

    def _run_login(
        self,
        arguments: list[str],
        *,
        desktop: bool = True,
        interactive: bool = False,
        starts_signed_in: bool = False,
        signed_in=(True,),
    ):
        output = io.StringIO()
        stdin = Mock()
        stdin.isatty.return_value = interactive
        with patch("cloakgpt.has_graphical_display", return_value=desktop), patch(
            "cloakgpt.sys.stdin", stdin
        ), patch(
            "cloakgpt._starts_signed_in", return_value=starts_signed_in
        ), patch(
            "cloakgpt._page_is_signed_in", side_effect=signed_in
        ) as page_is_signed_in, redirect_stdout(output):
            result = cloakgpt.main(arguments)
        return result, output.getvalue(), page_is_signed_in

    @patch("cloakgpt.open_remote_display")
    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_command(self, launch_chatgpt_context, open_remote_display) -> None:
        context = Mock()
        login_page = self._open_page()
        extra_blank_page = self._open_page()
        existing_page = self._open_page("https://example.com/")
        context.pages = [login_page, extra_blank_page, existing_page]
        extra_blank_page.close.side_effect = lambda: context.pages.remove(
            extra_blank_page
        )
        launch_chatgpt_context.return_value = context

        result, output, _ = self._run_login(
            ["login", "--timezone", "Asia/Taipei"],
            signed_in=(False, False, True),
        )

        self.assertEqual(result, 0)
        open_remote_display.assert_not_called()
        launch_chatgpt_context.assert_called_once_with(
            cloakgpt.DEFAULT_PROFILE_DIR,
            headless=False,
            timezone="Asia/Taipei",
            env=None,
            args=None,
        )
        context.new_page.assert_not_called()
        login_page.goto.assert_called_once_with(
            cloakgpt.CHATGPT_URL,
            wait_until="domcontentloaded",
        )
        extra_blank_page.close.assert_called_once_with()
        existing_page.close.assert_not_called()
        self.assertEqual(
            [call.args for call in login_page.wait_for_timeout.call_args_list],
            [(cloakgpt.LOGIN_POLL_MS,), (cloakgpt.LOGIN_SAVE_DELAY_MS,)],
        )
        self.assertIn("Signed in. Saving the session...", output)
        context.close.assert_called_once_with()

    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_creates_page_when_context_has_none(
        self,
        launch_chatgpt_context,
    ) -> None:
        context = Mock()
        context.pages = []
        new_page = self._open_page()
        context.new_page.side_effect = lambda: context.pages.append(new_page) or new_page
        launch_chatgpt_context.return_value = context

        result, _, _ = self._run_login(["login"])

        self.assertEqual(result, 0)
        context.new_page.assert_called_once_with()
        new_page.goto.assert_called_once_with(
            cloakgpt.CHATGPT_URL,
            wait_until="domcontentloaded",
        )

    @patch("builtins.input", return_value="")
    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_finishes_when_enter_is_pressed(
        self,
        launch_chatgpt_context,
        user_input,
    ) -> None:
        context = Mock()
        page = self._open_page()
        page.wait_for_timeout.side_effect = lambda _ms: time.sleep(0.01)
        context.pages = [page]
        launch_chatgpt_context.return_value = context

        result, output, _ = self._run_login(
            ["login"],
            interactive=True,
            signed_in=iter(lambda: False, True),
        )

        self.assertEqual(result, 0)
        user_input.assert_called_once_with()
        self.assertIn("or press Enter here to finish now.", output)
        self.assertNotIn("Signed in.", output)
        context.close.assert_called_once_with()

    @patch("builtins.input", return_value="")
    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_keeps_signed_in_profile_open_until_enter(
        self,
        launch_chatgpt_context,
        user_input,
    ) -> None:
        context = Mock()
        page = self._open_page()
        page.wait_for_timeout.side_effect = lambda _ms: time.sleep(0.01)
        context.pages = [page]
        launch_chatgpt_context.return_value = context

        result, output, page_is_signed_in = self._run_login(
            ["login"],
            interactive=True,
            starts_signed_in=True,
        )

        self.assertEqual(result, 0)
        user_input.assert_called_once_with()
        page_is_signed_in.assert_not_called()
        self.assertIn("already signed in", output)
        context.close.assert_called_once_with()

    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_returns_when_signed_in_without_terminal(
        self,
        launch_chatgpt_context,
    ) -> None:
        context = Mock()
        page = self._open_page()
        context.pages = [page]
        launch_chatgpt_context.return_value = context

        result, output, _ = self._run_login(["login"], starts_signed_in=True)

        self.assertEqual(result, 0)
        self.assertIn("This ChatGPT profile is already signed in.", output)
        page.wait_for_timeout.assert_not_called()
        context.close.assert_called_once_with()

    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_returns_when_browser_is_closed(
        self,
        launch_chatgpt_context,
    ) -> None:
        context = Mock()
        page = self._open_page()
        context.pages = [page]
        launch_chatgpt_context.return_value = context
        page.goto.side_effect = lambda *_args, **_kwargs: page.is_closed.configure_mock(
            return_value=True
        )

        result, output, page_is_signed_in = self._run_login(["login"])

        self.assertEqual(result, 0)
        page_is_signed_in.assert_not_called()
        self.assertNotIn("Signed in.", output)
        context.close.assert_called_once_with()

    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_stop_signal_closes_browser_before_exiting(
        self,
        launch_chatgpt_context,
    ) -> None:
        context = Mock()
        page = self._open_page()
        context.pages = [page]
        launch_chatgpt_context.return_value = context
        # The signal lands inside a Playwright wait, where raising would leave
        # the browser impossible to close.
        page.wait_for_timeout.side_effect = lambda _ms: signal.raise_signal(signal.SIGINT)
        errors = io.StringIO()

        with redirect_stderr(errors):
            result, output, _ = self._run_login(
                ["login"],
                signed_in=iter(lambda: False, True),
            )

        self.assertEqual(result, 130)
        self.assertEqual(errors.getvalue().strip(), "stopped")
        page.wait_for_timeout.assert_called_once_with(cloakgpt.LOGIN_POLL_MS)
        context.close.assert_called_once_with()
        self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)

    def _remote_display(self, opened: list) -> Mock:
        display = Mock()
        display.backend = "tigervnc"
        display.display = 100
        display.port = 6100
        display.viewer_url = "http://127.0.0.1:6100/vnc.html?autoconnect=1"
        display.env = {"DISPLAY": ":100"}
        display.browser_args = ["--window-position=0,0", "--window-size=1280,800"]

        @contextmanager
        def open_remote_display(backend, port):
            opened.append((backend, port))
            yield display
            opened.append("closed")

        return display, open_remote_display

    @patch("cloakgpt.ssh_tunnel_hint", return_value="ssh -N -L 6100:127.0.0.1:6100 root@192.168.50.250")
    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_uses_remote_display_without_desktop(
        self,
        launch_chatgpt_context,
        tunnel_hint,
    ) -> None:
        opened = []
        display, open_remote_display = self._remote_display(opened)
        context = Mock()
        context.pages = [self._open_page()]
        context.close.side_effect = lambda: opened.append("browser closed")
        launch_chatgpt_context.return_value = context

        with patch("cloakgpt.open_remote_display", side_effect=open_remote_display):
            result, output, _ = self._run_login(["login"], desktop=False)

        self.assertEqual(result, 0)
        self.assertEqual(opened, [("auto", None), "browser closed", "closed"])
        launch_chatgpt_context.assert_called_once_with(
            cloakgpt.DEFAULT_PROFILE_DIR,
            headless=False,
            timezone="Asia/Taipei",
            env=display.env,
            args=display.browser_args,
        )
        tunnel_hint.assert_called_once_with(6100)
        self.assertIn("ssh -N -L 6100:127.0.0.1:6100 root@192.168.50.250", output)
        self.assertIn(display.viewer_url, output)

    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_remote_flag_selects_backend_and_port_on_desktop(
        self,
        launch_chatgpt_context,
    ) -> None:
        opened = []
        _display, open_remote_display = self._remote_display(opened)
        context = Mock()
        context.pages = [self._open_page()]
        launch_chatgpt_context.return_value = context

        with patch("cloakgpt.open_remote_display", side_effect=open_remote_display):
            result, _, _ = self._run_login(
                ["login", "--remote", "--vnc", "kasmvnc", "--port", "7000"],
            )

        self.assertEqual(result, 0)
        self.assertEqual(opened[0], ("kasmvnc", 7000))

    @patch("cloakgpt.open_remote_display")
    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_local_flag_skips_remote_display_without_desktop(
        self,
        launch_chatgpt_context,
        open_remote_display,
    ) -> None:
        context = Mock()
        context.pages = [self._open_page()]
        launch_chatgpt_context.return_value = context

        result, _, _ = self._run_login(["login", "--local"], desktop=False)

        self.assertEqual(result, 0)
        open_remote_display.assert_not_called()
        self.assertIsNone(launch_chatgpt_context.call_args.kwargs["env"])

    def test_login_modes_are_mutually_exclusive(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_error:
            cloakgpt.main(["login", "--local", "--remote"])

        self.assertEqual(exit_error.exception.code, 2)

    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_reports_missing_remote_display(
        self,
        launch_chatgpt_context,
    ) -> None:
        errors = io.StringIO()
        with patch(
            "cloakgpt.open_remote_display",
            side_effect=cloakgpt_display.RemoteDisplayError("no VNC server"),
        ), redirect_stderr(errors):
            result, _, _ = self._run_login(["login", "--remote"])

        self.assertEqual(result, 1)
        self.assertEqual(errors.getvalue().strip(), "error: no VNC server")
        launch_chatgpt_context.assert_not_called()

    @patch("cloakgpt.has_graphical_display", return_value=True)
    @patch("cloakgpt.launch_chatgpt_context")
    def test_login_reports_existing_profile_without_browser_log(
        self,
        launch_chatgpt_context,
        _has_graphical_display,
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
        # Compare against the same path object so the assertion holds on
        # Windows, where a stringified path uses backslashes.
        skill_path = Path("/home/someone/.claude/skills/x/SKILL.md")
        outdated.return_value = [skill_path]
        output = io.StringIO()

        with redirect_stdout(output):
            cloakgpt.main(["update", "--channel", "prerelease", "--json"])

        payload = json.loads(output.getvalue())
        self.assertTrue(payload["skill"]["bundled"])
        self.assertEqual(payload["skill"]["outdated"], [str(skill_path)])
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

    @patch("cloakgpt.OpenAIServer")
    def test_serve_command_starts_and_stops_server(self, mock_server_cls) -> None:
        mock_server = Mock()
        mock_server.port = 8888
        mock_server_cls.return_value = mock_server

        with patch("time.sleep", side_effect=KeyboardInterrupt):
            errors = io.StringIO()
            with redirect_stderr(errors):
                result = cloakgpt.main(["serve", "--port", "8888", "--api-key", "test-key"])

        self.assertEqual(result, 0)
        mock_server_cls.assert_called_once_with(
            host="127.0.0.1",
            port=8888,
            api_key="test-key",
            session_id=None,
            stateless=False,
            default_model=None,
            reasoning=None,
            headless=True,
            timezone="Asia/Taipei",
            verbose=True,
        )
        mock_server.start.assert_called_once()
        mock_server.shutdown.assert_called_once()
        self.assertIn("server running at http://127.0.0.1:8888/v1", errors.getvalue())
        self.assertIn("Server stopped.", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
