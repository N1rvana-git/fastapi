"""Minimal OpenAI-compatible streaming stub for local/CI verification.

Why: end-to-end SSE tests should not depend on a paid provider or the network.
Run it next to the API and point ``CHAT_BASE_URL`` at it:

    python scripts/dev_llm_stub.py --port 8125
    # .env / env vars
    CHAT_BASE_URL=http://127.0.0.1:8125/v1
    CHAT_API_KEY=stub

It streams a deterministic answer (and, when the request contains tool results,
a short acknowledgement), which is enough to exercise the gateway, the SSE
buffer, idempotent replay and the agent loop plumbing.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_CHUNKS = ["你好", "，我是", "闲小宝", "（stub）", "。"]
_TOOL_CHUNKS = ["已收到", "工具结果", "，正在", "整理回答。"]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003 - stdlib API
        return  # keep the stub quiet

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        messages = payload.get("messages") or []
        has_tool_result = any(message.get("role") == "tool" for message in messages)
        chunks = _TOOL_CHUNKS if has_tool_result else _CHUNKS

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        for chunk in chunks:
            frame = {
                "id": "stub-1",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(frame, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.02)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAI-compatible SSE stub")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8125)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"LLM stub listening on http://{args.host}:{args.port}/v1/chat/completions")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
