"""Transactional write handlers for workflow definitions."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now


class WorkflowManagerWritesMixin:
    """Writes responsibility for WorkflowManager."""

    def register_handlers(self) -> None:
        self.coordinator.register("workflow.create", self._apply_create)
        self.coordinator.register("workflow.update", self._apply_update)
        self.coordinator.register("workflow.step", self._apply_step)
        self.coordinator.register("workflow.step_update", self._apply_step_update)

    def _apply_create(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        w = payload["workflow"]
        tx.execute(
            "INSERT INTO workflows(id, name, mode, status, goal, definition, model_id, task_id,"
            " conversation_id, created_at, updated_at, started_at, finished_at, error, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                w["id"],
                w["name"],
                w["mode"],
                w["status"],
                w.get("goal"),
                json_text(w["definition"]),
                w.get("model_id"),
                w.get("task_id"),
                w.get("conversation_id"),
                w["created_at"],
                w["updated_at"],
                w.get("started_at"),
                w.get("finished_at"),
                w.get("error"),
                json_text(w.get("metadata") or {}),
            ),
        )
        return {"id": w["id"]}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = dict(payload["fields"])
        if "definition" in fields:
            fields["definition"] = json_text(fields["definition"])
        if "metadata" in fields:
            fields["metadata"] = json_text(fields["metadata"] or {})
        sets = ", ".join(f"{key} = ?" for key in fields)
        tx.execute(
            f"UPDATE workflows SET {sets}, updated_at = ? WHERE id = ?",
            [*fields.values(), iso_now(), payload["id"]],
        )
        return {"id": payload["id"]}

    def _apply_step(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        s = payload["step"]
        tx.execute(
            "INSERT INTO workflow_steps(id, workflow_id, seq, kind, title, spec, status,"
            " started_at, ended_at, output, error, task_id, tokens, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                s["id"],
                s["workflow_id"],
                s["seq"],
                s["kind"],
                s.get("title"),
                json_text(s.get("spec") or {}),
                s["status"],
                s.get("started_at"),
                s.get("ended_at"),
                s.get("output"),
                s.get("error"),
                s.get("task_id"),
                int(s.get("tokens") or 0),
                json_text(s.get("metadata") or {}),
            ),
        )
        return {"id": s["id"], "seq": s["seq"]}

    def _apply_step_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = dict(payload["fields"])
        for key in ("metadata", "spec"):
            if key in fields:
                fields[key] = json_text(fields[key] or {})
        sets = ", ".join(f"{key} = ?" for key in fields)
        tx.execute(
            f"UPDATE workflow_steps SET {sets} WHERE id = ?",
            [*fields.values(), payload["id"]],
        )
        return {"id": payload["id"]}
