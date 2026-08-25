import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import chatgpt_browser


class ChatGPTBrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.profile_dir = Path(self.temp_dir.name) / "profile"

        self.editor = Mock()
        self.editor.wait_for = AsyncMock()
        self.editor.fill = AsyncMock()
        self.send_button = Mock()
        self.send_button.wait_for = AsyncMock()
        self.send_button.click = AsyncMock()
        self.reasoning_trigger = Mock()
        self.reasoning_trigger.wait_for = AsyncMock()
        self.reasoning_trigger.click = AsyncMock()
        self.reasoning_trigger.inner_text = AsyncMock(return_value="高い")
        self.root_menu = Mock()
        self.root_menu.first = self.root_menu
        self.root_menu.wait_for = AsyncMock()
        self.root_menu.inner_text = AsyncMock()
        self.advanced_view = Mock()
        self.advanced_view.count = AsyncMock(return_value=1)
        self.advanced_view.click = AsyncMock()
        self.model_item = Mock()
        self.model_item.inner_text = AsyncMock(return_value="模型 GPT-5.6 Sol")
        self.model_item.click = AsyncMock()
        self.reasoning_item = Mock()
        self.reasoning_item.click = AsyncMock()
        self.submenu_items = Mock()
        self.submenu_items.count = AsyncMock(return_value=2)
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
        self.reasoning_menu.inner_text = AsyncMock()
        self.reasoning_option = Mock()
        self.reasoning_option.inner_text = AsyncMock(return_value="高い")
        self.reasoning_option.get_attribute = AsyncMock(return_value=None)
        self.reasoning_option.click = AsyncMock()
        self.reasoning_options = Mock()
        self.reasoning_options.count = AsyncMock(return_value=3)
        self.reasoning_options.nth.return_value = self.reasoning_option
        self.model_option = Mock()
        self.model_option.get_attribute = AsyncMock(return_value=None)
        self.model_option.click = AsyncMock()
        self.model_match = Mock()
        self.model_match.count = AsyncMock(return_value=1)
        self.model_match.first = self.model_option
        self.reasoning_options.filter.return_value = self.model_match
        self.reasoning_menu.locator.return_value = self.reasoning_options
        self.responses = Mock()
        self.responses.count = AsyncMock(return_value=0)
        self.responses.last.evaluate = AsyncMock(side_effect=lambda script: (
            "conversation-turn-2"
            if script == chatgpt_browser.TURN_ID_SCRIPT
            else "OK."
        ))
        self.citation_pills = Mock()
        self.citation_pills.count = AsyncMock(return_value=0)
        self.responses.last.locator.return_value = self.citation_pills

        self.page = Mock()
        self.page.url = "https://chatgpt.com/c/test-conversation"
        self.page.goto = AsyncMock()
        self.page.evaluate = AsyncMock(
            return_value={"complete": True, "status": None}
        )
        self.page.wait_for_function = AsyncMock()
        self.page.wait_for_timeout = AsyncMock()
        self.page.keyboard.press = AsyncMock()
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

        self.context = Mock()
        self.context.new_page = AsyncMock(return_value=self.page)
        self.context.close = AsyncMock()
        self.launch_patch = patch(
            "chatgpt_browser.launch_persistent_context_async",
            new_callable=AsyncMock,
        )
        self.launch_context = self.launch_patch.start()
        self.launch_context.return_value = self.context

    def tearDown(self) -> None:
        self.launch_patch.stop()
        self.temp_dir.cleanup()

    def test_start_conversation(self) -> None:
        answer = chatgpt_browser.start_conversation(
            "First",
            profile_dir=self.profile_dir,
        )

        self.assertEqual(answer, "OK.")
        self.page.goto.assert_called_once_with(
            chatgpt_browser.CHATGPT_URL,
            wait_until="domcontentloaded",
        )
        self.editor.fill.assert_called_once_with("First")
        self.send_button.click.assert_called_once_with()
        self.model_option.click.assert_not_called()
        self.reasoning_option.click.assert_not_called()
        self.assertTrue(self.launch_context.call_args.kwargs["headless"])

    def test_reports_windows_profile_in_use_without_browser_log(self) -> None:
        self.launch_context.side_effect = RuntimeError(
            "Target page, context or browser has been closed\n"
            "[pid=41108] <process did exit: exitCode=21, signal=null>\n"
            "Browser logs: noisy details"
        )

        with self.assertRaisesRegex(
            chatgpt_browser.ProfileInUseError,
            "browser profile is already in use",
        ) as error:
            chatgpt_browser.start_conversation(
                "Hello",
                profile_dir=self.profile_dir,
            )

        self.assertNotIn("Browser logs", str(error.exception))
        self.assertIn("cloakgpt daemon status", str(error.exception))
        self.assertIn("cloakgpt daemon stop", str(error.exception))

    def test_reports_localized_existing_browser_session_as_profile_in_use(self) -> None:
        self.launch_context.side_effect = RuntimeError(
            "Target page, context or browser has been closed\n"
            "[out] 既存のブラウザ セッションで開いています。"
        )

        with self.assertRaises(chatgpt_browser.ProfileInUseError):
            chatgpt_browser.start_conversation(
                "Hello",
                profile_dir=self.profile_dir,
            )

    def test_headed_conversation_shows_browser(self) -> None:
        chatgpt_browser.start_conversation(
            "Visible",
            headless=False,
            profile_dir=self.profile_dir,
        )

        self.assertFalse(self.launch_context.call_args.kwargs["headless"])

    def test_selects_requested_model(self) -> None:
        chatgpt_browser.start_conversation(
            "Hello",
            model=chatgpt_browser.ChatGPTModel.GPT_5_5,
            profile_dir=self.profile_dir,
        )

        self.model_item.click.assert_called_once_with()
        self.reasoning_options.filter.assert_called_once_with(has_text="GPT-5.5")
        self.model_option.click.assert_called_once_with()

    def test_selects_requested_reasoning_level(self) -> None:
        chatgpt_browser.start_conversation(
            "Think",
            reasoning_level=chatgpt_browser.ReasoningLevel.HIGH,
            profile_dir=self.profile_dir,
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
            )

    def test_keeps_reasoning_level_when_already_selected(self) -> None:
        self.reasoning_option.get_attribute.return_value = "true"

        chatgpt_browser.start_conversation(
            "Think",
            reasoning_level=chatgpt_browser.ReasoningLevel.HIGH,
            profile_dir=self.profile_dir,
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
        )

        status_callback.assert_any_call("ChatGPT activity: ウェブを検索中")
        status_callback.assert_any_call("ChatGPT activity: 2件のサイトを検索中")
        status_callback.assert_any_call("ChatGPT activity: 13s考えました")
        self.assertEqual(self.page.wait_for_timeout.call_count, 3)

    def test_composer_lock_does_not_serialize_response_generation(self) -> None:
        async def exercise() -> None:
            second_editor = Mock()
            second_editor.wait_for = AsyncMock()
            second_editor.fill = AsyncMock()
            second_button = Mock()
            second_button.wait_for = AsyncMock()
            second_button.click = AsyncMock()
            second_responses = Mock()
            second_responses.count = AsyncMock(return_value=0)
            second_page = Mock()
            second_page.url = self.page.url
            second_page.locator.side_effect = {
                chatgpt_browser.PROMPT_EDITOR_SELECTOR: second_editor,
                chatgpt_browser.SEND_BUTTON_SELECTOR: second_button,
                chatgpt_browser.ASSISTANT_MESSAGE_SELECTOR: second_responses,
            }.get

            entered = 0
            both_waiting = asyncio.Event()
            release = asyncio.Event()

            async def wait_for_reply(*args, **kwargs):
                nonlocal entered
                entered += 1
                if entered == 2:
                    both_waiting.set()
                await release.wait()
                return "OK."

            lock = asyncio.Lock()
            status = chatgpt_browser.ChatGPTPageStatus(
                self.page.url, "GPT-5.6 Sol", "high"
            )
            with (
                patch(
                    "chatgpt_browser._read_page_status",
                    new_callable=AsyncMock,
                    return_value=status,
                ),
                patch(
                    "chatgpt_browser._wait_for_reply",
                    new_callable=AsyncMock,
                    side_effect=wait_for_reply,
                ),
            ):
                first = asyncio.create_task(
                    chatgpt_browser.send_message_on_page(
                        self.page,
                        self.page.url,
                        "First",
                        None,
                        None,
                        None,
                        reuse_page=True,
                        composer_lock=lock,
                    )
                )
                second = asyncio.create_task(
                    chatgpt_browser.send_message_on_page(
                        second_page,
                        second_page.url,
                        "Second",
                        None,
                        None,
                        None,
                        reuse_page=True,
                        composer_lock=lock,
                    )
                )

                await asyncio.wait_for(both_waiting.wait(), timeout=1)
                self.send_button.click.assert_awaited_once_with()
                second_button.click.assert_awaited_once_with()
                release.set()
                await asyncio.gather(first, second)

        asyncio.run(exercise())

    def test_does_not_hide_unknown_delivery_after_send_click(self) -> None:
        with (
            patch(
                "chatgpt_browser._wait_for_reply",
                new_callable=AsyncMock,
                side_effect=RuntimeError("page disconnected"),
            ),
            self.assertRaisesRegex(
                chatgpt_browser.DeliveryStateUnknownError,
                "delivery state unknown",
            ),
        ):
            chatgpt_browser.start_conversation(
                "Hello",
                profile_dir=self.profile_dir,
            )

        self.send_button.click.assert_called_once_with()

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
        pills.count = AsyncMock(return_value=1)
        pill = pills.nth.return_value
        direct_links = pill.locator.return_value
        direct_links.count = AsyncMock(return_value=1)
        direct_link = direct_links.first
        direct_link.get_attribute = AsyncMock(return_value=(
            "https://example.com/report?utm_source=chatgpt.com"
        ))
        direct_link.inner_text = AsyncMock(return_value="example.com")
        pill.hover = AsyncMock()
        response.locator.return_value = pills

        page = Mock()
        page.locator.return_value.count = AsyncMock(return_value=0)
        page.wait_for_timeout = AsyncMock()

        sources = asyncio.run(chatgpt_browser._extract_sources(page, response))

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
        pills.count = AsyncMock(return_value=1)
        pill = pills.nth.return_value
        pill.locator.return_value.count = AsyncMock(return_value=0)
        pill.hover = AsyncMock()
        response.locator.return_value = pills

        page = Mock()
        popovers = page.locator.return_value
        popovers.count = AsyncMock(return_value=1)
        popover = popovers.first
        popover.inner_text = AsyncMock(return_value="1/2")
        links = Mock()
        links.count = AsyncMock(return_value=1)
        link = links.first
        link.get_attribute = AsyncMock(side_effect=[
            "https://first.example/report",
            "https://second.example/report",
        ])
        link.inner_text = AsyncMock(side_effect=[
            "first.example\nFirst report",
            "second.example\nSecond report",
        ])
        buttons = Mock()
        buttons.count = AsyncMock(return_value=2)
        buttons.nth.return_value.click = AsyncMock()
        popover.locator.side_effect = {
            "a[href]": links,
            "button": buttons,
        }.get

        page.wait_for_timeout = AsyncMock()
        page.keyboard.press = AsyncMock()
        sources = asyncio.run(chatgpt_browser._extract_sources(page, response))

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

    def test_frozen_windows_data_dir_uses_local_app_data(self) -> None:
        with (
            patch.object(chatgpt_browser.sys, "frozen", True, create=True),
            patch.object(chatgpt_browser.platform, "system", return_value="Windows"),
            patch.dict(
                chatgpt_browser.os.environ,
                {"LOCALAPPDATA": r"C:\Users\test\AppData\Local"},
                clear=True,
            ),
        ):
            data_dir = chatgpt_browser.get_default_data_dir()

        self.assertEqual(
            data_dir,
            Path(r"C:\Users\test\AppData\Local") / "CloakGPT",
        )

    def test_frozen_unix_data_dirs_follow_platform_conventions(self) -> None:
        with (
            patch.object(chatgpt_browser.sys, "frozen", True, create=True),
            patch.object(chatgpt_browser.platform, "system", return_value="Linux"),
            patch.object(Path, "home", return_value=Path("/home/test")),
            patch.dict(
                chatgpt_browser.os.environ,
                {"XDG_DATA_HOME": "/data/test"},
                clear=True,
            ),
        ):
            linux_dir = chatgpt_browser.get_default_data_dir()

        with (
            patch.object(chatgpt_browser.sys, "frozen", True, create=True),
            patch.object(chatgpt_browser.platform, "system", return_value="Darwin"),
            patch.object(Path, "home", return_value=Path("/Users/test")),
            patch.dict(chatgpt_browser.os.environ, {}, clear=True),
        ):
            macos_dir = chatgpt_browser.get_default_data_dir()

        self.assertEqual(linux_dir, Path("/data/test/CloakGPT"))
        self.assertEqual(
            macos_dir,
            Path("/Users/test/Library/Application Support/CloakGPT"),
        )

    def test_data_dir_environment_override_always_wins(self) -> None:
        custom_dir = Path(r"C:\custom-cloakgpt")
        with patch.dict(
            chatgpt_browser.os.environ,
            {"CLOAKGPT_DATA_DIR": str(custom_dir)},
            clear=True,
        ):
            data_dir = chatgpt_browser.get_default_data_dir()

        self.assertEqual(data_dir, custom_dir)


if __name__ == "__main__":
    unittest.main()
