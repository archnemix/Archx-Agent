"""McpManager: calls operations."""

from __future__ import annotations
from typing import Any, Mapping
from archx_agent.adapters.mcp_client import (
    McpCallResult,
)
from archx_agent.helpers.exceptions import (
    ExtensionTrustError,
    MCPServerError,
    MCPProtocolError,
)


class McpManagerCallsMixin:
    def invoke(
        self,
        ref: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> McpCallResult:
        """Call a remote tool. Permission checks belong to the caller (ToolManager)."""
        server = self.server(ref)
        if not server.enabled:
            raise ExtensionTrustError(
                f"MCP server {server.name!r} is disabled; enable it with "
                f"`archx-agent mcp enable {server.name}`"
            )
        if not server.trusted:
            raise ExtensionTrustError(
                f"MCP server {server.name!r} is not trusted; nothing it advertises may run "
                f"(review it, then `archx-agent mcp trust {server.name}`)"
            )
        client = self._client(server)
        try:
            if not client.protocol_version:
                client.initialize()
            return client.call_tool(
                tool_name,
                arguments,
                timeout=self.client_timeout if timeout is None else timeout,
            )
        except MCPServerError as exc:
            if isinstance(exc, MCPProtocolError) or not client.alive():
                self._close(server.id)
            self._record_error(server, exc.message)
            raise

    def status(self) -> list[dict[str, Any]]:
        out = []
        for server in self.servers():
            tools = self.tools_of(server.id)
            out.append(
                {
                    **server.to_dict(),
                    "tools": len(tools),
                    "registered": sum(1 for t in tools if t.get("enabled")),
                    "connected": server.id in self._clients
                    and getattr(self._clients[server.id], "alive", lambda: False)(),
                }
            )
        return out
