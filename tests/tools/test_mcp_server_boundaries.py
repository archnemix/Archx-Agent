"""MCP server malformed requests, framing, authentication and CLI default regressions."""

from __future__ import annotations
import argparse
from contextlib import contextmanager, nullcontext
import io
import json
import socket
import threading
import pytest
from archx_agent.application.workspace import open_workspace
from archx_agent.interfaces.mcp_server import ArchxMcpServer
from archx_agent.helpers.exceptions import ValidationError


@pytest.fixture
def service(tmp_path):
    with open_workspace(home=str(tmp_path / "home"), env={}) as ws:
        ws.config.set("mcp.server_enabled", True)
        yield ArchxMcpServer(ws, allowed_tools=["archx.info"])


@contextmanager
def listening(service, **kwargs):
    server = service.serve_http(port=0, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def exchange(address, headers, body=b"", half_close=False):
    with socket.create_connection(address, timeout=2) as sock:
        sock.sendall(
            b"POST /mcp HTTP/1.1\r\nHost: localhost\r\n" + headers + b"\r\n" + body
        )
        if half_close:
            sock.shutdown(socket.SHUT_WR)
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    return int(data.split(b" ")[1]), data


@pytest.mark.parametrize(
    "message",
    [
        [],
        {},
        {"jsonrpc": "1.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "id": True, "method": "ping"},
        {"jsonrpc": "2.0", "id": [], "method": "ping"},
    ],
)
def test_invalid_rpc_never_reaches_tool(service, message):
    assert service.handle(message)["error"]["code"] == -32600


@pytest.mark.parametrize("params", [[], 0, False, "bad"])
def test_invalid_params_are_errors(service, params):
    response = service.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params}
    )
    assert response["error"]["code"] == -32602


@pytest.mark.parametrize("args", [[], 0, False, "bad"])
def test_invalid_tool_arguments_not_masked_as_empty_object(service, args):
    response = service.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "archx.info", "arguments": args},
        }
    )
    assert response["error"]["code"] == -32602


@pytest.mark.parametrize(
    "headers,body,expected",
    [
        (b"Content-Length: -1\r\n", b"", 400),
        (b"Content-Length: 1\r\nContent-Length: 1\r\n", b"0", 400),
        (b"Transfer-Encoding: chunked\r\n", b"", 400),
        (b"Content-Length: 10000\r\n", b"", 413),
        (b"Content-Length: 1\r\n", b"\xff", 400),
        (b"Content-Length: 1\r\n", b"{", 400),
    ],
)
def test_bad_http_frames_close_connection(service, headers, body, expected):
    with listening(service, max_body_bytes=512) as address:
        code, data = exchange(address, headers, body)
    assert code == expected and b"Connection: close" in data


def test_short_body_refused(service):
    with listening(service) as address:
        code, _ = exchange(address, b"Content-Length: 20\r\n", b"{}", half_close=True)
    assert code == 400


def test_slow_body_times_out(service):
    with listening(service, request_timeout=0.05) as address:
        code, _ = exchange(address, b"Content-Length: 20\r\n", b"{}")
    assert code == 408


@pytest.mark.parametrize(
    "header",
    [
        b"",
        b"Authorization: Bearer wrong\r\n",
        b"Authorization: Bearer secret-fixture\r\nAuthorization: Bearer secret-fixture\r\n",
    ],
)
def test_auth_checked_before_reading_body(service, header):
    with listening(service, token="secret-fixture") as address:
        code, _ = exchange(address, header + b"Content-Length: 9999999999\r\n")
    assert code == 401


def test_authenticated_rpc_and_empty_allowlist(service):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
    with listening(service, token="secret-fixture") as address:
        code, data = exchange(
            address,
            b"Authorization: Bearer secret-fixture\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n",
            body,
        )
    assert code == 200 and json.loads(data.split(b"\r\n\r\n", 1)[1])["result"] == {}
    assert ArchxMcpServer(service.ws, allowed_tools=[]).allowed_tools == []


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "example.com"])
def test_non_loopback_requires_token_before_bind(service, host):
    with pytest.raises(ValidationError, match="token"):
        service.serve_http(host=host, port=0)


@pytest.mark.parametrize("token", ["", "bad token", "\udfff", True])
def test_invalid_token_refused(service, token):
    with pytest.raises(ValidationError):
        service.serve_http(port=0, token=token)


def test_stdio_overflow_stops_without_dispatching_tail(service):
    out = io.StringIO()
    service.serve_stdio(
        stdin=io.BytesIO(
            b"x" * 1000 + b"\n" + b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
        ),
        stdout=out,
        max_message_bytes=128,
    )
    assert len(out.getvalue().splitlines()) == 1 and json.loads(out.getvalue())["error"]


def test_stdio_invalid_utf8_is_parse_error(service):
    out = io.StringIO()
    service.serve_stdio(stdin=io.BytesIO(b"\xff\n"), stdout=out)
    assert json.loads(out.getvalue())["error"]["code"] == -32700


def test_cli_http_uses_config_defaults_and_token_env(service, monkeypatch):
    from archx_agent.interfaces.cli.commands import mcp as command
    import archx_agent.interfaces.mcp_server as public

    captured = {}

    class Http:
        server_port = 8848

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            captured["closed"] = True

    class Fake:
        def __init__(self, ws):
            pass

        def serve_http(self, **kwargs):
            captured.update(kwargs)
            return Http()

    monkeypatch.setattr(command, "_workspace", lambda _: nullcontext(service.ws))
    monkeypatch.setattr(public, "ArchxMcpServer", Fake)
    monkeypatch.setenv("ARCHX_TEST_MCP_TOKEN", "fixture-token")
    args = argparse.Namespace(
        mcp_command="serve",
        transport="http",
        host=None,
        port=None,
        token_env="ARCHX_TEST_MCP_TOKEN",
    )
    assert command.cmd_mcp(args) == 0
    assert captured == {
        "host": service.ws.config.get("mcp.server_host"),
        "port": service.ws.config.get("mcp.server_port"),
        "token": "fixture-token",
        "closed": True,
    }
