"""McpManager: registry operations."""

from __future__ import annotations
from typing import Any
from archx_agent.adapters.mcp_client import (
    McpToolInfo,
)
from ..tools import ToolSpec
from .records import sanitize_tool_name, McpServer, _types_from_schema


class McpManagerRegistryMixin:
    @staticmethod
    def spec_name(server_name: str, tool_name: str) -> str:
        return f"mcp.{sanitize_tool_name(server_name)}.{sanitize_tool_name(tool_name)}"

    def _spec_for(self, server: McpServer, tool: McpToolInfo) -> ToolSpec:
        inputs, types, required = _types_from_schema(tool.input_schema)
        return ToolSpec(
            name=self.spec_name(server.name, tool.name),
            summary=(tool.description or f"MCP tool {tool.name}")[:200],
            capability="mcp.call",
            risk="medium" if server.trusted else "high",
            inputs=inputs,
            required=required,
            types=types,
            supports_dry_run=False,
            side_effects=f"calls {tool.name} on MCP server {server.name}",
            builtin=False,
            origin=f"mcp:{server.name}",
        )

    def _handler(self, server: McpServer, tool: McpToolInfo):
        remote = tool.name
        server_ref = server.id

        def call(args: dict[str, Any]) -> dict[str, Any]:
            return self.invoke(server_ref, remote, args).to_dict()

        return call

    def _register_stored(self, server: McpServer) -> list[str]:
        """Re-register the tools already recorded for a server (no reconnect needed)."""
        if self.tools is None:
            return []
        registered: list[str] = []
        for row in self.tools_of(server.id):
            info = McpToolInfo(
                name=row["name"],
                description=row.get("description") or "",
                input_schema=row.get("schema") or {},
                annotations=row.get("annotations") or {},
            )
            self.tools.declare_spec(
                self._spec_for(server, info), self._handler(server, info)
            )
            registered.append(self.spec_name(server.name, info.name))
        return registered

    def _unregister(self, server: McpServer) -> None:
        if self.tools is None:
            return
        for row in self.tools_of(server.id):
            try:
                self.tools.unregister_spec(self.spec_name(server.name, row["name"]))
            except Exception:  # noqa: BLE001 - already gone
                continue

    def registered_tool_name(self, ref: str, tool_name: str) -> str:
        return self.spec_name(self.server(ref).name, tool_name)

    def restore(self) -> dict[str, int]:
        """Re-register callable tools after a restart.

        Registered tools live in memory; the *decision* to allow them lives in the
        database. Without this, every new CLI process would need a `sync` before a
        previously-trusted server's tools could be called - and a stale registry would
        silently disagree with what `mcp servers` reports.
        """
        servers = 0
        tools = 0
        for server in self.servers():
            if not (server.trusted and server.enabled):
                continue
            if not self._cfg("mcp.client_enabled", True):
                continue
            registered = self._register_stored(server)
            if registered:
                servers += 1
                tools += len(registered)
        return {"servers": servers, "tools": tools}
