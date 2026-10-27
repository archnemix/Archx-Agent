"""The optional MCP server: expose a whitelist of Archx tools to an MCP client.

Three things make this safe enough to ship off-by-default:

1. **Off unless asked for.** ``mcp.server_enabled`` is false; ``archx-agent mcp serve``
   refuses with the exact command that would turn it on.
2. **A whitelist, not the registry.** Only tools named in ``mcp.server_tools`` are listed
   or callable. ``fs.write`` is not in the default list.
3. **The caller is a distinct subject.** Every call passes
   ``permission_subject="mcp-server"`` to the tool manager, so a grant the user made for
   their own ``fs.read`` does *not* authorise a remote client. A human has to grant
   ``fs.read`` to ``mcp-server`` explicitly.

The server speaks JSON-RPC 2.0 over stdio (line-delimited) or over HTTP POST. It implements
``initialize``, ``ping``, ``tools/list`` and ``tools/call``; everything else is answered
with a JSON-RPC ``method not found`` error rather than silence.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable, Mapping

from archx_agent import __version__
from archx_agent.adapters.mcp_client import PROTOCOL_VERSION
from archx_agent.helpers.exceptions import (
    ArchxError,
    PermissionDeniedError,
    ValidationError,
)
from archx_agent.helpers.jsonio import json_text

SERVER_NAME = "archx-agent"
DEFAULT_SUBJECT = "mcp-server"


def _json_schema_for(spec) -> dict[str, Any]:
    types = spec.types or {name: "str" for name in spec.inputs}
    json_types = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}
    properties = {
        name: {"type": json_types.get(types.get(name, "str"), "object"),
               "description": description}
        for name, description in spec.inputs.items()
    }
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if spec.required:
        schema["required"] = list(spec.required)
    return schema


class ArchxMcpServer:
    """Request handling for both transports (no sockets in this class)."""

    def __init__(self, workspace, *, allowed_tools: Iterable[str] | None = None,
                 subject: str = DEFAULT_SUBJECT) -> None:
        self.ws = workspace
        self.subject = subject
        self.allowed_tools = list(allowed_tools or workspace.config.get("mcp.server_tools"))
        if not workspace.config.get("mcp.server_enabled"):
            raise ValidationError(
                "the MCP server is disabled (mcp.server_enabled=false); enable it deliberately "
                "with: archx-agent config set mcp.server_enabled true"
            )
        unknown = [name for name in self.allowed_tools if name not in
                   {spec.name for spec in workspace.tools.specs()}]
        if unknown:
            raise ValidationError(
                f"mcp.server_tools names unknown tool(s): {', '.join(unknown)}"
            )
        self.initialized = False

    # -- helpers ----------------------------------------------------------
    def _specs(self):
        return [self.ws.tools.spec(name) for name in self.allowed_tools]

    def _error(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    # -- dispatch ---------------------------------------------------------
    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, Mapping):
            return self._error(None, -32600, "invalid request")
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if request_id is None:
            if method == "notifications/initialized":
                self.initialized = True
            return None  # notifications never get a response
        if not isinstance(method, str):
            return self._error(request_id, -32600, "missing method")
        if method == "initialize":
            self.initialized = True
            self.ws.events.record(
                "mcp", "server.client_connected", level="summary",
                payload={"client": params.get("clientInfo") or {}, "tools": self.allowed_tools},
            )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": str(params.get("protocolVersion") or PROTOCOL_VERSION),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": spec.name,
                            "description": spec.summary,
                            "inputSchema": _json_schema_for(spec),
                            "annotations": {"archxCapability": spec.capability, "risk": spec.risk},
                        }
                        for spec in self._specs()
                    ]
                },
            }
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            if name not in self.allowed_tools:
                return self._error(request_id, -32602, f"tool {name!r} is not exposed by this server")
            if not isinstance(arguments, Mapping):
                return self._error(request_id, -32602, "arguments must be an object")
            return {"jsonrpc": "2.0", "id": request_id, "result": self._call(name, arguments)}
        return self._error(request_id, -32601, f"method not found: {method}")

    def _call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        try:
            run = self.ws.tools.execute(
                name,
                dict(arguments),
                requester="mcp-server",
                permission_subject=self.subject,
            )
        except PermissionDeniedError as exc:
            self.ws.events.record(
                "mcp", "server.call_denied", status="denied",
                payload={"tool": name, "reason": exc.message, "subject": self.subject},
            )
            return {
                "content": [{"type": "text", "text": f"denied: {exc.message}"}],
                "isError": True,
            }
        except ArchxError as exc:
            return {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc.message}"}],
                "isError": True,
            }
        self.ws.events.record(
            "mcp", "server.call", level="summary",
            payload={"tool": name, "status": run.status, "run_id": run.id},
        )
        return {
            "content": [{"type": "text", "text": json_text(run.result or {"error": run.error})}],
            "isError": run.status != "succeeded",
            "structuredContent": run.result or {},
        }

    # -- transports -------------------------------------------------------
    def serve_stdio(self, stdin=None, stdout=None) -> None:
        reader = stdin or sys.stdin
        writer = stdout or sys.stdout
        for line in reader:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                response = self._error(None, -32700, "parse error")
            else:
                response = self.handle(message)
            if response is not None:
                writer.write(json.dumps(response) + "\n")
                writer.flush()

    def serve_http(self, *, host: str = "127.0.0.1", port: int = 8848) -> ThreadingHTTPServer:
        handler = self._http_handler()
        server = ThreadingHTTPServer((host, port), handler)
        self.ws.events.record(
            "mcp", "server.listening", level="summary", payload={"host": host, "port": port}
        )
        return server

    def _http_handler(self):
        server_self = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):  # noqa: N802
                body = json.dumps({"name": SERVER_NAME, "version": __version__,
                                   "tools": server_self.allowed_tools}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    message = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    self._send(400, server_self._error(None, -32700, "parse error"))
                    return
                response = server_self.handle(message)
                if response is None:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._send(200, response)

            def _send(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # keep stdout clean for stdio mode
                pass

        return Handler


__all__ = ["ArchxMcpServer", "DEFAULT_SUBJECT", "SERVER_NAME"]
