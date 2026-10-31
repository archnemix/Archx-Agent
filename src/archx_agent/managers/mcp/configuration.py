"""McpManager: configuration operations."""

from __future__ import annotations
import json
from typing import Any, Mapping
from archx_agent.helpers.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now, new_id
from .records import TRANSPORTS, McpServer, _server_from_row


class McpManagerConfigurationMixin:
    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001
            return default

    @property
    def client_timeout(self) -> float:
        return float(self._cfg("mcp.client_timeout_seconds", 20))

    def add_server(
        self,
        name: str,
        *,
        transport: str = "stdio",
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        env: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        enabled: bool = False,
        trusted: bool = False,
    ) -> McpServer:
        name = (name or "").strip()
        if not name:
            raise ValidationError("an MCP server needs a name")
        if transport not in TRANSPORTS:
            raise ValidationError(
                f"unknown transport {transport!r} (expected one of {list(TRANSPORTS)})"
            )
        if self._find(name) is not None:
            raise ConflictError(f"an MCP server named {name!r} already exists")
        if transport == "stdio":
            if not command:
                raise ValidationError(
                    "a stdio server needs --command (the program to run)"
                )
            if url:
                raise ValidationError("a stdio server does not take --url")
        else:
            if not url:
                raise ValidationError("an http server needs --url")
            if command:
                raise ValidationError("an http server does not take --command")
        now = iso_now()
        server = McpServer(
            id=new_id("ms_"),
            name=name,
            transport=transport,
            enabled=enabled,
            trusted=trusted,
            created_at=now,
            updated_at=now,
            command=command,
            args=list(args or []),
            url=url,
            env={str(k): str(v) for k, v in (env or {}).items()},
            headers={str(k): str(v) for k, v in (headers or {}).items()},
        )
        self._write(
            "mcp.server.upsert",
            {
                "server": {
                    "id": server.id,
                    "name": server.name,
                    "transport": server.transport,
                    "command": server.command,
                    "args": server.args,
                    "url": server.url,
                    "env": server.env,
                    "headers": server.headers,
                    "enabled": server.enabled,
                    "trusted": server.trusted,
                    "created_at": server.created_at,
                    "updated_at": server.updated_at,
                    "protocol_version": None,
                    "last_status": "never connected",
                    "tools_count": 0,
                }
            },
        )
        self.trace("mcp", "server.added", payload=server.to_dict())
        return server

    def servers(self) -> list[McpServer]:
        rows = self.store.query("SELECT * FROM mcp_servers ORDER BY name")
        return [_server_from_row(row) for row in rows]

    def _find(self, ref: str) -> McpServer | None:
        row = self.store.query_one(
            "SELECT * FROM mcp_servers WHERE id = ? OR name = ?", (ref, ref)
        )
        return _server_from_row(row) if row else None

    def server(self, ref: str) -> McpServer:
        found = self._find(ref)
        if found is None:
            raise NotFoundError(f"no MCP server {ref!r}")
        return found

    def update_server(self, ref: str, **fields: Any) -> McpServer:
        server = self.server(ref)
        allowed = {"enabled", "trusted", "command", "args", "url", "env", "headers"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValidationError(
                f"cannot update MCP server field(s): {', '.join(sorted(unknown))}"
            )
        if fields:
            self._write(
                "mcp.server.update",
                {"id": server.id, "fields": fields, "updated_at": iso_now()},
            )
        return self.server(server.id)

    def enable(self, ref: str, *, enabled: bool = True) -> McpServer:
        updated = self.update_server(ref, enabled=enabled)
        self._write("mcp.tool.enable", {"server_id": updated.id, "enabled": enabled})
        if enabled and updated.trusted:
            self._register_stored(updated)
        elif not enabled:
            self._unregister(updated)
        return updated

    def trust(self, ref: str, *, trusted: bool = True) -> McpServer:
        updated = self.update_server(ref, trusted=trusted)
        self.trace(
            "mcp",
            "server.trusted" if trusted else "server.untrusted",
            payload=updated.to_dict(),
        )
        if not trusted:
            self._unregister(updated)
        elif updated.enabled:
            self._register_stored(updated)
        return updated

    def remove_server(self, ref: str) -> McpServer:
        server = self.server(ref)
        self._close(server.id)
        self._unregister(server)
        self._write("mcp.server.delete", {"id": server.id})
        self.trace("mcp", "server.removed", payload={"name": server.name})
        return server

    def tools_of(
        self, ref: str, *, include_disabled: bool = True
    ) -> list[dict[str, Any]]:
        server = self.server(ref)
        sql = "SELECT * FROM mcp_tools WHERE server_id = ?"
        if not include_disabled:
            sql += " AND enabled = 1"
        rows = self.store.query(sql + " ORDER BY name", (server.id,))
        for row in rows:
            for key in ("schema", "annotations"):
                if row.get(key):
                    try:
                        row[key] = json.loads(row[key])
                    except json.JSONDecodeError:  # pragma: no cover
                        row[key] = {}
                else:
                    row[key] = {}
        return rows
