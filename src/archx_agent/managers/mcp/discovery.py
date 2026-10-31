"""McpManager: discovery operations."""

from __future__ import annotations
from typing import Any
from archx_agent.adapters.mcp_client import (
    PROTOCOL_VERSION,
)
from archx_agent.helpers.exceptions import (
    MCPServerError,
    MCPProtocolError,
)
from archx_agent.helpers.timeutil import iso_now
from .records import McpServer


class McpManagerDiscoveryMixin:
    def sync(self, ref: str) -> dict[str, Any]:
        """Connect, discover tools, and (if trusted+enabled) register them."""
        server = self.server(ref)
        try:
            client = self._client(server)
            init = client.initialize()
            discovered = client.list_tools()
            specs = [self._spec_for(server, tool) for tool in discovered]
            if len({spec.name for spec in specs}) != len(specs):
                raise MCPProtocolError(
                    "discovered tool names collide after registry sanitization"
                )
        except MCPServerError as exc:
            self._close(server.id)
            self._record_error(server, exc.message)
            raise
        self._write(
            "mcp.server.update",
            {
                "id": server.id,
                "fields": {
                    "protocol_version": client.protocol_version or PROTOCOL_VERSION,
                    "last_connected_at": iso_now(),
                    "last_status": "connected",
                    "last_error": None,
                    "tools_count": len(discovered),
                },
                "updated_at": iso_now(),
            },
        )
        callable_now = server.enabled and server.trusted
        known = {row["name"] for row in self.tools_of(server.id)}
        seen: set[str] = set()
        registered: list[str] = []
        for tool, spec in zip(discovered, specs):
            seen.add(tool.name)
            self._write(
                "mcp.tool.upsert",
                {
                    "tool": {
                        "server_id": server.id,
                        "name": tool.name,
                        "description": tool.description,
                        "schema": tool.input_schema,
                        "enabled": callable_now,
                        "discovered_at": iso_now(),
                        "capability": "mcp.call",
                        "risk": spec.risk,
                        "annotations": tool.annotations,
                    }
                },
            )
            if callable_now and self.tools is not None:
                self.tools.declare_spec(spec, self._handler(server, tool))
                registered.append(spec.name)
        for stale in known - seen:
            self._write("mcp.tool.delete", {"server_id": server.id, "name": stale})
            if self.tools is not None:
                name = self.spec_name(server.name, stale)
                try:
                    self.tools.unregister_spec(name)
                except Exception:  # noqa: BLE001 - it may never have been registered
                    pass
        self.trace(
            "mcp",
            "server.synced",
            payload={
                "server": server.name,
                "protocol": client.protocol_version,
                "server_info": init.get("serverInfo") or {},
                "discovered": len(discovered),
                "registered": len(registered),
                "callable": callable_now,
            },
        )
        return {
            "server": server.name,
            "transport": server.transport,
            "protocol_version": client.protocol_version,
            "server_info": init.get("serverInfo") or {},
            "capabilities": init.get("capabilities") or {},
            "discovered": [t.to_dict() for t in discovered],
            "registered": registered,
            "callable": callable_now,
            "reason": None if callable_now else self._not_callable_reason(server),
        }

    def _not_callable_reason(self, server: McpServer) -> str:
        if not server.trusted and not server.enabled:
            return "the server is not trusted and not enabled"
        if not server.trusted:
            return "the server is not trusted (archx-agent mcp trust <name>)"
        return "the server is disabled (archx-agent mcp enable <name>)"

    def _record_error(self, server: McpServer, message: str) -> None:
        try:
            self._write(
                "mcp.server.update",
                {
                    "id": server.id,
                    "fields": {
                        "last_status": "error",
                        "last_error": message[:500],
                        "last_error_at": iso_now(),
                    },
                    "updated_at": iso_now(),
                },
            )
        except Exception:  # noqa: BLE001 - recording a failure must not mask it
            pass
        self.trace(
            "mcp",
            "server.sync_failed",
            status="error",
            error=message,
            payload={"server": server.name},
        )
