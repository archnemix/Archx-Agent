"""ExtensionManager: writes operations."""

from __future__ import annotations
from typing import Any
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now


class ExtensionManagerWritesMixin:
    def register_handlers(self) -> None:
        self.coordinator.register("extension.install", self._apply_install)
        self.coordinator.register("extension.update", self._apply_update)
        self.coordinator.register("extension.delete", self._apply_delete)
        self.coordinator.register("extension.tool.upsert", self._apply_tool_upsert)
        self.coordinator.register("extension.tool.delete", self._apply_tool_delete)

    def _apply_install(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        e = payload["extension"]
        tx.execute(
            "INSERT INTO extensions(id, name, version, path, manifest, trust, enabled,"
            " installed_at, updated_at, last_error, manifest_hash, trusted_by, trusted_at, notes)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                e["id"],
                e["name"],
                e["version"],
                e.get("path"),
                json_text(e["manifest"]),
                e.get("trust", "untrusted"),
                1 if e.get("enabled") else 0,
                e["installed_at"],
                e["updated_at"],
                e.get("last_error"),
                e.get("manifest_hash"),
                e.get("trusted_by"),
                e.get("trusted_at"),
                e.get("notes"),
            ),
        )
        return {"id": e["id"]}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = dict(payload["fields"])
        sets, params = [], []
        for key, value in fields.items():
            if key == "manifest":
                value = json_text(value)
            elif key in ("enabled",):
                value = 1 if value else 0
            sets.append(f"{key} = ?")
            params.append(value)
        sets.append("updated_at = ?")
        params.append(payload.get("updated_at") or iso_now())
        params.append(payload["id"])
        tx.execute(f"UPDATE extensions SET {', '.join(sets)} WHERE id = ?", params)
        return {"id": payload["id"]}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "DELETE FROM extension_tools WHERE extension_id = ?", (payload["id"],)
        )
        tx.execute("DELETE FROM extensions WHERE id = ?", (payload["id"],))
        return {"id": payload["id"]}

    def _apply_tool_upsert(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        t = payload["tool"]
        tx.execute(
            "INSERT INTO extension_tools(id, extension_id, name, description, capability, risk,"
            " schema, entry, enabled, discovered_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(extension_id, name) DO UPDATE SET description=excluded.description,"
            " capability=excluded.capability, risk=excluded.risk, schema=excluded.schema,"
            " entry=excluded.entry, enabled=excluded.enabled, discovered_at=excluded.discovered_at",
            (
                t["id"],
                t["extension_id"],
                t["name"],
                t.get("description") or "",
                t.get("capability"),
                t.get("risk"),
                json_text(t.get("schema") or {}),
                json_text(t.get("entry") or {}),
                1 if t.get("enabled") else 0,
                t["discovered_at"],
            ),
        )
        return {"id": t["id"]}

    def _apply_tool_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "DELETE FROM extension_tools WHERE extension_id = ? AND name = ?",
            (payload["extension_id"], payload["name"]),
        )
        return {"extension_id": payload["extension_id"], "name": payload["name"]}
