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

``--chunks``/``--delay`` make streams deliberately slow so load tests can hold
many SSE connections open at the same time.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_CHUNKS = ["你好", "，我是", "闲小宝", "（stub）", "。"]
_TOOL_CHUNKS = ["已收到", "工具结果", "，正在", "整理回答。"]

_CHUNK_COUNT = 5
_CHUNK_DELAY = 0.02


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
        base = _TOOL_CHUNKS if has_tool_result else _CHUNKS
        chunks = [base[index % len(base)] for index in range(_CHUNK_COUNT)]

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
            time.sleep(_CHUNK_DELAY)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


class StubServer(ThreadingHTTPServer):
    # socketserver's default backlog is 5, which makes 50 concurrent SSE
    # connections fail and look like an LLM outage. Raise it for load tests.
    daemon_threads = True
    request_queue_size = 256


def main() -> None:
    global _CHUNK_COUNT, _CHUNK_DELAY

    parser = argparse.ArgumentParser(description="OpenAI-compatible SSE stub")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8125)
    parser.add_argument("--chunks", type=int, default=5, help="number of streamed chunks")
    parser.add_argument("--delay", type=float, default=0.02, help="seconds between chunks")
    args = parser.parse_args()
    _CHUNK_COUNT = max(1, args.chunks)
    _CHUNK_DELAY = max(0.0, args.delay)
    server = StubServer((args.host, args.port), Handler)
    print(
        f"LLM stub listening on http://{args.host}:{args.port}/v1/chat/completions "
        f"(chunks={_CHUNK_COUNT}, delay={_CHUNK_DELAY}s)"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
