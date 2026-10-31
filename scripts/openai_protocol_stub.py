#!/usr/bin/env python3
"""A minimal OpenAI-compatible *protocol* server for integration testing.

It is **not a model**. It returns a deterministic reply derived from the request so the
HTTP path (auth, request shape, response parsing, streaming, error codes) can be exercised
end to end in an environment with no model weights. Every reply is prefixed with
``[PROTOCOL-STUB]`` so it can never be mistaken for model output.

Usage:
    python scripts/openai_protocol_stub.py --port 8123 [--fail 401|429|500] [--reply-file FILE]

``--reply-file`` makes the stub return the file's text as the assistant message. It
exists so acceptance scripts can drive a *real* HTTP round trip through a canned reply
(for example an agent plan) without pretending the stub is a model.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    fail_status = 0
    reply_text: str | None = None

    def _send(self, status: int, payload: dict | str) -> None:
        raw = (payload if isinstance(payload, str) else json.dumps(payload)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._send(200, {"object": "list", "data": [{"id": "protocol-stub", "object": "model"}]})
        else:
            self._send(404, {"error": {"message": "no such route"}})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.fail_status:
            messages = {
                401: "invalid api key",
                429: "rate limit exceeded",
                500: "internal error",
            }
            self._send(self.fail_status, {"error": {"message": messages.get(self.fail_status, "error")}})
            return
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self._send(404, {"error": {"message": "no such route"}})
            return
        messages = body.get("messages") or []
        last_user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
        if self.reply_text is not None:
            text = self.reply_text
        else:
            text = (
                "[PROTOCOL-STUB] this reply came from a test HTTP server, not a model. "
                f"you said: {last_user[:160]}"
            )
        self._send(
            200,
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": 0,
                "model": body.get("model", "protocol-stub"),
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
                ],
                "usage": {
                    "prompt_tokens": max(1, prompt_chars // 4),
                    "completion_tokens": max(1, len(text) // 4),
                    "total_tokens": max(1, prompt_chars // 4) + max(1, len(text) // 4),
                },
            },
        )

    def log_message(self, *args) -> None:  # keep the acceptance output readable
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--fail", type=int, default=0, help="always answer with this HTTP status")
    parser.add_argument("--reply-file", default=None, help="return this file's text as the reply")
    args = parser.parse_args()
    Handler.fail_status = args.fail
    if args.reply_file:
        Handler.reply_text = open(args.reply_file, encoding="utf-8").read()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"protocol stub listening on http://{args.host}:{args.port}/v1", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
