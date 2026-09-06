"""Tests for CloakGPT OpenAI-compatible HTTP API server."""

import json
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from chatgpt_browser import ReasoningLevel
from cloakgpt_server import (
    DEFAULT_SERVER_MODELS,
    ConversationSessionManager,
    MessageNormalizer,
    OpenAIFormatter,
    OpenAIServer,
    ReasoningResolver,
)


class TestMessageNormalizer(unittest.TestCase):
    """Verify conversion of OpenAI messages into prompt text."""

    def test_single_text_message(self):
        messages = [{"role": "user", "content": "請推薦台北適合放鬆散步的地點。"}]
        prompt = MessageNormalizer.normalize(messages)
        self.assertEqual(prompt, "請推薦台北適合放鬆散步的地點。")

    def test_multipart_content_with_image_and_file(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "請幫我分析這份資料與圖片中的重點。"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="},
                    },
                    {
                        "type": "file",
                        "file": {"filename": "report.pdf", "file_data": "data:application/pdf;base64,JVBERi0="},
                    },
                ],
            }
        ]
        prompt = MessageNormalizer.normalize(messages)
        self.assertIn("請幫我分析這份資料與圖片中的重點。", prompt)
        self.assertIn("[附件圖片", prompt)
        self.assertIn("[附件檔案: report.pdf", prompt)

    def test_multiturn_conversation(self):
        messages = [
            {"role": "system", "content": "你是一個親切的旅遊顧問。"},
            {"role": "user", "content": "今天天氣很好，想出門走走。"},
            {"role": "assistant", "content": "太棒了！請問你偏好山景還是水岸步道呢？"},
            {"role": "user", "content": "我偏好水岸步道，交通方便為佳。"},
        ]
        prompt = MessageNormalizer.normalize(messages)
        self.assertIn("你是一個親切的旅遊顧問。", prompt)
        self.assertIn("今天天氣很好，想出門走走。", prompt)
        self.assertIn("太棒了！請問你偏好山景還是水岸步道呢？", prompt)
        self.assertIn("我偏好水岸步道，交通方便為佳。", prompt)

    def test_extract_incremental_prompt(self):
        turn_1 = [{"role": "user", "content": "目前專案是什麼內容"}]
        turn_2 = [
            {"role": "user", "content": "目前專案是什麼內容"},
            {"role": "assistant", "content": "這是一個 Go 專案。"},
            {"role": "user", "content": "@main.go @go.mod"},
        ]
        incremental = MessageNormalizer.extract_incremental(turn_2, turn_1)
        self.assertEqual(incremental, "@main.go @go.mod")


class TestConversationSessionManager(unittest.TestCase):
    """Verify session continuity and task rotation logic."""

    def test_detects_continuation_and_reuses_session(self):
        manager = ConversationSessionManager()
        turn_1 = [{"role": "user", "content": "你好"}]
        is_cont_1, prompt_1, sess_id_1 = manager.process_messages(turn_1)
        self.assertFalse(is_cont_1)
        self.assertEqual(prompt_1, "你好")
        self.assertTrue(sess_id_1.startswith("serve-"))

        turn_2 = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "嗨！"},
            {"role": "user", "content": "今天天氣如何？"},
        ]
        is_cont_2, prompt_2, sess_id_2 = manager.process_messages(turn_2)
        self.assertTrue(is_cont_2)
        self.assertEqual(prompt_2, "今天天氣如何？")
        self.assertEqual(sess_id_1, sess_id_2)

    def test_detects_new_task_and_rotates_session(self):
        manager = ConversationSessionManager()
        turn_1 = [{"role": "user", "content": "任務一"}]
        _, _, sess_id_1 = manager.process_messages(turn_1)

        new_task = [{"role": "user", "content": "新任務開始"}]
        is_cont, prompt, sess_id_2 = manager.process_messages(new_task)
        self.assertFalse(is_cont)
        self.assertEqual(prompt, "新任務開始")
        self.assertNotEqual(sess_id_1, sess_id_2)

    def test_fixed_session_mode(self):
        manager = ConversationSessionManager(pinned_session_id="custom-session-xyz")
        turn_1 = [{"role": "user", "content": "第一句"}]
        _, _, sess_id_1 = manager.process_messages(turn_1)
        self.assertEqual(sess_id_1, "custom-session-xyz")

        turn_2 = [{"role": "user", "content": "新對話"}]
        _, _, sess_id_2 = manager.process_messages(turn_2)
        self.assertEqual(sess_id_2, "custom-session-xyz")


class TestOpenAIFormatter(unittest.TestCase):
    """Verify generation of OpenAI-compliant response payloads."""

    def test_format_completion_response(self):
        response = OpenAIFormatter.completion(
            model="gpt-5.5",
            content="大湖公園和碧湖公園都很適合散步，搭捷運文湖線即可抵達。",
            prompt_tokens=18,
            completion_tokens=25,
        )
        self.assertTrue(response["id"].startswith("chatcmpl-"))
        self.assertEqual(response["object"], "chat.completion")
        self.assertEqual(response["model"], "gpt-5.5")
        self.assertEqual(len(response["choices"]), 1)
        choice = response["choices"][0]
        self.assertEqual(choice["message"]["role"], "assistant")
        self.assertIn("大湖公園", choice["message"]["content"])
        self.assertEqual(choice["finish_reason"], "stop")
        self.assertEqual(response["usage"]["total_tokens"], 43)

    def test_format_chunk_response(self):
        chunk = OpenAIFormatter.chunk(
            completion_id="chatcmpl-test1234",
            model="gpt-5.5",
            delta_content="大湖公園",
            created_time=1700000000,
            finish_reason=None,
        )
        self.assertEqual(chunk["id"], "chatcmpl-test1234")
        self.assertEqual(chunk["object"], "chat.completion.chunk")
        self.assertEqual(chunk["choices"][0]["delta"]["content"], "大湖公園")
        self.assertIsNone(chunk["choices"][0]["finish_reason"])

    def test_format_chunk_reasoning_content(self):
        chunk = OpenAIFormatter.chunk(
            completion_id="chatcmpl-test1234",
            model="gpt-5.5",
            reasoning_content="• ChatGPT activity: 思考中...\n",
            created_time=1700000000,
        )
        self.assertEqual(chunk["id"], "chatcmpl-test1234")
        self.assertEqual(
            chunk["choices"][0]["delta"]["reasoning_content"],
            "• ChatGPT activity: 思考中...\n",
        )

    def test_format_error_response(self):
        payload, status_code = OpenAIFormatter.error(
            message="未提供授權憑證",
            error_type="authentication_error",
            status_code=401,
            code="invalid_api_key",
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload["error"]["message"], "未提供授權憑證")
        self.assertEqual(payload["error"]["type"], "authentication_error")
        self.assertEqual(payload["error"]["code"], "invalid_api_key")


class TestReasoningResolver(unittest.TestCase):
    """Verify reasoning level resolution from request body and defaults."""

    def test_resolve_reasoning_effort_standard_values(self):
        self.assertEqual(
            ReasoningResolver.resolve({"reasoning_effort": "low"}),
            ReasoningLevel.FAST,
        )
        self.assertEqual(
            ReasoningResolver.resolve({"reasoning_effort": "medium"}),
            ReasoningLevel.MEDIUM,
        )
        self.assertEqual(
            ReasoningResolver.resolve({"reasoning_effort": "high"}),
            ReasoningLevel.HIGH,
        )

    def test_resolve_reasoning_custom_fast(self):
        self.assertEqual(
            ReasoningResolver.resolve({"reasoning": "fast"}),
            ReasoningLevel.FAST,
        )

    def test_resolve_case_insensitive(self):
        self.assertEqual(
            ReasoningResolver.resolve({"reasoning_effort": "HIGH"}),
            ReasoningLevel.HIGH,
        )

    def test_fallback_to_default_when_omitted(self):
        self.assertIsNone(ReasoningResolver.resolve({}))
        self.assertEqual(
            ReasoningResolver.resolve({}, default_reasoning=ReasoningLevel.MEDIUM),
            ReasoningLevel.MEDIUM,
        )

    def test_unknown_value_falls_back_to_default(self):
        self.assertEqual(
            ReasoningResolver.resolve(
                {"reasoning_effort": "super-fast"},
                default_reasoning=ReasoningLevel.HIGH,
            ),
            ReasoningLevel.HIGH,
        )


class TestOpenAIServerEndpoints(unittest.TestCase):
    """Verify HTTP endpoints and status codes with a running server instance."""

    def setUp(self):
        self.mock_broker_requester = MagicMock()
        self.mock_broker_requester.return_value = {
            "answer": "推薦捷運大安森林公園站、大湖公園站以及淡水老街水岸步道。"
        }
        self.server = OpenAIServer(
            host="127.0.0.1",
            port=0,
            api_key=None,
            broker_requester=self.mock_broker_requester,
        )
        self.server.start()
        self.base_url = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.shutdown()

    def test_get_models(self):
        req = Request(f"{self.base_url}/v1/models", method="GET")
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["object"], "list")
            model_ids = [m["id"] for m in data["data"]]
            for expected_model in DEFAULT_SERVER_MODELS:
                self.assertIn(expected_model, model_ids)

    def test_head_models(self):
        req = Request(f"{self.base_url}/v1/models", method="HEAD")
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)

    def test_get_specific_model(self):
        req = Request(f"{self.base_url}/v1/models/gpt-5.5", method="GET")
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["id"], "gpt-5.5")
            self.assertEqual(data["object"], "model")

    def test_get_unknown_model(self):
        req = Request(f"{self.base_url}/v1/models/non-existent-model", method="GET")
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 404)

    def test_post_chat_completions_non_stream(self):
        payload = {
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "請推薦台北適合放鬆散步的地點。"}],
            "stream": False,
        }
        req = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["object"], "chat.completion")
            self.assertEqual(data["model"], "gpt-5.5")
            answer = data["choices"][0]["message"]["content"]
            self.assertIn("大安森林公園", answer)

    def test_post_chat_completions_stream(self):
        payload = {
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "請推薦台北適合放鬆散步的地點。"}],
            "stream": True,
        }
        req = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(
                resp.headers.get("Content-Type"),
                "text/event-stream; charset=utf-8",
            )
            data_lines = []
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if line.startswith("data:"):
                    data_lines.append(line)
                if line == "data: [DONE]":
                    break
            self.assertTrue(len(data_lines) >= 2)
            # Last line must be [DONE]
            self.assertEqual(data_lines[-1], "data: [DONE]")
            # First line must be valid chunk JSON
            chunk_data = json.loads(data_lines[0].removeprefix("data:").strip())
            self.assertEqual(chunk_data["object"], "chat.completion.chunk")

    def test_post_chat_completions_with_reasoning_effort(self):
        payload = {
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "分析演算法複雜度。"}],
            "reasoning_effort": "high",
        }
        req = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            last_request = self.mock_broker_requester.call_args[0][0]
            self.assertEqual(last_request.get("reasoning"), "high")

    def test_post_chat_completions_stream_immediate_headers_and_keepalive(self):
        # Simulate a slow broker to ensure HTTP 200 arrives immediately and keepalives are sent
        def slow_broker(request, **kwargs):
            time.sleep(2.2)
            return {"answer": "完成了！"}

        self.mock_broker_requester.side_effect = slow_broker

        payload = {
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "請慢慢回答。"}],
            "stream": True,
        }
        req = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        start_time = time.time()
        with urlopen(req) as resp:
            # Response headers and status must arrive immediately (< 0.8s)
            header_duration = time.time() - start_time
            self.assertLess(header_duration, 0.8)
            self.assertEqual(resp.status, 200)

            all_lines = []
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if line:
                    all_lines.append(line)
                if line == "data: [DONE]":
                    break

            # Must contain at least one keep-alive comment
            has_keepalive = any(line.startswith(": keep-alive") for line in all_lines)
            self.assertTrue(has_keepalive)
            self.assertEqual(all_lines[-1], "data: [DONE]")

        self.mock_broker_requester.side_effect = None

    def test_post_chat_completions_stream_broker_error(self):
        self.mock_broker_requester.side_effect = RuntimeError("ChatGPT 頁面斷線")

        payload = {
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "測試錯誤傳遞。"}],
            "stream": True,
        }
        req = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data_lines = [
                line.decode("utf-8").strip()
                for line in resp
                if line.decode("utf-8").strip().startswith("data:")
            ]
            self.assertTrue(len(data_lines) >= 2)
            self.assertEqual(data_lines[-1], "data: [DONE]")
            # One line should contain the error JSON
            error_data = [
                json.loads(line.removeprefix("data:").strip())
                for line in data_lines
                if "error" in line
            ]
            self.assertTrue(len(error_data) > 0)
            self.assertIn("ChatGPT 頁面斷線", error_data[0]["error"]["message"])

        self.mock_broker_requester.side_effect = None

    def test_post_chat_completions_stream_reasoning_content_from_status_callback(self):
        def status_emitting_broker(request, **kwargs):
            status_cb = kwargs.get("status_callback")
            if status_cb:
                status_cb("Opening ChatGPT...")
                status_cb("ChatGPT activity: 思考中...")
            return {"answer": "這是最終回答。"}

        self.mock_broker_requester.side_effect = status_emitting_broker

        payload = {
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "測試 Thinking 狀態。"}],
            "stream": True,
        }
        req = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data_chunks = []
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if line.startswith("data:") and line != "data: [DONE]":
                    data_chunks.append(json.loads(line.removeprefix("data:").strip()))

            reasoning_chunks = [
                c["choices"][0]["delta"].get("reasoning_content")
                for c in data_chunks
                if "reasoning_content" in c["choices"][0].get("delta", {})
            ]
            self.assertIn("• Opening ChatGPT...\n", reasoning_chunks)
            self.assertIn("• ChatGPT activity: 思考中...\n", reasoning_chunks)

        self.mock_broker_requester.side_effect = None

    def test_post_chat_completions_multiturn_reuses_session_and_sends_incremental(self):
        broker_calls = []

        def recording_broker(request, **kwargs):
            broker_calls.append(dict(request))
            return {"answer": f"回答: {request.get('question')}"}

        self.mock_broker_requester.side_effect = recording_broker

        # Turn 1
        payload_1 = {
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "目前專案是什麼內容"}],
        }
        req_1 = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload_1).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req_1) as resp:
            self.assertEqual(resp.status, 200)

        self.assertEqual(len(broker_calls), 1)
        first_call = broker_calls[0]
        self.assertEqual(first_call["operation"], "send")
        self.assertEqual(first_call["question"], "目前專案是什麼內容")
        first_session_id = first_call["session_id"]
        self.assertTrue(first_session_id)

        # Turn 2: Follow-up in same conversation
        payload_2 = {
            "model": "gpt-5.5",
            "messages": [
                {"role": "user", "content": "目前專案是什麼內容"},
                {"role": "assistant", "content": "這是一個 Go 專案。"},
                {"role": "user", "content": "@main.go @go.mod"},
            ],
        }
        req_2 = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload_2).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req_2) as resp:
            self.assertEqual(resp.status, 200)

        self.assertEqual(len(broker_calls), 2)
        second_call = broker_calls[1]
        self.assertEqual(second_call["operation"], "send")
        # Must reuse the same session_id
        self.assertEqual(second_call["session_id"], first_session_id)
        # Must only send the incremental user message, not duplicating the history
        self.assertEqual(second_call["question"], "@main.go @go.mod")

        self.mock_broker_requester.side_effect = None


class TestOpenAIServerAuth(unittest.TestCase):
    """Verify Bearer token authentication."""

    def setUp(self):
        self.server = OpenAIServer(
            host="127.0.0.1",
            port=0,
            api_key="secret-token-123",
            broker_requester=MagicMock(return_value={"answer": "ok"}),
        )
        self.server.start()
        self.base_url = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.shutdown()

    def test_request_without_token_rejected(self):
        req = Request(f"{self.base_url}/v1/models", method="GET")
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

    def test_request_with_invalid_token_rejected(self):
        req = Request(
            f"{self.base_url}/v1/models",
            headers={"Authorization": "Bearer wrong-token"},
            method="GET",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

    def test_request_with_valid_token_accepted(self):
        req = Request(
            f"{self.base_url}/v1/models",
            headers={"Authorization": "Bearer secret-token-123"},
            method="GET",
        )
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)


if __name__ == "__main__":
    unittest.main()
