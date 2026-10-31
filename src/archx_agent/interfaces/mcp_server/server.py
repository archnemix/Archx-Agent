"""MCP server policy and JSON-RPC dispatch; transports have separate owners."""

from __future__ import annotations
from typing import Any, Iterable, Mapping
from archx_agent import __version__
from archx_agent.adapters.mcp_client import PROTOCOL_VERSION
from archx_agent.helpers.exceptions import (
    ArchxError,
    PermissionDeniedError,
    ValidationError,
)
from archx_agent.helpers.jsonio import json_text
from .protocol import SERVER_NAME, DEFAULT_SUBJECT, _json_schema_for

from .http import McpHttpMixin
from .stdio import McpStdioMixin


class ArchxMcpServer(McpHttpMixin, McpStdioMixin):
    def __init__(
        self,
        workspace,
        *,
        allowed_tools: Iterable[str] | None = None,
        subject: str = DEFAULT_SUBJECT,
    ) -> None:
        self.ws = workspace
        self.subject = subject
        self.allowed_tools = list(
            workspace.config.get("mcp.server_tools")
            if allowed_tools is None
            else allowed_tools
        )
        if not workspace.config.get("mcp.server_enabled"):
            raise ValidationError(
                "the MCP server is disabled (mcp.server_enabled=false); enable it deliberately "
                "with: archx-agent config set mcp.server_enabled true"
            )
        unknown = [
            name
            for name in self.allowed_tools
            if name not in {spec.name for spec in workspace.tools.specs()}
        ]
        if unknown:
            raise ValidationError(
                f"mcp.server_tools names unknown tool(s): {', '.join(unknown)}"
            )
        self.initialized = False

    def _specs(self):
        return [self.ws.tools.spec(name) for name in self.allowed_tools]

    def _error(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, Mapping):
            return self._error(None, -32600, "invalid request")
        if message.get("jsonrpc") != "2.0":
            return self._error(None, -32600, "expected JSON-RPC 2.0")
        method = message.get("method")
        request_id = message.get("id")
        if isinstance(request_id, bool) or not isinstance(
            request_id, (str, int, type(None))
        ):
            return self._error(None, -32600, "invalid request id")
        params = message.get("params", {})
        if not isinstance(params, Mapping):
            return self._error(request_id, -32602, "params must be an object")
        if "id" not in message:
            if method == "notifications/initialized":
                self.initialized = True
            return None  # notifications never get a response
        if not isinstance(method, str):
            return self._error(request_id, -32600, "missing method")
        if method == "initialize":
            self.initialized = True
            self.ws.events.record(
                "mcp",
                "server.client_connected",
                level="summary",
                payload={
                    "client": params.get("clientInfo") or {},
                    "tools": self.allowed_tools,
                },
            )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": str(
                        params.get("protocolVersion") or PROTOCOL_VERSION
                    ),
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
                            "annotations": {
                                "archxCapability": spec.capability,
                                "risk": spec.risk,
                            },
                        }
                        for spec in self._specs()
                    ]
                },
            }
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments", {})
            if name not in self.allowed_tools:
                return self._error(
                    request_id, -32602, f"tool {name!r} is not exposed by this server"
                )
            if not isinstance(arguments, Mapping):
                return self._error(request_id, -32602, "arguments must be an object")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": self._call(name, arguments),
            }
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
                "mcp",
                "server.call_denied",
                status="denied",
                payload={"tool": name, "reason": exc.message, "subject": self.subject},
            )
            return {
                "content": [{"type": "text", "text": f"denied: {exc.message}"}],
                "isError": True,
            }
        except ArchxError as exc:
            return {
                "content": [
                    {"type": "text", "text": f"{type(exc).__name__}: {exc.message}"}
                ],
                "isError": True,
            }
        self.ws.events.record(
            "mcp",
            "server.call",
            level="summary",
            payload={"tool": name, "status": run.status, "run_id": run.id},
        )
        return {
            "content": [
                {"type": "text", "text": json_text(run.result or {"error": run.error})}
            ],
            "isError": run.status != "succeeded",
            "structuredContent": run.result or {},
        }
