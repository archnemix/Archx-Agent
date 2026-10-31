#!/usr/bin/env python3
"""A real (small) MCP server used by the M23 tests and acceptance script.

It speaks JSON-RPC 2.0 over stdio by default, and over HTTP with ``--http --port N``.
Nothing here is a mock of the protocol: the client under test opens a real pipe (or a real
socket) and exchanges real messages.

Tools:
    echo   {text}                 -> "echo: <text>"
    add    {a, b}                 -> "<sum>"
    slow   {seconds}              -> waits, then "slept"
    explode                       -> isError: true
    session                       -> protocol version and request count

Run with ``--tools echo,add`` to advertise a subset, which is how the tests exercise the
"server dropped a tool we had registered" path.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROTOCOL_VERSION = "2025-06-18"


def tool_definitions() -> list[dict]:
    return [
        {
            "name": "echo",
            "description": "echo the text back",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "text to echo"}},
                "required": ["text"],
            },
        },
        {
            "name": "add",
            "description": "add two integers",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "description": "first"},
                    "b": {"type": "integer", "description": "second"},
                },
                "required": ["a", "b"],
            },
        },
        {
            "name": "slow",
            "description": "sleep for a while",
            "inputSchema": {
                "type": "object",
                "properties": {"seconds": {"type": "number", "description": "how long"}},
                "required": ["seconds"],
            },
        },
        {"name": "explode", "description": "always fails", "inputSchema": {"type": "object"}},
        {"name": "session", "description": "report session details", "inputSchema": {"type": "object"}},
    ]


class Session:
    def __init__(self, advertised: set[str] | None = None) -> None:
        self.count = 0
        self.initialized = False
        self.tools = [t for t in tool_definitions() if not advertised or t["name"] in advertised]

    def handle(self, message: dict) -> dict | None:
        self.count += 1
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if request_id is None:
            return None
        if method == "initialize":
            self.initialized = True
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "fixture-mcp", "version": "0.1.0"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.tools}}
        if method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"resources": [{"uri": "fixture://readme", "name": "readme"}]},
            }
        if method == "resources/read":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"contents": [{"uri": params.get("uri"), "text": "fixture resource"}]},
            }
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}
        if method == "tools/call":
            return {"jsonrpc": "2.0", "id": request_id, "result": self.call(params)}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }

    def call(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            return {"content": [{"type": "text", "text": f"echo: {args.get('text', '')}"}]}
        if name == "add":
            try:
                total = int(args.get("a")) + int(args.get("b"))
            except (TypeError, ValueError):
                return {"content": [{"type": "text", "text": "a and b must be integers"}], "isError": True}
            return {"content": [{"type": "text", "text": str(total)}]}
        if name == "slow":
            time.sleep(float(args.get("seconds", 1)))
            return {"content": [{"type": "text", "text": "slept"}]}
        if name == "explode":
            return {"content": [{"type": "text", "text": "boom: it was always going to fail"}], "isError": True}
        if name == "session":
            return {
                "content": [
                    {"type": "text", "text": json.dumps({"initialized": self.initialized,
                                                         "requests": self.count})}
                ]
            }
        return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}


def serve_stdio(session: Session) -> None:
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            print(json.dumps({"jsonrpc": "2.0", "id": None,
                              "error": {"code": -32700, "message": "parse error"}}), flush=True)
            continue
        if message.get("method") == "exit":
            return
        response = session.handle(message)
        if response is not None:
            print(json.dumps(response), flush=True)


def serve_http(session: Session, host: str, port: int) -> None:
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            message = json.loads(self.rfile.read(length) or b"{}")
            with lock:
                response = session.handle(message)
            if response is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "fixture-session-1")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"listening on {host}:{port}", file=sys.stderr, flush=True)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--tools", default="")
    args = parser.parse_args()
    advertised = {x.strip() for x in args.tools.split(",") if x.strip()}
    session = Session(advertised or None)
    if args.http:
        serve_http(session, args.host, args.port)
    else:
        serve_stdio(session)


if __name__ == "__main__":
    main()
