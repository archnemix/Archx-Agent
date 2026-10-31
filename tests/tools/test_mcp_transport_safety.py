"""MCP byte/deadline/lifecycle regressions using real pipes and loopback HTTP."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
import threading
import time

import pytest

from archx_agent.adapters.mcp_client import (
    McpHttpClient,
    McpStdioClient,
    _parse_http_body,
)
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import (
    MCPProtocolError,
    MCPServerError,
    MCPTimeoutError,
    ValidationError,
)


@contextmanager
def peer(callback):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            message = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
            )
            try:
                callback(self, message)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def reply(handler, payload, *, status=200, content_type="application/json"):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def stdio(code, **kwargs):
    return McpStdioClient([sys.executable, "-u", "-c", code], **kwargs)


@pytest.mark.parametrize(
    "value", [0, -1, True, "1", None, float("nan"), float("inf"), 10**1000]
)
@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_bad_timeout_before_io(value, transport, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid timeout started a process")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    with pytest.raises(ValidationError):
        if transport == "stdio":
            stdio("pass", timeout=value)
        else:
            McpHttpClient("http://127.0.0.1:9", timeout=value)


@pytest.mark.parametrize("field", ["max_message_bytes", "max_pending"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "32"])
def test_bad_limits(field, value):
    with pytest.raises(ValidationError):
        McpHttpClient("http://127.0.0.1:9", **{field: value})


@pytest.mark.parametrize(
    "command", [None, [], "python", [""], [sys.executable, 3], [sys.executable, "\0"]]
)
def test_bad_argv(command):
    with pytest.raises(ValidationError):
        McpStdioClient(command)


@pytest.mark.parametrize(
    "url",
    [
        None,
        "ftp://example.com",
        "http://",
        "http://user:secret@localhost",
        "http://localhost:bad",
        "http://localhost:99999",
        "http://localhost/\n",
    ],
)
def test_invalid_urls_do_not_echo_credentials(url):
    with pytest.raises(ValidationError) as error:
        McpHttpClient(url)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "headers", [[("X", "value")], {"X\r": "a"}, {"X": "\n"}, {"X": 3}, {"X": "😀"}]
)
def test_invalid_headers(headers):
    with pytest.raises(ValidationError):
        McpHttpClient("http://127.0.0.1:9", headers=headers)


@pytest.mark.parametrize("value", [0, False, -1, float("nan")])
def test_per_call_timeout_validated_without_sending(value):
    client = McpHttpClient("http://127.0.0.1:9")
    try:
        with pytest.raises(ValidationError):
            client.request("ping", timeout=value)
        assert not client._pending and client._sender is None
    finally:
        client.close()


def test_blocked_stdin_is_inside_deadline():
    client = stdio("import time; time.sleep(30)", timeout=0.15)
    try:
        start = time.monotonic()
        with pytest.raises(MCPTimeoutError):
            client.request("blocked", {"text": "x" * 1_000_000})
        assert time.monotonic() - start < 1.5
        assert client.closed and not client._pending
        assert client.process.poll() is not None
    finally:
        client.close()


@pytest.mark.parametrize(
    "data",
    [
        b"not json\n",
        b"\xff\n",
        b"[" * 1200 + b"0" + b"]" * 1200 + b"\n",
        b"[]\n",
        b'{"jsonrpc":"1.0","id":1,"result":{}}\n',
        b'{"jsonrpc":"2.0","id":1,"error":"wrong"}\n',
        b'{"jsonrpc":"2.0","id":true,"result":{}}\n',
        b'{"jsonrpc":"2.0","id":[],"result":{}}\n',
    ],
)
def test_bad_stdio_protocol_fails_pending_without_thread_crash(data):
    client = stdio(
        f"import sys,time;sys.stdin.buffer.readline();sys.stdout.buffer.write({data!r});sys.stdout.flush();time.sleep(30)",
        timeout=2,
    )
    try:
        with pytest.raises(MCPProtocolError):
            client.request("ping")
        assert not client._pending and client.closed
    finally:
        client.close()


@pytest.mark.parametrize("newline", [b"", b"\n"])
def test_stdout_byte_limit_even_without_newline(newline):
    data = b"x" * 5000 + newline
    client = stdio(
        f"import sys,time;sys.stdin.buffer.readline();sys.stdout.buffer.write({data!r});sys.stdout.flush();time.sleep(30)",
        max_message_bytes=512,
        timeout=2,
    )
    try:
        with pytest.raises(MCPProtocolError, match="exceeds 512"):
            client.request("ping")
    finally:
        client.close()


def test_stderr_single_line_is_bounded_and_does_not_deadlock():
    code = "import sys,json,time;sys.stdin.readline();sys.stderr.write('x'*2000000);sys.stderr.flush();print(json.dumps({'jsonrpc':'2.0','id':1,'result':{'ok':True}}));time.sleep(30)"
    client = stdio(code, timeout=3)
    try:
        assert client.request("ping")["ok"]
        assert len(client._stderr_lines) <= 200
        assert sum(len(s) for s in client.stderr_tail(200)) <= 200 * 4096
        with pytest.raises(ValidationError):
            client.stderr_tail(0)
    finally:
        client.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX child-group cleanup")
def test_close_kills_ordinary_descendants_and_does_not_wait_for_pipe_eof(tmp_path):
    marker = tmp_path / "escaped"
    child = f'import time,pathlib;time.sleep(1);pathlib.Path({str(marker)!r}).write_text("escaped")'
    code = f"import sys,json,subprocess,time;sys.stdin.readline();subprocess.Popen([sys.executable,'-c',{child!r}]);print(json.dumps({{'jsonrpc':'2.0','id':1,'result':{{'ready':True}}}}));time.sleep(30)"
    client = stdio(code, timeout=2)
    assert client.request("ping")["ready"]
    start = time.monotonic()
    client.close()
    assert time.monotonic() - start < 1
    time.sleep(1.2)
    assert not marker.exists()
    for worker in (client._reader, client._stderr_thread):
        worker.join(1)
        assert not worker.is_alive()


def test_close_wakes_inflight_and_pending_limit_is_explicit(tmp_path):
    ready = tmp_path / "ready"
    client = stdio(
        f"import pathlib,sys,time;sys.stdin.readline();pathlib.Path({str(ready)!r}).touch();time.sleep(30)",
        timeout=3,
        max_pending=1,
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(client.request, "wait")
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists()
            with pytest.raises(MCPServerError, match="too many pending"):
                client.request("second")
            client.close()
            with pytest.raises(MCPServerError):
                waiting.result(timeout=1)
        assert not client._pending
    finally:
        client.close()


def test_outgoing_overflow_and_serialization_remove_pending():
    client = McpHttpClient("http://127.0.0.1:9", max_message_bytes=512)
    try:
        with pytest.raises(MCPProtocolError, match="outgoing message"):
            client.request("ping", {"text": "x" * 1000})
        with pytest.raises(MCPProtocolError, match="JSON data"):
            client.request("ping", {"data": object()})
        assert not client._pending and client.alive()
    finally:
        client.close()


def test_http_drip_read_and_override_are_inside_caller_deadline():
    def slow(handler, message):
        handler.send_response(200)
        handler.send_header("Content-Length", "10000")
        handler.end_headers()
        for _ in range(100):
            handler.wfile.write(b" ")
            handler.wfile.flush()
            time.sleep(0.025)

    with peer(slow) as url:
        client = McpHttpClient(url, timeout=10)
        try:
            start = time.monotonic()
            with pytest.raises(MCPTimeoutError):
                client.request("ping", timeout=0.15)
            assert time.monotonic() - start < 1
            assert client.closed and not client._pending
        finally:
            client.close()


@pytest.mark.parametrize(
    "body,ctype",
    [
        (b"\xff", "application/json"),
        (b"[]", "application/json"),
        (b"123", "application/json"),
        (b"data: 123\n\n", "text/event-stream"),
        (b"[" * 1200 + b"0" + b"]" * 1200, "application/json"),
    ],
)
def test_http_invalid_bodies(body, ctype):
    with peer(lambda h, m: reply(h, body, content_type=ctype)) as url:
        client = McpHttpClient(url, timeout=2)
        try:
            with pytest.raises(MCPProtocolError):
                client.request("ping")
        finally:
            client.close()


def test_http_body_limit():
    with peer(
        lambda h, m: reply(
            h, {"jsonrpc": "2.0", "id": m["id"], "result": {"text": "x" * 10000}}
        )
    ) as url:
        client = McpHttpClient(url, max_message_bytes=512, timeout=2)
        try:
            with pytest.raises(MCPProtocolError, match="exceeds 512"):
                client.request("ping")
        finally:
            client.close()


def test_http_error_body_is_prefix_only():
    with peer(lambda h, m: reply(h, b"x" * 1_000_000, status=500)) as url:
        client = McpHttpClient(url, timeout=2)
        try:
            with pytest.raises(MCPServerError, match="HTTP 500") as error:
                client.request("ping")
            assert len(str(error.value)) < 500
        finally:
            client.close()


def test_redirect_refused_without_forwarding_auth():
    visited = []
    with peer(lambda h, m: visited.append(dict(h.headers))) as destination:

        def redirect(handler, message):
            handler.send_response(302)
            handler.send_header("Location", destination)
            handler.send_header("Content-Length", "0")
            handler.end_headers()

        with peer(redirect) as url:
            client = McpHttpClient(
                url, headers={"Authorization": "Bearer not-a-real-secret"}, timeout=2
            )
            try:
                with pytest.raises(MCPProtocolError, match="redirects are refused"):
                    client.request("ping")
                assert not visited
            finally:
                client.close()


@pytest.mark.parametrize(
    "key,method",
    [
        ("tools", "tools/list"),
        ("resources", "resources/list"),
        ("prompts", "prompts/list"),
    ],
)
def test_paginated_discovery_follows_cursors(key, method):
    calls = []

    def page(handler, message):
        cursor = message["params"].get("cursor")
        calls.append(cursor)
        item = {"name": "one" if cursor is None else "two"}
        result = {key: [item]}
        if cursor is None:
            result["nextCursor"] = "next"
        reply(handler, {"jsonrpc": "2.0", "id": message["id"], "result": result})

    with peer(page) as url:
        client = McpHttpClient(url, timeout=2)
        try:
            result = getattr(
                client,
                {
                    "tools": "list_tools",
                    "resources": "list_resources",
                    "prompts": "list_prompts",
                }[key],
            )()
            assert len(result) == 2 and calls == [None, "next"]
        finally:
            client.close()


@pytest.mark.parametrize(
    "tools",
    [
        [{"name": "a", "inputSchema": []}],
        [{"name": "a", "annotations": []}],
        [{"name": "a"}, {"name": "a"}],
        ["not-an-object"],
        {"wrong": "shape"},
    ],
)
def test_malformed_discovery(tools):
    with peer(
        lambda h, m: reply(
            h, {"jsonrpc": "2.0", "id": m["id"], "result": {"tools": tools}}
        )
    ) as url:
        client = McpHttpClient(url, timeout=2)
        try:
            with pytest.raises(MCPProtocolError):
                client.list_tools()
        finally:
            client.close()


def test_discovery_cursor_cycle_refused():
    with peer(
        lambda h, m: reply(
            h,
            {
                "jsonrpc": "2.0",
                "id": m["id"],
                "result": {"tools": [], "nextCursor": "again"},
            },
        )
    ) as url:
        client = McpHttpClient(url, timeout=2)
        try:
            with pytest.raises(MCPProtocolError, match="repeated"):
                client.list_tools()
        finally:
            client.close()


def test_manager_failed_discovery_closes_cached_client_and_preserves_snapshot(tmp_path):
    def malformed(handler, message):
        result = (
            {"protocolVersion": "2025-06-18"}
            if message["method"] == "initialize"
            else {"tools": [{"name": "same/name"}, {"name": "same:name"}]}
        )
        reply(handler, {"jsonrpc": "2.0", "id": message.get("id"), "result": result})

    with (
        peer(malformed) as url,
        open_workspace(home=str(tmp_path / "home"), env={}) as ws,
    ):
        server = ws.mcp.add_server(
            "bad", transport="http", url=url, trusted=True, enabled=True
        )
        with pytest.raises(MCPProtocolError, match="collide"):
            ws.mcp.sync(server.id)
        assert server.id not in ws.mcp._clients
        assert ws.mcp.tools_of(server.id) == []
        assert ws.mcp.server(server.id).last_status == "error"


def test_parser_rejects_nonobject_sse_and_batch_entries():
    for text, ctype in [
        ("data: []\n\n", "text/event-stream"),
        ("[{} ,1]", "application/json"),
    ]:
        with pytest.raises(MCPProtocolError):
            _parse_http_body(text, ctype)


def test_http_delayed_headers_cannot_block_caller():
    def delayed(handler, message):
        time.sleep(0.4)
        reply(handler, {"jsonrpc": "2.0", "id": message["id"], "result": {}})

    with peer(delayed) as url:
        client = McpHttpClient(url, timeout=10)
        try:
            start = time.monotonic()
            with pytest.raises(MCPTimeoutError):
                client.request("ping", timeout=0.1)
            assert time.monotonic() - start < 0.8
        finally:
            client.close()


def test_outbound_queue_is_bounded_and_sender_retires(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    client = McpHttpClient("http://127.0.0.1:9", max_pending=1)

    def blocked(payload, deadline):
        entered.set()
        release.wait(2)

    monkeypatch.setattr(client, "_send", blocked)
    try:
        client.notify("first")
        assert entered.wait(1)
        client.notify("second")
        with pytest.raises(MCPServerError, match="queue is full"):
            client.notify("third")
        sender = client._sender
        client.close()
        assert client._outgoing.empty()
        release.set()
        sender.join(1)
        assert not sender.is_alive() and client._outgoing.empty()
    finally:
        release.set()
        client.close()


@pytest.mark.parametrize(
    "result",
    [
        {"protocolVersion": []},
        {"protocolVersion": "p", "serverInfo": []},
        {"protocolVersion": "p", "capabilities": []},
    ],
)
def test_invalid_initialize_releases_manager_connection(tmp_path, result):
    with (
        peer(
            lambda h, m: reply(
                h, {"jsonrpc": "2.0", "id": m.get("id"), "result": result}
            )
        ) as url,
        open_workspace(home=str(tmp_path / "home"), env={}) as ws,
    ):
        server = ws.mcp.add_server("bad-init", transport="http", url=url)
        with pytest.raises(MCPProtocolError):
            ws.mcp.sync(server.id)
        assert server.id not in ws.mcp._clients


def test_replacing_dead_cached_connection_calls_close(tmp_path):
    class Dead:
        closed = False

        def alive(self):
            return False

        def close(self):
            self.closed = True

    with open_workspace(home=str(tmp_path / "home"), env={}) as ws:
        server = ws.mcp.add_server("dead", transport="http", url="http://127.0.0.1:9")
        old = Dead()
        ws.mcp._clients[server.id] = old
        replacement = ws.mcp._client(server)
        assert old.closed and replacement is not old


@pytest.mark.parametrize(
    "result",
    [
        {"content": "bad"},
        {"content": [1]},
        {"isError": "false"},
        {"structuredContent": []},
    ],
)
def test_bad_tool_result_shape(result):
    with peer(
        lambda h, m: reply(h, {"jsonrpc": "2.0", "id": m["id"], "result": result})
    ) as url:
        client = McpHttpClient(url, timeout=2)
        try:
            with pytest.raises(MCPProtocolError):
                client.call_tool("tool")
        finally:
            client.close()


def test_discovery_aggregate_budget_is_not_only_per_page():
    def page(handler, message):
        first = "cursor" not in message["params"]
        result = {
            "tools": [
                {"name": "first" if first else "second", "description": "x" * 300}
            ]
        }
        if first:
            result["nextCursor"] = "next"
        reply(handler, {"jsonrpc": "2.0", "id": message["id"], "result": result})

    with peer(page) as url:
        client = McpHttpClient(url, max_message_bytes=512, timeout=2)
        try:
            with pytest.raises(MCPProtocolError, match="aggregate"):
                client.list_tools()
        finally:
            client.close()


def test_discovery_page_count_is_bounded(monkeypatch):
    client = McpHttpClient("http://127.0.0.1:9")
    calls = []

    def page(method, params, **kwargs):
        calls.append(params)
        return {"tools": [], "nextCursor": str(len(calls))}

    monkeypatch.setattr(client, "request", page)
    try:
        with pytest.raises(MCPProtocolError, match="100 pages"):
            client.list_tools()
        assert len(calls) == 100
    finally:
        client.close()


@pytest.mark.parametrize(
    "message",
    [
        {"jsonrpc": "2.0"},
        {"jsonrpc": "2.0", "id": 1},
        {"jsonrpc": "2.0", "result": {}},
        {"jsonrpc": "2.0", "method": []},
        {"jsonrpc": "2.0", "id": 1, "method": "ping", "result": {}},
        {"jsonrpc": "2.0", "id": 1, "error": {"code": True, "message": "bad"}},
    ],
)
def test_ambiguous_envelopes_refused(message):
    with peer(lambda h, m: reply(h, message)) as url:
        client = McpHttpClient(url, timeout=2)
        try:
            with pytest.raises(MCPProtocolError):
                client.request("ping")
        finally:
            client.close()


def test_reader_thread_start_failure_reaps_spawned_process(monkeypatch):
    import subprocess

    processes = []
    original_popen = subprocess.Popen
    original_start = threading.Thread.start

    def capture(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    def fail_reader(thread):
        if thread.name.endswith("-reader"):
            raise RuntimeError("thread unavailable")
        return original_start(thread)

    monkeypatch.setattr(subprocess, "Popen", capture)
    monkeypatch.setattr(threading.Thread, "start", fail_reader)
    with pytest.raises(MCPServerError, match="reader threads"):
        stdio("import time;time.sleep(30)")
    assert len(processes) == 1 and processes[0].poll() is not None


def test_sender_start_failure_does_not_leave_pending_or_queued_work(monkeypatch):
    original_start = threading.Thread.start

    def fail_sender(thread):
        if thread.name.endswith("-sender"):
            raise RuntimeError("thread unavailable")
        return original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", fail_sender)
    client = McpHttpClient("http://127.0.0.1:9")
    try:
        with pytest.raises(MCPServerError, match="sender thread"):
            client.request("ping")
        assert (
            not client._pending and client._outgoing.empty() and client._sender is None
        )
    finally:
        client.close()


def test_paginated_discovery_uses_one_operation_deadline():
    calls = []

    def page(handler, message):
        calls.append(message)
        time.sleep(0.07)
        reply(
            handler,
            {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {"tools": [], "nextCursor": str(len(calls))},
            },
        )

    with peer(page) as url:
        client = McpHttpClient(url, timeout=0.12)
        try:
            start = time.monotonic()
            with pytest.raises(MCPTimeoutError):
                client.list_tools()
            assert time.monotonic() - start < 0.8 and len(calls) <= 2
        finally:
            client.close()


def test_redirect_refusal_closes_its_response_before_storing_error():
    from archx_agent.adapters.mcp_client.http import _NoRedirect

    class Response:
        closed = False

        def close(self):
            self.closed = True

    response = Response()
    with pytest.raises(MCPProtocolError):
        _NoRedirect().redirect_request(
            None, response, 302, "redirect", {}, "http://example.invalid"
        )
    assert response.closed


@pytest.mark.parametrize("mode", ["short", "duplicate", "conflicting"])
def test_http_valid_json_prefix_does_not_override_response_framing(mode):
    def framed(handler, message):
        raw = json.dumps(
            {"jsonrpc": "2.0", "id": message["id"], "result": {"ok": True}}
        ).encode()
        handler.send_response(200)
        handler.send_header(
            "Content-Length", str(len(raw) + (10 if mode == "short" else 0))
        )
        if mode == "duplicate":
            handler.send_header("Content-Length", str(len(raw)))
        if mode == "conflicting":
            handler.send_header("Transfer-Encoding", "chunked")
        handler.end_headers()
        handler.wfile.write(raw)

    with peer(framed) as url:
        client = McpHttpClient(url, timeout=2)
        try:
            with pytest.raises(MCPProtocolError):
                client.request("ping")
        finally:
            client.close()


def test_http_chunked_complete_response_is_supported():
    def chunked(handler, message):
        raw = json.dumps(
            {"jsonrpc": "2.0", "id": message["id"], "result": {"ok": True}}
        ).encode()
        handler.send_response(200)
        handler.send_header("Transfer-Encoding", "chunked")
        handler.end_headers()
        handler.wfile.write(f"{len(raw):x}\r\n".encode() + raw + b"\r\n0\r\n\r\n")

    with peer(chunked) as url:
        client = McpHttpClient(url, timeout=2)
        try:
            assert client.request("ping")["ok"]
        finally:
            client.close()
