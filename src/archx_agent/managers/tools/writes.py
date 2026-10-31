"""Transactional write handlers for tool execution."""

from __future__ import annotations

import json
from typing import Any

from archx_agent.helpers.exceptions import (
    NotFoundError,
)
from archx_agent.helpers.jsonio import json_text


class ToolManagerWritesMixin:
    """Writes responsibility for ToolManager."""

    def register_handlers(self) -> None:
        self.coordinator.register("tool.record", self._apply_record)
        self.coordinator.register("tool.finish", self._apply_finish)

    def _apply_record(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run = payload["run"]
        seq = int(
            tx.query("SELECT COALESCE(MAX(seq), 0) + 1 AS s FROM tool_runs")[0]["s"]
        )
        tx.execute(
            "INSERT INTO tool_runs(id, task_id, tool_name, arguments, status, result, started_at,"
            " ended_at, duration_ms, error, permission_id, trace_event_id, approval_id, dry_run,"
            " truncated, seq) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run["id"],
                run.get("task_id"),
                run["tool"],
                json_text(run.get("arguments") or {}),
                run["status"],
                None,
                run["started_at"],
                run.get("ended_at"),
                run.get("duration_ms"),
                run.get("error"),
                run.get("permission_id"),
                run.get("trace_event_id"),
                run.get("approval_id"),
                1 if run.get("dry_run") else 0,
                1 if run.get("truncated") else 0,
                seq,
            ),
        )
        return {"id": run["id"], "seq": seq}

    def _apply_finish(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "UPDATE tool_runs SET status=?, result=?, ended_at=?, duration_ms=?, error=?,"
            " permission_id=COALESCE(?, permission_id), approval_id=COALESCE(?, approval_id),"
            " trace_event_id=COALESCE(?, trace_event_id), truncated=?"
            " WHERE id=?",
            (
                payload["status"],
                json_text(payload.get("result") or {}),
                payload.get("ended_at"),
                payload.get("duration_ms"),
                payload.get("error"),
                payload.get("permission_id"),
                payload.get("approval_id"),
                payload.get("trace_event_id"),
                1 if payload.get("truncated") else 0,
                payload["id"],
            ),
        )
        return {"id": payload["id"], "status": payload["status"]}

    def runs(self, *, tool: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        sql = "SELECT * FROM tool_runs"
        params: list[Any] = []
        if tool:
            sql += " WHERE tool_name = ?"
            params.append(tool)
        sql += " ORDER BY seq DESC, started_at DESC LIMIT ?"
        params.append(int(limit))
        rows = self.store.query(sql, params)
        for row in rows:
            if row.get("arguments"):
                try:
                    row["arguments"] = json.loads(row["arguments"])
                except json.JSONDecodeError:  # pragma: no cover
                    pass
            if row.get("result"):
                try:
                    row["result"] = json.loads(row["result"])
                except json.JSONDecodeError:  # pragma: no cover
                    pass
        return rows

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.store.query_one("SELECT * FROM tool_runs WHERE id = ?", (run_id,))
        if row is None:
            raise NotFoundError(f"no tool run {run_id}")
        return row
