"""MCP client: configured servers, discovered tools, and calls that go through the checks.

A server is a program (``stdio``) or an endpoint (``http``) the user configured. Two
independent facts decide what may happen:

* **trusted** - the user said "I know what this server is";
* **enabled** - the user said "use it for now".

Neither is a permission. A discovered tool only becomes callable when the server is
trusted *and* enabled, and every call still needs a grant for ``mcp.call`` with the tool as
the subject (see ``managers/permissions.py``). A server that advertises ``fs.write`` does
not get to run it: its tool is an MCP call, and the wrapping tool has its own capability.

Discovery is recorded even for an untrusted server - "this is what it would expose" is
useful - but nothing is registered with the tool registry, so nothing can be invoked.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from archx_agent.adapters.mcp_client import (
    McpCallResult,
    McpHttpClient,
    McpStdioClient,
    McpToolInfo,
    PROTOCOL_VERSION,
)
from archx_agent.helpers.exceptions import (
    ConflictError,
    ExtensionTrustError,
    MCPServerError,
    NotFoundError,
    ValidationError,
)
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager
from .tools import ToolManager, ToolSpec

MCP_TABLES = ("mcp_servers", "mcp_tools")

TRANSPORTS = ("stdio", "http")

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def sanitize_tool_name(value: str) -> str:
    cleaned = _SAFE.sub("_", (value or "").strip())
    return cleaned.strip("._") or "tool"


@dataclass
class McpServer:
    id: str
    name: str
    transport: str
    enabled: bool
    trusted: bool
    created_at: str
    updated_at: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    protocol_version: str | None = None
    last_connected_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None
    tools_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "transport": self.transport,
            "enabled": self.enabled,
            "trusted": self.trusted,
            "command": self.command,
            "args": self.args,
            "url": self.url,
            "env": sorted(self.env),
            "headers": sorted(self.headers),
            "protocol_version": self.protocol_version,
            "last_connected_at": self.last_connected_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "tools_count": self.tools_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _server_from_row(row: dict[str, Any]) -> McpServer:
    def _obj(raw: Any) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:  # pragma: no cover - corrupted row
            return {}
        return value if isinstance(value, dict) else {}

    return McpServer(
        id=row["id"],
        name=row["name"],
        transport=row["transport"],
        enabled=bool(row["enabled"]),
        trusted=bool(row["trusted"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        command=row.get("command"),
        args=list(json.loads(row["args"])) if row.get("args") else [],
        url=row.get("url"),
        env=_obj(row.get("env")),
        headers=_obj(row.get("headers")),
        protocol_version=row.get("protocol_version"),
        last_connected_at=row.get("last_connected_at"),
        last_status=row.get("last_status"),
        last_error=row.get("last_error"),
        last_error_at=row.get("last_error_at"),
        tools_count=int(row.get("tools_count") or 0),
    )


def _types_from_schema(schema: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str], tuple[str, ...]]:
    """Translate a JSON Schema subset into the registry's input descriptions."""
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        properties = {}
    inputs: dict[str, str] = {}
    types: dict[str, str] = {}
    for name, spec in properties.items():
        spec = spec if isinstance(spec, dict) else {}
        raw_type = spec.get("type")
        if isinstance(raw_type, list):
            raw_type = next((t for t in raw_type if t != "null"), None)
        mapped = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "object": "json",
            "array": "json",
        }.get(str(raw_type), "json")
        inputs[str(name)] = str(spec.get("description") or f"{name} ({raw_type or 'any'})")
        types[str(name)] = mapped
    required = schema.get("required") if isinstance(schema, dict) else None
    required_names = tuple(str(x) for x in required) if isinstance(required, list) else ()
    return inputs, types, required_names


class McpManager(BaseManager):
    """Server records, discovery, and the registration seam into the tool registry."""

    tables = MCP_TABLES

    def __init__(self, store, coordinator, *, events=None, config=None, tools: ToolManager | None = None) -> None:
        self.config = config
        self.tools = tools
        self._clients: dict[str, Any] = {}
        super().__init__(store, coordinator, events=events)

    # -- config -----------------------------------------------------------
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

    # -- persistence ------------------------------------------------------
    def register_handlers(self) -> None:
        self.coordinator.register("mcp.server.upsert", self._apply_upsert)
        self.coordinator.register("mcp.server.update", self._apply_update)
        self.coordinator.register("mcp.server.delete", self._apply_delete)
        self.coordinator.register("mcp.tool.upsert", self._apply_tool_upsert)
        self.coordinator.register("mcp.tool.delete", self._apply_tool_delete)
        self.coordinator.register("mcp.tool.enable", self._apply_tool_enable)

    def _apply_upsert(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        s = payload["server"]
        tx.execute(
            "INSERT INTO mcp_servers(id, name, transport, command, args, url, env, enabled, trusted,"
            " created_at, updated_at, headers, protocol_version, last_status, tools_count)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                s["id"], s["name"], s["transport"], s.get("command"),
                json_text(s.get("args") or []), s.get("url"), json_text(s.get("env") or {}),
                1 if s.get("enabled") else 0, 1 if s.get("trusted") else 0,
                s["created_at"], s["updated_at"], json_text(s.get("headers") or {}),
                s.get("protocol_version"), s.get("last_status"), int(s.get("tools_count") or 0),
            ),
        )
        return {"id": s["id"]}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = dict(payload["fields"])
        sets, params = [], []
        for key, value in fields.items():
            if key in ("args", "env", "headers"):
                value = json_text(value or ([] if key == "args" else {}))
            elif key in ("enabled", "trusted"):
                value = 1 if value else 0
            sets.append(f"{key} = ?")
            params.append(value)
        sets.append("updated_at = ?")
        params.append(payload.get("updated_at") or iso_now())
        params.append(payload["id"])
        tx.execute(f"UPDATE mcp_servers SET {', '.join(sets)} WHERE id = ?", params)
        return {"id": payload["id"]}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute("DELETE FROM mcp_tools WHERE server_id = ?", (payload["id"],))
        tx.execute("DELETE FROM mcp_servers WHERE id = ?", (payload["id"],))
        return {"id": payload["id"]}

    def _apply_tool_upsert(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        t = payload["tool"]
        tx.execute(
            "INSERT INTO mcp_tools(server_id, name, description, schema, enabled, discovered_at,"
            " capability, risk, annotations, last_synced_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(server_id, name) DO UPDATE SET description=excluded.description,"
            " schema=excluded.schema, enabled=excluded.enabled, capability=excluded.capability,"
            " risk=excluded.risk, annotations=excluded.annotations,"
            " last_synced_at=excluded.last_synced_at",
            (
                t["server_id"], t["name"], t.get("description") or "", json_text(t.get("schema") or {}),
                1 if t.get("enabled") else 0, t["discovered_at"], t.get("capability"),
                t.get("risk"), json_text(t.get("annotations") or {}), t["discovered_at"],
            ),
        )
        return {"server_id": t["server_id"], "name": t["name"]}

    def _apply_tool_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "DELETE FROM mcp_tools WHERE server_id = ? AND name = ?",
            (payload["server_id"], payload["name"]),
        )
        return {"server_id": payload["server_id"], "name": payload["name"]}

    def _apply_tool_enable(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "UPDATE mcp_tools SET enabled = ? WHERE server_id = ?",
            (1 if payload.get("enabled") else 0, payload["server_id"]),
        )
        return {"server_id": payload["server_id"]}

    # -- server CRUD ------------------------------------------------------
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
            raise ValidationError(f"unknown transport {transport!r} (expected one of {list(TRANSPORTS)})")
        if self._find(name) is not None:
            raise ConflictError(f"an MCP server named {name!r} already exists")
        if transport == "stdio":
            if not command:
                raise ValidationError("a stdio server needs --command (the program to run)")
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
            raise ValidationError(f"cannot update MCP server field(s): {', '.join(sorted(unknown))}")
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
            "mcp", "server.trusted" if trusted else "server.untrusted", payload=updated.to_dict()
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

    def tools_of(self, ref: str, *, include_disabled: bool = True) -> list[dict[str, Any]]:
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

    # -- connections ------------------------------------------------------
    def _client(self, server: McpServer):
        existing = self._clients.get(server.id)
        if existing is not None:
            if getattr(existing, "alive", lambda: False)():
                return existing
            self._clients.pop(server.id, None)
        if server.transport == "stdio":
            env = dict(os.environ)
            env.update(server.env)
            client = McpStdioClient(
                [server.command or "", *server.args],
                name=server.name,
                env=env,
                timeout=self.client_timeout,
            )
        else:
            client = McpHttpClient(
                server.url or "",
                name=server.name,
                headers=server.headers,
                timeout=self.client_timeout,
            )
        self._clients[server.id] = client
        return client

    def _close(self, server_id: str) -> None:
        client = self._clients.pop(server_id, None)
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - closing must not raise
                pass

    def close(self) -> None:
        for server_id in list(self._clients):
            self._close(server_id)

    # -- discovery --------------------------------------------------------
    def sync(self, ref: str) -> dict[str, Any]:
        """Connect, discover tools, and (if trusted+enabled) register them."""
        server = self.server(ref)
        try:
            client = self._client(server)
            init = client.initialize()
            discovered = client.list_tools()
        except MCPServerError as exc:
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
        for tool in discovered:
            seen.add(tool.name)
            spec = self._spec_for(server, tool)
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
        self.trace("mcp", "server.sync_failed", status="error", error=message,
                   payload={"server": server.name})

    # -- tool specs -------------------------------------------------------
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
            self.tools.declare_spec(self._spec_for(server, info), self._handler(server, info))
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

    # -- calls ------------------------------------------------------------
    def invoke(self, ref: str, tool_name: str, arguments: Mapping[str, Any] | None = None,
               *, timeout: float | None = None) -> McpCallResult:
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
            return client.call_tool(tool_name, arguments, timeout=timeout or self.client_timeout)
        except MCPServerError as exc:
            self._record_error(server, exc.message)
            raise

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


__all__ = ["MCP_TABLES", "TRANSPORTS", "McpManager", "McpServer", "sanitize_tool_name"]
