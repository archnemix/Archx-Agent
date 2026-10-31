"""ResearchManager: writes operations."""

from __future__ import annotations

from typing import Any
from archx_agent.helpers.jsonio import json_text


class ResearchManagerWritesMixin:
    def register_handlers(self) -> None:
        self.coordinator.register("research.create", self._apply_create)
        self.coordinator.register("research.update", self._apply_update)
        self.coordinator.register("research.source", self._apply_source)
        self.coordinator.register("research.delete", self._apply_delete)

    def _apply_create(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run = payload["run"]
        tx.execute(
            "INSERT INTO research_runs(id, status, question, subquestions, report_path,"
            " report_format, created_at, completed_at, limitations, task_id, mode, plan,"
            " planned_by, coverage, evidence_count, report, error, model_id, settings,"
            " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run["id"], run["status"], run["question"],
                json_text(run.get("subquestions") or []),
                run.get("report_path"), run.get("report_format") or "markdown",
                run["created_at"], run.get("completed_at"),
                json_text(run.get("limitations") or []), run.get("task_id"),
                run.get("mode") or "local", json_text(run.get("plan") or []),
                run.get("planned_by") or "rules", float(run.get("coverage") or 0.0),
                int(run.get("evidence_count") or 0), run.get("report"), run.get("error"),
                run.get("model_id"), json_text(run.get("settings") or {}),
                run.get("updated_at") or run["created_at"],
            ),
        )
        return {"id": run["id"]}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = payload["id"]
        fields = payload["fields"]
        if not fields:
            return {"id": run_id, "updated": 0}
        columns = ", ".join(f"{name} = ?" for name in fields)
        tx.execute(
            f"UPDATE research_runs SET {columns} WHERE id = ?",
            (*fields.values(), run_id),
        )
        return {"id": run_id, "updated": 1}

    def _apply_source(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        source = payload["source"]
        tx.execute(
            "INSERT INTO research_sources(run_id, url, title, publisher, retrieved_at, excerpt,"
            " subsection, limitations, stance, kind, ref, status, error, checksum, bytes,"
            " relevance, credibility, claims, subquestion)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                source["run_id"], source["url"], source.get("title"),
                source.get("publisher"), source["retrieved_at"], source.get("excerpt"),
                source.get("subsection"), source.get("limitations"),
                source.get("stance") or "unknown", source.get("kind") or "url",
                source.get("ref"), source.get("status") or "fetched", source.get("error"),
                source.get("checksum"), source.get("bytes"), source.get("relevance"),
                source.get("credibility") or "unknown",
                json_text(source.get("claims") or []), source.get("subquestion"),
            ),
        )
        row = tx.query("SELECT last_insert_rowid() AS id")
        return {"id": int(row[0]["id"]) if row else None}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = payload["id"]
        tx.execute("DELETE FROM research_sources WHERE run_id = ?", (run_id,))
        tx.execute("DELETE FROM research_runs WHERE id = ?", (run_id,))
        return {"id": run_id, "deleted": 1}
