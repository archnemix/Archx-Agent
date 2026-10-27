"""M23: MCP client transports, server registration/trust, and the optional Archx MCP server."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from archx_agent.adapters.mcp_client import (
    McpHttpClient,
    McpStdioClient,
    _parse_http_body,
)
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ConflictError,
    ExtensionTrustError,
    MCPProtocolError,
    MCPServerError,
    MCPTimeoutError,
    MCPToolError,
    NotFoundError,
    PermissionDeniedError,
    ToolNotFoundError,
    ToolValidationError,
    ValidationError,
)
from archx_agent.interfaces.mcp_server import ArchxMcpServer

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_server.py"
CLI_ENTRY = (
    "import sys; from archx_agent.interfaces.cli.main import main; "
    "raise SystemExit(main(sys.argv[1:]))"
)


def fixture_cmd(*args: str) -> list[str]:
    return [sys.executable, str(FIXTURE), *args]


@pytest.fixture()
def ws(tmp_path):
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


@pytest.fixture()
def client():
    c = McpStdioClient(fixture_cmd(), name="fixture", timeout=10)
    c.initialize()
    yield c
    c.close()


def stdio_server(ws, name="fixture", *, trusted=True, enabled=True, args=()):
    return ws.mcp.add_server(
        name,
        transport="stdio",
        command=sys.executable,
        args=[str(FIXTURE), *args],
        trusted=trusted,
        enabled=enabled,
    )


# --------------------------------------------------------------------------
# transports
# --------------------------------------------------------------------------
class TestStdioTransport:
    def test_initialize_reports_the_protocol_and_server(self, client):
        assert client.protocol_version == "2025-06-18"
        assert client.server_info["name"] == "fixture-mcp"
        assert "tools" in client.capabilities

    def test_list_and_call_real_tools(self, client):
        names = [tool.name for tool in client.list_tools()]
        assert {"echo", "add", "slow", "explode"} <= set(names)
        assert client.call_tool("echo", {"text": "hi"}).text == "echo: hi"
        assert client.call_tool("add", {"a": 2, "b": 40}).text == "42"

    def test_tool_schema_is_carried(self, client):
        add = next(t for t in client.list_tools() if t.name == "add")
        assert add.input_schema["required"] == ["a", "b"]
        assert add.input_schema["properties"]["a"]["type"] == "integer"

    def test_tool_error_is_reported_not_swallowed(self, client):
        with pytest.raises(MCPToolError, match="always going to fail"):
            client.call_tool("explode")

    def test_unknown_method_is_an_error(self, client):
        with pytest.raises(MCPServerError, match="method not found"):
            client.request("bogus/method")

    def test_timeout_does_not_hang(self):
        c = McpStdioClient(fixture_cmd(), name="slow-fixture", timeout=10)
        try:
            c.initialize()
            started = time.monotonic()
            with pytest.raises(MCPTimeoutError):
                c.call_tool("slow", {"seconds": 3}, timeout=0.3)
            assert time.monotonic() - started < 3
        finally:
            c.close()

    def test_missing_command_is_a_clear_error(self):
        with pytest.raises(MCPServerError, match="cannot start"):
            McpStdioClient(["/definitely/not/a/binary-xyz"], name="nope")

    def test_server_that_exits_is_reported_with_its_status(self):
        c = McpStdioClient(fixture_cmd("--bogus-flag"), name="broken", timeout=5)
        try:
            with pytest.raises(MCPServerError) as exc:
                c.initialize()
            assert "exited with status" in exc.value.message
        finally:
            c.close()

    def test_server_that_never_answers_fails_instead_of_hanging(self, tmp_path):
        script = tmp_path / "mute.py"
        script.write_text("import time\nprint('not json', flush=True)\ntime.sleep(30)\n")
        c = McpStdioClient([sys.executable, str(script)], name="mute", timeout=0.5)
        try:
            with pytest.raises((MCPTimeoutError, MCPServerError)):
                c.initialize()
        finally:
            c.close()

    def test_close_is_safe_to_call_twice(self, client):
        client.close()
        client.close()
        with pytest.raises(MCPServerError):
            client.request("ping")

    def test_resources_and_prompts(self, client):
        assert client.list_resources()[0]["uri"] == "fixture://readme"
        assert client.read_resource("fixture://readme")["contents"][0]["text"] == "fixture resource"
        assert client.list_prompts() == []

    def test_server_to_client_ping_is_answered(self):
        """A server that pings us gets a result, so it can never hang on us."""
        c = McpStdioClient(fixture_cmd(), name="fixture", timeout=5)
        try:
            c.initialize()
            responded = []
            c._write = lambda message: responded.append(message)  # type: ignore[assignment]
            c._dispatch_incoming({"jsonrpc": "2.0", "id": 999, "method": "ping"})
            c._dispatch_incoming({"jsonrpc": "2.0", "id": 1000, "method": "sampling/createMessage"})
            assert responded[0] == {"jsonrpc": "2.0", "id": 999, "result": {}}
            assert responded[1]["error"]["code"] == -32601
        finally:
            c.close()


class _JsonHandler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, str, str, dict[str, str]]] = {}
    seen: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        _JsonHandler.seen.append({"body": body, "headers": dict(self.headers)})
        status, content_type, payload, headers = self.routes.get(
            self.path, (404, "application/json", '{"error":"no route"}', {})
        )
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["id"] = body.get("id")  # a real peer answers the request it was given
            payload = json.dumps(payload)
        raw = payload.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture()
def json_http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _JsonHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _JsonHandler.routes = {}
    _JsonHandler.seen = []
    yield f"http://127.0.0.1:{server.server_port}", _JsonHandler
    server.shutdown()
    server.server_close()


class TestHttpTransport:
    def test_json_response_and_session_id(self, json_http_server):
        url, handler = json_http_server
        handler.routes["/mcp"] = (
            200,
            "application/json",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "http-fixture"},
                    "capabilities": {},
                },
            },
            {"Mcp-Session-Id": "sess-42"},
        )
        client = McpHttpClient(url + "/mcp", name="http-fixture")
        client.initialize()
        assert client.protocol_version == "2025-06-18"
        assert client.session_id == "sess-42"

    def test_session_header_is_echoed_on_later_requests(self, json_http_server):
        url, handler = json_http_server
        handler.routes["/mcp"] = (
            200, "application/json",
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": [], "protocolVersion": "p"}},
            {"Mcp-Session-Id": "sess-9"},
        )
        client = McpHttpClient(url + "/mcp", name="echo-session")
        client.initialize()
        client.list_tools()
        assert handler.seen[-1]["headers"].get("Mcp-Session-Id") == "sess-9"

    def test_sse_response_is_parsed(self, json_http_server):
        url, handler = json_http_server
        handler.routes["/mcp"] = (
            200,
            "text/event-stream",
            'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"p","tools":[]}}\n\n',
            {},
        )
        client = McpHttpClient(url + "/mcp", name="sse")
        assert client.initialize()["protocolVersion"] == "p"

    def test_http_error_is_reported_with_the_body(self, json_http_server):
        url, handler = json_http_server
        handler.routes["/mcp"] = (500, "application/json", {"error": "boom"}, {})
        client = McpHttpClient(url + "/mcp", name="err")
        with pytest.raises(MCPServerError, match="HTTP 500"):
            client.initialize()

    def test_unreachable_endpoint_is_reported(self):
        client = McpHttpClient("http://127.0.0.1:9/mcp", name="dead", timeout=2)
        with pytest.raises(MCPServerError, match="cannot reach"):
            client.initialize()

    def test_bad_url_and_body_are_rejected(self):
        with pytest.raises(ValidationError, match="http"):
            McpHttpClient("ftp://example.com")
        with pytest.raises(MCPProtocolError):
            _parse_http_body("not json", "application/json")


# --------------------------------------------------------------------------
# server registration, trust, sync
# --------------------------------------------------------------------------
class TestMcpServers:
    def test_add_validates_transport_specific_fields(self, ws):
        with pytest.raises(ValidationError, match="--command"):
            ws.mcp.add_server("a", transport="stdio")
        with pytest.raises(ValidationError, match="--url"):
            ws.mcp.add_server("b", transport="http")
        with pytest.raises(ValidationError, match="unknown transport"):
            ws.mcp.add_server("c", transport="carrier-pigeon", command="x")

    def test_duplicate_names_are_refused(self, ws):
        stdio_server(ws, "dup")
        with pytest.raises(ConflictError, match="already exists"):
            stdio_server(ws, "dup")

    def test_server_records_are_persisted_and_listed(self, ws):
        stdio_server(ws, "fixture", trusted=False, enabled=False)
        rows = ws.mcp.servers()
        assert len(rows) == 1
        assert rows[0].transport == "stdio"
        assert rows[0].command == sys.executable
        assert rows[0].last_status == "never connected"
        assert rows[0].to_dict()["trusted"] is False

    def test_untrusted_sync_discovers_but_registers_nothing(self, ws):
        stdio_server(ws, "fixture", trusted=False, enabled=False)
        result = ws.mcp.sync("fixture")
        assert result["discovered"]
        assert result["registered"] == []
        assert result["callable"] is False
        assert "not trusted" in result["reason"]
        assert ws.mcp.tools_of("fixture")
        assert not any(spec.name.startswith("mcp.fixture") for spec in ws.tools.specs())

    def test_trusted_and_enabled_sync_registers_tools(self, ws):
        stdio_server(ws, "fixture")
        result = ws.mcp.sync("fixture")
        assert result["callable"] is True
        assert set(result["registered"]) == {
            "mcp.fixture.add", "mcp.fixture.echo", "mcp.fixture.slow",
            "mcp.fixture.explode", "mcp.fixture.session",
        }
        spec = ws.tools.spec("mcp.fixture.add")
        assert spec.capability == "mcp.call"
        assert spec.origin == "mcp:fixture"
        assert spec.required == ("a", "b")

    def test_calling_an_mcp_tool_needs_a_grant_then_runs(self, ws):
        stdio_server(ws, "fixture")
        ws.mcp.sync("fixture")
        with pytest.raises(ApprovalRequiredError) as exc:
            ws.tools.execute("mcp.fixture.echo", {"text": "hi"})
        assert exc.value.capability == "mcp.call"
        ws.permissions.approve(exc.value.approval_id)
        run = ws.tools.execute("mcp.fixture.echo", {"text": "hi"})
        assert run.status == "succeeded"
        assert run.result["content"][0]["text"] == "echo: hi"

    def test_remote_tool_errors_become_failed_runs(self, ws):
        stdio_server(ws, "fixture")
        ws.mcp.sync("fixture")
        ws.permissions.grant("mcp.call", subject="mcp.fixture.explode", duration="persistent", confirm=True)
        with pytest.raises(MCPToolError):
            ws.tools.execute("mcp.fixture.explode", {})
        assert ws.tools.runs(tool="mcp.fixture.explode")[0]["status"] == "failed"

    def test_argument_types_follow_the_remote_schema(self, ws):
        stdio_server(ws, "fixture")
        ws.mcp.sync("fixture")
        ws.permissions.grant("mcp.call", subject="mcp.fixture.add", duration="persistent", confirm=True)
        run = ws.tools.execute("mcp.fixture.add", {"a": "2", "b": "3"})  # coerced from the CLI form
        assert run.result["content"][0]["text"] == "5"
        with pytest.raises(ToolValidationError, match="does not take"):
            ws.tools.execute("mcp.fixture.add", {"a": 1, "b": 2, "c": 3})

    def test_dropping_a_tool_unregisters_it(self, ws):
        stdio_server(ws, "fixture")
        ws.mcp.sync("fixture")
        assert any(spec.name == "mcp.fixture.slow" for spec in ws.tools.specs())
        ws.mcp.update_server("fixture", args=[str(FIXTURE), "--tools", "echo,add"])
        ws.mcp._close(ws.mcp.server("fixture").id)
        result = ws.mcp.sync("fixture")
        assert set(result["registered"]) == {"mcp.fixture.add", "mcp.fixture.echo"}
        assert not any(spec.name == "mcp.fixture.slow" for spec in ws.tools.specs())
        assert {row["name"] for row in ws.mcp.tools_of("fixture")} == {"echo", "add"}

    def test_untrusting_removes_the_tools(self, ws):
        stdio_server(ws, "fixture")
        ws.mcp.sync("fixture")
        ws.mcp.trust("fixture", trusted=False)
        with pytest.raises(ToolNotFoundError):
            ws.tools.execute("mcp.fixture.echo", {"text": "hi"})

    def test_disabling_removes_the_tools_and_invoke_refuses(self, ws):
        stdio_server(ws, "fixture")
        ws.mcp.sync("fixture")
        ws.mcp.enable("fixture", enabled=False)
        with pytest.raises(ToolNotFoundError):
            ws.tools.execute("mcp.fixture.echo", {"text": "hi"})
        with pytest.raises(ExtensionTrustError, match="disabled"):
            ws.mcp.invoke("fixture", "echo", {"text": "hi"})

    def test_untrusted_invoke_is_refused(self, ws):
        stdio_server(ws, "fixture", trusted=False)
        with pytest.raises(ExtensionTrustError, match="not trusted"):
            ws.mcp.invoke("fixture", "echo", {"text": "hi"})

    def test_sync_failure_is_recorded_not_hidden(self, ws):
        ws.mcp.add_server("broken", command="/definitely/not/here", enabled=True, trusted=True)
        with pytest.raises(MCPServerError):
            ws.mcp.sync("broken")
        server = ws.mcp.server("broken")
        assert server.last_status == "error"
        assert "cannot start" in (server.last_error or "")
        ws.events.flush()
        assert any(e.name == "server.sync_failed" for e in ws.events.query(kind="mcp", limit=20))

    def test_remove_server_clears_tools_and_specs(self, ws):
        stdio_server(ws, "fixture")
        ws.mcp.sync("fixture")
        ws.mcp.remove_server("fixture")
        assert ws.mcp.servers() == []
        assert not any(spec.name.startswith("mcp.fixture") for spec in ws.tools.specs())
        with pytest.raises(NotFoundError):
            ws.mcp.server("fixture")

    def test_status_reports_tool_counts(self, ws):
        stdio_server(ws, "fixture")
        ws.mcp.sync("fixture")
        status = ws.mcp.status()[0]
        assert status["tools"] == 5
        assert status["registered"] == 5
        assert status["connected"] is True

    def test_sync_twice_is_idempotent(self, ws):
        stdio_server(ws, "fixture")
        ws.mcp.sync("fixture")
        before = len(ws.tools.specs())
        ws.mcp.sync("fixture")
        assert len(ws.tools.specs()) == before

    def test_http_server_can_be_synced(self, ws, json_http_server):
        url, handler = json_http_server
        handler.routes["/mcp"] = (
            200, "application/json",
            {
                "jsonrpc": "2.0", "id": 1,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "remote-http"},
                    "capabilities": {"tools": {}},
                    "tools": [
                        {
                            "name": "lookup",
                            "description": "look something up",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"q": {"type": "string"}},
                                "required": ["q"],
                            },
                        }
                    ],
                },
            },
            {},
        )
        ws.mcp.add_server("remote", transport="http", url=url + "/mcp", trusted=True, enabled=True)
        result = ws.mcp.sync("remote")
        assert result["registered"] == ["mcp.remote.lookup"]
        assert ws.mcp.server("remote").protocol_version == "2025-06-18"


# --------------------------------------------------------------------------
# the optional Archx MCP server
# --------------------------------------------------------------------------
class TestArchxMcpServer:
    def test_disabled_by_default_with_the_exact_hint(self, ws):
        with pytest.raises(ValidationError, match="mcp.server_enabled"):
            ArchxMcpServer(ws)

    def test_whitelist_is_enforced(self, ws):
        ws.config.set("mcp.server_enabled", True)
        server = ArchxMcpServer(ws, allowed_tools=["fs.read"])
        listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert [t["name"] for t in listed["result"]["tools"]] == ["fs.read"]
        refused = server.handle(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "fs.write", "arguments": {"path": "x", "content": "y"}}}
        )
        assert refused["error"]["code"] == -32602

    def test_unknown_tool_in_the_allowlist_fails_at_startup(self, ws):
        ws.config.set("mcp.server_enabled", True)
        with pytest.raises(ValidationError, match="unknown tool"):
            ArchxMcpServer(ws, allowed_tools=["fs.teleport"])

    def test_initialize_and_ping(self, ws):
        ws.config.set("mcp.server_enabled", True)
        server = ArchxMcpServer(ws, allowed_tools=["archx.info"])
        init = server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test"}}}
        )
        assert init["result"]["serverInfo"]["name"] == "archx-agent"
        assert init["result"]["capabilities"]["tools"] is not None
        assert server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
        assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
        assert server.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"] == -32601

    def test_a_local_grant_does_not_authorise_a_remote_client(self, ws):
        ws.config.set("mcp.server_enabled", True)
        Path(ws.tool_roots()[0], "shared.txt").write_text("shared content")
        ws.permissions.grant("fs.read", subject="fs.read", duration="persistent", confirm=True)
        server = ArchxMcpServer(ws, allowed_tools=["fs.read"])
        denied = server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "fs.read", "arguments": {"path": "shared.txt"}}}
        )
        assert denied["result"]["isError"] is True
        assert "denied" in denied["result"]["content"][0]["text"]
        ws.permissions.grant("fs.read", subject="mcp-server", duration="persistent", confirm=True)
        allowed = server.handle(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "fs.read", "arguments": {"path": "shared.txt"}}}
        )
        assert allowed["result"]["isError"] is False
        assert "shared content" in allowed["result"]["content"][0]["text"]

    def test_stdio_loop_talks_json_rpc(self, ws):
        import io

        ws.config.set("mcp.server_enabled", True)
        server = ArchxMcpServer(ws, allowed_tools=["archx.info"])
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
            + "not json\n"
        )
        stdout = io.StringIO()
        server.serve_stdio(stdin=stdin, stdout=stdout)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
        assert lines[0]["result"]["protocolVersion"]
        assert lines[1]["result"]["tools"][0]["name"] == "archx.info"
        assert lines[2]["error"]["code"] == -32700

    def test_http_transport_serves_health_and_calls(self, ws):
        import urllib.request

        ws.config.set("mcp.server_enabled", True)
        server = ArchxMcpServer(ws, allowed_tools=["archx.info"])
        httpd = server.serve_http(host="127.0.0.1", port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{httpd.server_port}"
            with urllib.request.urlopen(base + "/") as response:
                health = json.loads(response.read())
            assert health["name"] == "archx-agent"
            request = urllib.request.Request(
                base + "/",
                data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": "archx.info", "arguments": {}}}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read())
            assert payload["result"]["isError"] is False
            assert "tool_limits" in payload["result"]["content"][0]["text"]
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_our_client_can_drive_our_own_server_end_to_end(self, ws):
        """A real subprocess of this same CLI, spoken to with the real MCP client."""
        ws.config.set("mcp.server_enabled", True)
        ws.config.set("mcp.server_tools", ["fs.read"])
        ws.config.save(ws.config.path("paths.home") / "config.json")
        Path(ws.tool_roots()[0], "e2e.txt").write_text("end to end")
        ws.permissions.grant("fs.read", subject="mcp-server", duration="persistent", confirm=True)
        command = [sys.executable, "-c", CLI_ENTRY, "--home", str(ws.config.home),
                   "mcp", "serve", "--transport", "stdio"]
        client = McpStdioClient(command, name="archx-self", timeout=20)
        try:
            client.initialize()
            names = [tool.name for tool in client.list_tools()]
            assert names == ["fs.read"]
            call = client.call_tool("fs.read", {"path": "e2e.txt"})
            assert "end to end" in call.text
        finally:
            client.close()
