#!/usr/bin/env python3
"""Standalone verification harness for CloakGPT OpenAI-compatible HTTP API server.

Usage:
    python3 scripts/verify_openai_server.py         # Mocked automated test
    python3 scripts/verify_openai_server.py --live  # End-to-end test with real browser session
"""

import argparse
import json
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# Ensure project root is in sys.path
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from cloakgpt_server import OpenAIServer


NATURAL_USER_PROMPT = "請用繁體中文推薦台北三個適合散步放鬆的捷運站周邊地點，並簡單說明各自的特色與交通方式。"


def run_harness(use_live: bool = False) -> bool:
    print("=" * 60)
    print(f"[*] 啟動 OpenAI 相容伺服器驗證 Harness (模式: {'實機瀏覽器' if use_live else '模擬環境'})")
    print("=" * 60)

    # If not live, mock broker requester
    broker_requester = None
    if not use_live:
        def mock_broker(req, **kwargs):
            status_cb = kwargs.get("status_callback")
            if status_cb:
                status_cb("Opening ChatGPT...")
                status_cb("ChatGPT activity: 思考中...")
            return {
                "answer": (
                    "推薦以下三個台北適合散步的捷運站周邊地點：\n"
                    "1. 大安森林公園（捷運大安森林公園站）：台北之肺，步道平緩綠意盎然。\n"
                    "2. 大湖公園（捷運大湖公園站）：依山傍水，錦帶橋景色優美。\n"
                    "3. 淡水水岸步道（捷運淡水站）：沿著金色水岸漫步，適合觀賞夕陽。"
                )
            }
        broker_requester = mock_broker

    server = OpenAIServer(
        host="127.0.0.1",
        port=0,
        api_key=None,
        broker_requester=broker_requester,
    )
    server.start()
    base_url = f"http://127.0.0.1:{server.port}"
    print(f"[+] 伺服器啟動於 {base_url}")

    all_passed = True

    # 1. 測試 GET /v1/models
    print("\n[測試 1] GET /v1/models (查詢模型清單)...")
    try:
        req = Request(f"{base_url}/v1/models", method="GET")
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("object") == "list", "回應非 list 物件"
            model_ids = [m["id"] for m in data.get("data", [])]
            print(f"    -> 成功取得可用模型清單: {model_ids}")
            print("    -> [PASS]")
    except Exception as e:
        print(f"    -> [FAIL]: {e}")
        all_passed = False

    # 2. 測試 POST /v1/chat/completions (非串流)
    print(f"\n[測試 2] POST /v1/chat/completions (非串流日常對話)...")
    print(f"    發送提示: {NATURAL_USER_PROMPT}")
    try:
        payload = {
            "model": "gpt-5.5",
            "messages": [
                {"role": "user", "content": NATURAL_USER_PROMPT}
            ],
            "stream": False,
        }
        req = Request(
            f"{base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.time()
        with urlopen(req, timeout=180 if use_live else 10) as resp:
            elapsed = time.time() - t0
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("object") == "chat.completion", "回應非 chat.completion 物件"
            answer = data["choices"][0]["message"]["content"]
            print(f"    -> 耗時 {elapsed:.2f} 秒，收到完整回答 (前 100 字):\n       {answer[:100].strip()}...")
            print("    -> [PASS]")
    except HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else ""
        print(f"    -> [FAIL]: {e} - Response: {err_body}")
        all_passed = False
    except Exception as e:
        print(f"    -> [FAIL]: {e}")
        all_passed = False

    # 3. 測試 POST /v1/chat/completions (串流 SSE)
    print(f"\n[測試 3] POST /v1/chat/completions (串流 SSE 日常對話)...")
    try:
        payload = {
            "model": "gpt-5.5",
            "messages": [
                {"role": "user", "content": "分享一道簡單美味的家常番茄炒蛋料理步驟。"}
            ],
            "stream": True,
        }
        req = Request(
            f"{base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.time()
        with urlopen(req, timeout=180 if use_live else 10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            assert "text/event-stream" in content_type, f"Content-Type 不正確: {content_type}"
            data_lines = []
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if line.startswith("data:"):
                    data_lines.append(line)
                if line == "data: [DONE]":
                    break
            assert any(l == "data: [DONE]" for l in data_lines), "串流未收到 [DONE] 終止標記"
            first_chunk = json.loads(data_lines[0].removeprefix("data:").strip())
            assert first_chunk.get("object") == "chat.completion.chunk", "Chunk 格式錯誤"
            parsed_chunks = [
                json.loads(l.removeprefix("data:").strip())
                for l in data_lines
                if l != "data: [DONE]"
            ]
            reasoning_chunks = [
                c["choices"][0]["delta"]["reasoning_content"]
                for c in parsed_chunks
                if "reasoning_content" in c["choices"][0].get("delta", {})
            ]
            if not use_live:
                assert any("思考中" in rc for rc in reasoning_chunks), "未收到 Thinking (reasoning_content) 串流"
                print(f"    -> 成功接收 Thinking 狀態區塊: {[rc.strip() for rc in reasoning_chunks]}")
            print(f"    -> 成功接收 {len(data_lines)} 個 SSE 資料區塊並確認收到 [DONE]")
            print("    -> [PASS]")
    except HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else ""
        print(f"    -> [FAIL]: {e} - Response: {err_body}")
        all_passed = False
    except Exception as e:
        print(f"    -> [FAIL]: {e}")
        all_passed = False

    # 4. 測試智慧 Session 延續多輪對話 (非串流延續追問)
    print("\n[測試 4] 測試智慧 Session 延續多輪對話 (追問第 2 輪)...")
    try:
        followup_payload = {
            "model": "gpt-5.5",
            "messages": [
                {"role": "user", "content": NATURAL_USER_PROMPT},
                {"role": "assistant", "content": "這是第一輪的推薦回答。"},
                {"role": "user", "content": "那這三個地點晚上去散步也安全合適嗎？"},
            ],
            "stream": False,
        }
        req = Request(
            f"{base_url}/v1/chat/completions",
            data=json.dumps(followup_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=180 if use_live else 10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            answer = data["choices"][0]["message"]["content"]
            print(f"    -> 成功接續第 2 輪對話，收到回答:\n       {answer[:100].strip()}...")
            print("    -> [PASS]")
    except Exception as e:
        print(f"    -> [FAIL]: {e}")
        all_passed = False

    # 5. 關閉伺服器
    server.shutdown()
    print("\n" + "=" * 60)
    if all_passed:
        print("[SUCCESS] 全部 Harness 測試項目皆已通過！")
    else:
        print("[FAILURE] 部分測試項目未通過，請檢查錯誤紀錄。")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CloakGPT OpenAI Server Verification Harness")
    parser.add_argument("--live", action="store_true", help="執行實機 ChatGPT 瀏覽器測試")
    args = parser.parse_args()
    success = run_harness(use_live=args.live)
    sys.exit(0 if success else 1)
