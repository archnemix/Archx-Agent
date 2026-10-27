#!/usr/bin/env python3
"""A minimal *Gemini-protocol* server for acceptance runs.

It is **not a model**. It speaks the documented shape of ``generateContent`` and
``streamGenerateContent`` so the HTTP path (auth header, request body, role translation,
usage parsing, error classification, redaction) can be driven end to end where Google's host
is unreachable. Every reply is prefixed with ``[PROTOCOL-STUB]`` so it can never be mistaken
for model output.

Usage:
    python scripts/gemini_protocol_stub.py --port 8123 [--fail 401|429|500] [--quota]
                                          [--block] [--empty] [--reply-file FILE]

By default any non-empty ``x-goog-api-key`` is accepted, because the point of the stub is the
protocol, not the credential. Pass ``--key`` to pin one: a request carrying a different key is
then answered with Google's own 400 message, which echoes the offending key - the point of that
behaviour is that the client must not put it on screen.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE: dict = {
    "key": None,
    "fail": 0,
    "quota": False,
    "block": False,
    "empty": False,
    "reply": "The stub read your request.",
    "attempts": 0,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------
    def log_message(self, *args) -> None:  # keep acceptance output readable
        pass

    def _send(self, status: int, payload: dict | bytes, content_type: str = "application/json") -> None:
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _fail(self) -> bool:
        """Answer with the configured failure, if any. Returns True when it answered."""
        status = STATE["fail"]
        if not status:
            return False
        if status == 401:
            self._send(401, {"error": {"code": 401, "status": "UNAUTHENTICATED",
                                       "message": "API key not valid. Please pass a valid API key."}})
        elif status == 429 and STATE["quota"]:
            self._send(429, {"error": {
                "code": 429, "status": "RESOURCE_EXHAUSTED",
                "message": "You exceeded your current quota, please check your plan and billing details.",
            }})
        elif status == 429:
            self._send(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                       "message": "Resource has been exhausted (e.g. rate limit)."}})
        elif status == 404:
            self._send(404, {"error": {"code": 404, "status": "NOT_FOUND",
                                       "message": "models/nope is not found for API version v1beta"}})
        else:
            self._send(status, {"error": {"code": status, "status": "UNAVAILABLE",
                                          "message": "The service is currently unavailable."}})
        return True

    # -- routes -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if self._fail():
            return
        self._send(200, {"models": [{
            "name": "models/gemini-2.0-flash",
            "displayName": "Gemini 2.0 Flash",
            "supportedGenerationMethods": ["generateContent", "streamGenerateContent"],
        }]})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            request = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            request = {}
        STATE["attempts"] += 1
        # The real service rejects a key it does not know, and echoes that key in the message.
        presented = self.headers.get("x-goog-api-key") or ""
        if not presented:
            self._send(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                       "message": "API key not valid. Please pass a valid API key."}})
            return
        if STATE["key"] and presented != STATE["key"]:
            self._send(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                       "message": f"API key not valid: {presented}"}})
            return
        if self._fail():
            return
        if STATE["block"]:
            self._send(200, {"promptFeedback": {"blockReason": "SAFETY"},
                             "usageMetadata": {"promptTokenCount": 3}})
            return
        if STATE["empty"]:
            self._send(200, {"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]})
            return
        if ":streamGenerateContent" in self.path:
            self._stream()
            return
        self._send(200, self._reply(request))

    # -- payloads ---------------------------------------------------------
    def _parts(self) -> list[dict]:
        return [{"text": "[PROTOCOL-STUB] " + STATE["reply"]}]

    def _reply(self, request: dict) -> dict:
        # Echo how many turns the client sent: role translation is visible in the answer.
        turns = len(request.get("contents") or [])
        return {
            "candidates": [{
                "content": {"role": "model", "parts": self._parts()},
                "finishReason": "STOP",
                "safetyRatings": [{"category": "HARM_CATEGORY_HARASSMENT", "probability": "NEGLIGIBLE"}],
            }],
            "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 5,
                              "totalTokenCount": 16, "turns": turns},
            "modelVersion": "gemini-2.0-flash-stub",
        }

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for piece in ["[PROTOCOL-STUB] ", "streamed ", "in ", "order."]:
            chunk = {"candidates": [{"content": {"parts": [{"text": piece}]}}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: {\"candidates\": []}\n\n")
        self.wfile.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--key", default=None, help="accept only this key (default: any key)")
    parser.add_argument("--fail", type=int, default=0, help="answer every request with this status")
    parser.add_argument("--quota", action="store_true", help="make a 429 mean exhausted quota")
    parser.add_argument("--block", action="store_true", help="answer with promptFeedback.blockReason")
    parser.add_argument("--empty", action="store_true", help="answer with no parts at all")
    parser.add_argument("--reply-file", default=None, help="use this file's text as the reply")
    args = parser.parse_args()

    STATE.update({"key": args.key, "fail": args.fail, "quota": args.quota,
                  "block": args.block, "empty": args.empty})
    if args.reply_file:
        STATE["reply"] = open(args.reply_file, encoding="utf-8").read().strip()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"gemini protocol stub on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
