import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import cloakgpt_session


def async_page(url: str = "about:blank") -> Mock:
    page = Mock()
    page.url = url
    page.close = AsyncMock()
    return page


def async_context(*pages: Mock) -> Mock:
    context = Mock()
    context.pages = []
    context.new_page = AsyncMock(side_effect=pages or [async_page()])
    context.close = AsyncMock()
    return context


class SessionBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.page = async_page()
        self.context = async_context(self.page)
        self.launch_patch = patch(
            "cloakgpt_session.launch_chatgpt_context_async",
            new_callable=AsyncMock,
        )
        self.launch = self.launch_patch.start()
        self.launch.return_value = self.context
        self.broker = cloakgpt_session.SessionBroker(
            data_dir=self.data_dir,
            headless=True,
            timezone="Asia/Taipei",
            ttl_seconds=7200,
        )

    async def asyncTearDown(self) -> None:
        await self.broker.close()
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

    async def test_detects_current_process(self) -> None:
        self.assertTrue(cloakgpt_session._pid_is_alive(os.getpid()))
        self.assertFalse(cloakgpt_session._pid_is_alive(-1))

    async def test_windows_broker_is_hidden_and_uses_utf8(self) -> None:
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

    async def test_open_session_does_not_launch_browser(self) -> None:
        opened = self.open_session()

        self.assertFalse(opened["warm"])
        self.launch.assert_not_awaited()
        self.context.new_page.assert_not_awaited()

    @patch("cloakgpt_session.send_message_on_page", new_callable=AsyncMock)
    async def test_reopens_conversation_and_closes_browser_after_each_message(
        self, send
    ) -> None:
        session_id = self.open_session()["session_id"]
        first_page = async_page()
        second_page = async_page()
        first_context = async_context(first_page)
        second_context = async_context(second_page)
        self.launch.side_effect = [first_context, second_context]
        send.side_effect = [
            ("First answer", "https://chatgpt.com/c/test"),
            ("Second answer", "https://chatgpt.com/c/test"),
        ]
        first_status = Mock()

        first = await self.broker.send(
            {
                "session_id": session_id,
                "question": "First",
                "model": None,
                "reasoning": None,
            },
            first_status,
        )
        second = await self.broker.send(
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
        self.assertEqual(self.launch.await_count, 2)
        self.assertIs(send.await_args_list[0].args[0], first_page)
        self.assertEqual(send.await_args_list[0].args[1], cloakgpt_session.CHATGPT_URL)
        self.assertIs(send.await_args_list[1].args[0], second_page)
        self.assertEqual(
            send.await_args_list[1].args[1], "https://chatgpt.com/c/test"
        )
        self.assertTrue(send.await_args_list[0].kwargs["reuse_page"])
        self.assertIs(
            send.await_args_list[0].kwargs["composer_lock"],
            self.broker._composer_lock,
        )
        first_page.close.assert_awaited_once_with()
        second_page.close.assert_awaited_once_with()
        first_context.close.assert_awaited_once_with()
        second_context.close.assert_awaited_once_with()
        self.assertFalse(first["warm"])
        self.assertFalse(second["warm"])
        first_status.assert_any_call("Closing browser...")

    @patch("cloakgpt_session.send_message_on_page", new_callable=AsyncMock)
    async def test_one_shot_closes_page_without_saving_session(self, send) -> None:
        send.return_value = ("One-shot answer", "https://chatgpt.com/c/temporary")
        status = Mock()

        result = await self.broker.send_once(
            {
                "question": "Hello",
                "model": None,
                "reasoning": None,
            },
            status,
        )

        self.assertEqual(result, {"answer": "One-shot answer"})
        self.assertEqual(self.broker.sessions, {})
        self.page.close.assert_awaited_once_with()
        self.context.close.assert_awaited_once_with()
        status.assert_any_call("Opening a temporary new conversation...")

    @patch("cloakgpt_session.send_message_on_page", new_callable=AsyncMock)
    async def test_one_shot_preserves_cold_session_record(self, send) -> None:
        session_id = self.open_session()["session_id"]
        send.return_value = ("One-shot answer", "https://chatgpt.com/c/temporary")

        result = await self.broker.send_once(
            {"question": "Hello", "model": None, "reasoning": None}, Mock()
        )

        self.assertEqual(result, {"answer": "One-shot answer"})
        self.assertIn(session_id, self.broker.sessions)
        self.assertEqual(self.broker.pages, {})

    @patch("cloakgpt_session.send_message_on_page", new_callable=AsyncMock)
    async def test_restarts_only_failed_page_once_before_delivery(self, send) -> None:
        session_id = self.open_session()["session_id"]
        replacement = async_page()
        self.context.new_page.side_effect = [self.page, replacement]
        send.side_effect = [
            RuntimeError("page disconnected before click"),
            ("Recovered", "https://chatgpt.com/c/recovered"),
        ]

        result = await self.broker.send(
            {
                "session_id": session_id,
                "question": "Hello",
                "model": None,
                "reasoning": None,
            },
            Mock(),
        )

        self.assertEqual(result["answer"], "Recovered")
        self.assertEqual(send.await_count, 2)
        self.page.close.assert_awaited_once_with()
        replacement.close.assert_awaited_once_with()
        self.context.close.assert_awaited_once_with()

    @patch("cloakgpt_session.send_message_on_page", new_callable=AsyncMock)
    async def test_never_retries_unknown_delivery(self, send) -> None:
        session_id = self.open_session()["session_id"]
        send.side_effect = cloakgpt_session.DeliveryStateUnknownError(
            "delivery state unknown"
        )

        with self.assertRaisesRegex(
            cloakgpt_session.DeliveryStateUnknownError,
            "delivery state unknown",
        ):
            await self.broker.send(
                {
                    "session_id": session_id,
                    "question": "Hello",
                    "model": None,
                    "reasoning": None,
                },
                Mock(),
            )

        send.assert_awaited_once()
        self.page.close.assert_awaited_once_with()
        self.context.close.assert_awaited_once_with()

    async def test_rejects_mode_and_timezone_changes(self) -> None:
        with self.assertRaisesRegex(ValueError, "headless mode"):
            self.broker.open_session(
                {"headless": False, "timezone": "Asia/Taipei"}, Mock()
            )
        with self.assertRaisesRegex(ValueError, "timezone is Asia/Taipei"):
            self.broker.open_session(
                {"headless": True, "timezone": "Europe/Paris"}, Mock()
            )

    async def test_close_cold_session_does_not_launch_browser(self) -> None:
        session_id = self.open_session()["session_id"]

        result = self.broker.close_session(session_id)

        self.assertTrue(result["closed"])
        self.launch.assert_not_awaited()
        self.page.close.assert_not_awaited()
        self.context.close.assert_not_awaited()

    async def test_watchdog_preserves_cold_session(self) -> None:
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
        self.assertEqual(self.broker.pages, {})

    async def test_restores_session_record_after_broker_restart(self) -> None:
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
            await restored.close()

    @patch("cloakgpt_session.send_message_on_page", new_callable=AsyncMock)
    async def test_different_sessions_have_no_broker_page_limit(self, send) -> None:
        session_ids = [self.open_session()["session_id"] for _ in range(5)]
        pages = [async_page() for _ in session_ids]
        self.context.new_page.side_effect = pages
        entered = 0
        all_entered = asyncio.Event()
        release = asyncio.Event()

        async def wait_for_release(*args, **kwargs):
            nonlocal entered
            entered += 1
            if entered == len(session_ids):
                all_entered.set()
            await release.wait()
            question = args[2]
            return question, f"https://chatgpt.com/c/{question}"

        send.side_effect = wait_for_release
        tasks = [
            asyncio.create_task(
                self.broker.send(
                    {
                        "session_id": session_id,
                        "question": f"session-{index}",
                        "model": None,
                        "reasoning": None,
                    },
                    Mock(),
                )
            )
            for index, session_id in enumerate(session_ids)
        ]

        await asyncio.wait_for(all_entered.wait(), timeout=1)
        self.assertEqual(len(self.broker.pages), 5)
        self.assertEqual(self.context.close.await_count, 0)
        daemon_status = await self.broker.dispatch({"operation": "ping"}, Mock())
        self.assertEqual(daemon_status["active_requests"], 5)
        self.assertEqual(daemon_status["queued_requests"], 0)
        self.assertEqual(daemon_status["open_pages"], 5)
        self.assertEqual(daemon_status["browser"], "running")
        release.set()
        results = await asyncio.gather(*tasks)

        self.assertEqual(len(results), 5)
        self.assertEqual(send.await_count, 5)
        self.context.close.assert_awaited_once_with()

    @patch("cloakgpt_session.send_message_on_page", new_callable=AsyncMock)
    async def test_same_session_is_fifo_and_uses_updated_url(self, send) -> None:
        session_id = self.open_session()["session_id"]
        second_page = async_page()
        self.context.new_page.side_effect = [self.page, second_page]
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        entered_questions: list[str] = []

        async def ordered_send(*args, **kwargs):
            question = args[2]
            entered_questions.append(question)
            if question == "First":
                first_entered.set()
                await release_first.wait()
            return question, "https://chatgpt.com/c/ordered"

        send.side_effect = ordered_send
        first = asyncio.create_task(
            self.broker.send(
                {
                    "session_id": session_id,
                    "question": "First",
                    "model": None,
                    "reasoning": None,
                },
                Mock(),
            )
        )
        await first_entered.wait()
        second_status = Mock()
        second = asyncio.create_task(
            self.broker.send(
                {
                    "session_id": session_id,
                    "question": "Second",
                    "model": None,
                    "reasoning": None,
                },
                second_status,
            )
        )
        await asyncio.sleep(0)

        self.assertEqual(entered_questions, ["First"])
        second_status.assert_any_call("Waiting for an earlier message in this session...")
        daemon_status = await self.broker.dispatch({"operation": "ping"}, Mock())
        self.assertEqual(daemon_status["active_requests"], 1)
        self.assertEqual(daemon_status["queued_requests"], 1)
        release_first.set()
        await asyncio.gather(first, second)

        self.assertEqual(entered_questions, ["First", "Second"])
        self.assertEqual(
            send.await_args_list[1].args[1], "https://chatgpt.com/c/ordered"
        )
        self.context.close.assert_awaited_once_with()

    @patch("cloakgpt_session.send_message_on_page", new_callable=AsyncMock)
    async def test_completed_request_does_not_close_another_page(self, send) -> None:
        first_id = self.open_session()["session_id"]
        second_id = self.open_session()["session_id"]
        second_page = async_page()
        self.context.new_page.side_effect = [self.page, second_page]
        both_entered = asyncio.Event()
        first_release = asyncio.Event()
        second_release = asyncio.Event()
        entered: set[str] = set()

        async def controlled_send(*args, **kwargs):
            question = args[2]
            entered.add(question)
            if len(entered) == 2:
                both_entered.set()
            await (first_release if question == "First" else second_release).wait()
            return question, f"https://chatgpt.com/c/{question}"

        send.side_effect = controlled_send
        first = asyncio.create_task(
            self.broker.send(
                {"session_id": first_id, "question": "First"}, Mock()
            )
        )
        second = asyncio.create_task(
            self.broker.send(
                {"session_id": second_id, "question": "Second"}, Mock()
            )
        )
        await both_entered.wait()
        first_release.set()
        await first

        self.page.close.assert_awaited_once_with()
        second_page.close.assert_not_awaited()
        self.context.close.assert_not_awaited()

        second_release.set()
        await second
        second_page.close.assert_awaited_once_with()
        self.context.close.assert_awaited_once_with()

    @patch("cloakgpt_session.send_message_on_page", new_callable=AsyncMock)
    async def test_busy_session_cannot_be_closed(self, send) -> None:
        session_id = self.open_session()["session_id"]
        entered = asyncio.Event()
        release = asyncio.Event()

        async def wait_for_release(*args, **kwargs):
            entered.set()
            await release.wait()
            return "Done", "https://chatgpt.com/c/done"

        send.side_effect = wait_for_release
        task = asyncio.create_task(
            self.broker.send(
                {"session_id": session_id, "question": "Hello"}, Mock()
            )
        )
        await entered.wait()

        with self.assertRaisesRegex(RuntimeError, "session is busy"):
            self.broker.close_session(session_id)

        release.set()
        await task

    @patch("cloakgpt_session.send_message_on_page", new_callable=AsyncMock)
    async def test_stop_drains_active_requests(self, send) -> None:
        session_id = self.open_session()["session_id"]
        entered = asyncio.Event()
        release = asyncio.Event()

        async def wait_for_release(*args, **kwargs):
            entered.set()
            await release.wait()
            return "Done", "https://chatgpt.com/c/done"

        send.side_effect = wait_for_release
        request = asyncio.create_task(
            self.broker.send(
                {"session_id": session_id, "question": "Hello"}, Mock()
            )
        )
        await entered.wait()
        stop = asyncio.create_task(self.broker.dispatch({"operation": "stop"}, Mock()))
        await asyncio.sleep(0)
        self.assertFalse(stop.done())

        release.set()
        await request
        self.assertEqual(await stop, {"stopped": True})
        self.assertTrue(self.broker.draining)


if __name__ == "__main__":
    unittest.main()
