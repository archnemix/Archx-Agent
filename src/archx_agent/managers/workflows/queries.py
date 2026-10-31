"""Read and search operations for workflow definitions."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.managers.workflows.constants import MODES, STATUSES
from archx_agent.managers.workflows.records import Workflow, _workflow_from_row
from archx_agent.managers.workflows.matching import _terms


class WorkflowManagerQueriesMixin:
    """Queries responsibility for WorkflowManager."""

    def get(self, workflow_id: str) -> Workflow:
        row = self.store.query_one(
            "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
        )
        if row is None:
            raise NotFoundError(f"no workflow {workflow_id}")
        return _workflow_from_row(row)

    def find(self, ref: str) -> Workflow | None:
        row = self.store.query_one("SELECT * FROM workflows WHERE id = ?", (ref,))
        if row is None:
            row = self.store.query_one(
                "SELECT * FROM workflows WHERE name = ? ORDER BY rowid DESC LIMIT 1",
                (ref,),
            )
        return _workflow_from_row(row) if row else None

    def require(self, ref: str) -> Workflow:
        workflow = self.find(ref)
        if workflow is None:
            raise NotFoundError(f"no workflow {ref}")
        return workflow

    def search(self, query: str, *, limit: int = 20) -> list[Workflow]:
        """Candidate workflows for a text query (name and goal), newest first."""
        terms = _terms(query)
        if not terms:
            return []
        clauses = []
        params: list[Any] = []
        for term in terms:
            clauses.append("(LOWER(name) LIKE ? OR LOWER(COALESCE(goal, '')) LIKE ?)")
            params.extend([f"%{term}%", f"%{term}%"])
        params.append(int(max(1, limit)))
        rows = self.store.query(
            "SELECT * FROM workflows WHERE "
            + " OR ".join(clauses)
            + " ORDER BY rowid DESC LIMIT ?",
            params,
        )
        return [_workflow_from_row(row) for row in rows]

    def list(
        self, *, status: str | None = None, mode: str | None = None, limit: int = 20
    ) -> list[Workflow]:
        sql = "SELECT * FROM workflows"
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            if status not in STATUSES:
                raise ValidationError(f"unknown workflow status {status!r}")
            clauses.append("status = ?")
            params.append(status)
        if mode:
            if mode not in MODES:
                raise ValidationError(f"unknown workflow mode {mode!r}")
            clauses.append("mode = ?")
            params.append(mode)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_workflow_from_row(row) for row in self.store.query(sql, params)]

    def stats(self) -> dict[str, Any]:
        rows = self.store.query(
            "SELECT status, COUNT(*) AS n FROM workflows GROUP BY status", ()
        )
        return {
            "total": sum(int(row["n"]) for row in rows),
            "by_status": {row["status"]: int(row["n"]) for row in rows},
            "steps": self.table_count("workflow_steps"),
        }
