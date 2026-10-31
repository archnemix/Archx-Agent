"""Transactional write handlers for task history."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.jsonio import json_text
from archx_agent.managers.tasks.constants import _LIST_COLUMNS, _JSON_COLUMNS


class TaskManagerWritesMixin:
    """Writes responsibility for TaskManager."""

    def register_handlers(self) -> None:
        self.coordinator.register("task.create", self._apply_create)
        self.coordinator.register("task.update", self._apply_update)
        self.coordinator.register("task.log", self._apply_log)
        self.coordinator.register("task.artifact", self._apply_artifact)

    def _apply_create(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        t = payload["task"]
        tx.execute(
            "INSERT INTO tasks(id, type, title, status, conversation_id, project_id,"
            " parent_task_id, run_id, created_at, started_at, completed_at, model_id, agents,"
            " tools, resource_use, cost_estimate, input_refs, output_refs, error, unresolved,"
            " trace_event_id, version_info, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                t["id"],
                t["type"],
                t["title"],
                t["status"],
                t.get("conversation_id"),
                t.get("project_id"),
                t.get("parent_task_id"),
                t.get("run_id"),
                t["created_at"],
                t.get("started_at"),
                t.get("completed_at"),
                t.get("model_id"),
                json_text(t.get("agents") or []),
                json_text(t.get("tools") or []),
                json_text(t.get("resource_use") or {}),
                t.get("cost_estimate"),
                json_text(t.get("input_refs") or []),
                json_text(t.get("output_refs") or []),
                t.get("error"),
                json_text(t.get("unresolved") or []),
                t.get("trace_event_id"),
                json_text(t.get("version_info") or {}),
                json_text(t.get("metadata") or {}),
            ),
        )
        row = tx.query("SELECT rowid AS seq FROM tasks WHERE id = ?", (t["id"],))
        return {"id": t["id"], "seq": row[0]["seq"] if row else None}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        sets: list[str] = []
        params: list[Any] = []
        for key, value in payload["fields"].items():
            if key in _LIST_COLUMNS or key in _JSON_COLUMNS:
                value = json_text(
                    value if value is not None else ([] if key in _LIST_COLUMNS else {})
                )
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:  # pragma: no cover - callers always pass fields
            return {"id": payload["id"], "updated": 0}
        params.append(payload["id"])
        tx.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params)
        return {"id": payload["id"], "updated": len(sets)}

    def _apply_log(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        entry = payload["entry"]
        tx.execute(
            "INSERT INTO task_log(task_id, at, kind, detail, event_id) VALUES (?,?,?,?,?)",
            (
                entry["task_id"],
                entry["at"],
                entry["kind"],
                entry.get("detail"),
                entry.get("event_id"),
            ),
        )
        row = tx.query("SELECT last_insert_rowid() AS seq")
        return {"seq": row[0]["seq"] if row else None}

    def _apply_artifact(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        a = payload["artifact"]
        tx.execute(
            "INSERT INTO artifacts(id, task_id, project_id, kind, name, path, rel_path,"
            " checksum, size, mime, created_at, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                a["id"],
                a.get("task_id"),
                a.get("project_id"),
                a["kind"],
                a["name"],
                a["path"],
                a.get("rel_path"),
                a.get("checksum"),
                a.get("size"),
                a.get("mime"),
                a["created_at"],
                json_text(a.get("metadata") or {}),
            ),
        )
        return {"id": a["id"]}
