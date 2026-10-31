"""McpManager: writes operations."""

from __future__ import annotations
from typing import Any
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now


class McpManagerWritesMixin:
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
                s["id"],
                s["name"],
                s["transport"],
                s.get("command"),
                json_text(s.get("args") or []),
                s.get("url"),
                json_text(s.get("env") or {}),
                1 if s.get("enabled") else 0,
                1 if s.get("trusted") else 0,
                s["created_at"],
                s["updated_at"],
                json_text(s.get("headers") or {}),
                s.get("protocol_version"),
                s.get("last_status"),
                int(s.get("tools_count") or 0),
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
                t["server_id"],
                t["name"],
                t.get("description") or "",
                json_text(t.get("schema") or {}),
                1 if t.get("enabled") else 0,
                t["discovered_at"],
                t.get("capability"),
                t.get("risk"),
                json_text(t.get("annotations") or {}),
                t["discovered_at"],
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
