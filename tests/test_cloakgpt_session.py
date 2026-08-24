import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cloakgpt_session


class SessionBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.page = Mock()
        self.page.is_closed.return_value = False
        self.context = Mock()
        self.context.new_page.return_value = self.page
        self.launch_patch = patch(
            "cloakgpt_session.launch_chatgpt_context",
            return_value=self.context,
        )
        self.launch = self.launch_patch.start()
        self.broker = cloakgpt_session.SessionBroker(
            data_dir=self.data_dir,
            headless=True,
            timezone="Asia/Taipei",
            ttl_seconds=7200,
        )

    def tearDown(self) -> None:
        self.broker.close()
        self.launch_patch.stop()
        self.temporary.cleanup()

    def open_session(self) -> dict:
        return self.broker.open_session(
            {
                "operation": "open",
                "headless": True,
                "timezone": "Asia/Taipei",
            },
            Mock(),
        )

    def test_detects_current_process(self) -> None:
        self.assertTrue(cloakgpt_session._pid_is_alive(os.getpid()))
        self.assertFalse(cloakgpt_session._pid_is_alive(-1))

    def test_windows_broker_is_hidden_and_uses_utf8(self) -> None:
        log = Mock()
        with (
            patch.object(cloakgpt_session.os, "name", "nt"),
            patch.object(
                cloakgpt_session.subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0x00000200,
                create=True,
            ),
            patch.object(
                cloakgpt_session.subprocess,
                "CREATE_NO_WINDOW",
                0x08000000,
                create=True,
            ),
        ):
            options = cloakgpt_session._broker_process_options(log)

        self.assertEqual(options["creationflags"], 0x08000200)
        self.assertNotIn("start_new_session", options)
        self.assertEqual(options["env"]["PYTHONUTF8"], "1")
        self.assertEqual(options["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertIs(options["stdout"], log)
        self.assertIs(options["stderr"], log)

    @patch("cloakgpt_session.send_message_on_page")
    def test_reuses_one_context_and_page_for_multiple_messages(self, send) -> None:
        opened = self.open_session()
        session_id = opened["session_id"]
        send.side_effect = [
            ("First answer", "https://chatgpt.com/c/test"),
            ("Second answer", "https://chatgpt.com/c/test"),
        ]

        first = self.broker.send(
            {
                "session_id": session_id,
                "question": "First",
                "model": None,
                "reasoning": None,
            },
            Mock(),
        )
        second = self.broker.send(
            {
                "session_id": session_id,
                "question": "Second",
                "model": None,
                "reasoning": None,
            },
            Mock(),
        )

        self.assertEqual(first["answer"], "First answer")
        self.assertEqual(second["answer"], "Second answer")
        self.launch.assert_called_once_with(
            self.data_dir / "chatgpt-profile",
            headless=True,
            timezone="Asia/Taipei",
        )
        self.context.new_page.assert_called_once_with()
        self.assertIs(send.call_args_list[0].args[0], self.page)
        self.assertIs(send.call_args_list[1].args[0], self.page)
        self.assertTrue(send.call_args_list[0].kwargs["reuse_page"])
        self.assertTrue(send.call_args_list[1].kwargs["reuse_page"])
        self.context.close.assert_not_called()

    @patch("cloakgpt_session.send_message_on_page")
    def test_restarts_page_once_only_for_pre_delivery_failure(self, send) -> None:
        session_id = self.open_session()["session_id"]
        replacement = Mock()
        replacement.is_closed.return_value = False
        self.context.new_page.side_effect = [replacement]
        send.side_effect = [
            RuntimeError("page disconnected before click"),
            ("Recovered", "https://chatgpt.com/c/recovered"),
        ]

        result = self.broker.send(
            {
                "session_id": session_id,
                "question": "Hello",
                "model": None,
                "reasoning": None,
            },
            Mock(),
        )

        self.assertEqual(result["answer"], "Recovered")
        self.assertEqual(send.call_count, 2)
        self.page.close.assert_called_once_with()

    @patch("cloakgpt_session.send_message_on_page")
    def test_never_retries_unknown_delivery(self, send) -> None:
        session_id = self.open_session()["session_id"]
        send.side_effect = cloakgpt_session.DeliveryStateUnknownError(
            "delivery state unknown"
        )

        with self.assertRaisesRegex(
            cloakgpt_session.DeliveryStateUnknownError,
            "delivery state unknown",
        ):
            self.broker.send(
                {
                    "session_id": session_id,
                    "question": "Hello",
                    "model": None,
                    "reasoning": None,
                },
                Mock(),
            )

        send.assert_called_once()

    def test_rejects_mode_and_timezone_changes(self) -> None:
        with self.assertRaisesRegex(ValueError, "headless mode"):
            self.broker.open_session(
                {"headless": False, "timezone": "Asia/Taipei"},
                Mock(),
            )
        with self.assertRaisesRegex(ValueError, "timezone is Asia/Taipei"):
            self.broker.open_session(
                {"headless": True, "timezone": "Europe/Paris"},
                Mock(),
            )

    def test_close_session_closes_last_page_and_context(self) -> None:
        session_id = self.open_session()["session_id"]

        result = self.broker.close_session(session_id)

        self.assertTrue(result["closed"])
        self.page.close.assert_called_once_with()
        self.context.close.assert_called_once_with()

    def test_watchdog_reaps_expired_session(self) -> None:
        session_id = self.open_session()["session_id"]
        self.broker.sessions[session_id]["conversation_url"] = (
            "https://chatgpt.com/c/restorable"
        )
        self.broker.sessions[session_id]["last_used"] = time.time() - 7201

        self.broker._reap_stale()

        self.assertIn(session_id, self.broker.sessions)
        self.assertEqual(
            self.broker.sessions[session_id]["conversation_url"],
            "https://chatgpt.com/c/restorable",
        )
        self.assertNotIn(session_id, self.broker.pages)
        self.page.close.assert_called_once_with()
        self.context.close.assert_called_once_with()

    def test_restores_session_record_after_broker_restart(self) -> None:
        session_id = self.open_session()["session_id"]
        self.broker.sessions[session_id]["conversation_url"] = (
            "https://chatgpt.com/c/restored"
        )
        self.broker._save_state()

        restored = cloakgpt_session.SessionBroker(
            data_dir=self.data_dir,
            headless=True,
            timezone="Asia/Taipei",
            ttl_seconds=7200,
        )
        try:
            self.assertEqual(
                restored.session_status(session_id)["conversation_url"],
                "https://chatgpt.com/c/restored",
            )
        finally:
            restored.close()


if __name__ == "__main__":
    unittest.main()
