"""Read and search operations for task history."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.result import Result
from archx_agent.managers.tasks.constants import TASK_STATUSES
from archx_agent.managers.tasks.records import Task, _task_from_row
from archx_agent.managers.tasks.validation import _validate_type
from archx_agent.managers.tasks.matching import _terms


class TaskManagerQueriesMixin:
    """Queries responsibility for TaskManager."""

    def search(
        self,
        query: str,
        *,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[Task]:
        """Candidate tasks for a text query (title and type), newest first.

        Matching is deliberately broad - any query term - and the caller ranks the
        candidates. Doing the ranking in SQL would hide *why* something matched.
        """
        terms = _terms(query)
        if not terms:
            return []
        clauses = ["(" + " OR ".join("LOWER(title) LIKE ?" for _ in terms) + ")"]
        params: list[Any] = [f"%{term}%" for term in terms]
        if status:
            clauses.append("status = ?")
            params.append(status)
        if kind:
            clauses.append("type = ?")
            params.append(kind)
        params.append(int(max(1, limit)))
        rows = self.store.query(
            "SELECT rowid AS seq, * FROM tasks WHERE "
            + " AND ".join(clauses)
            + " ORDER BY rowid DESC LIMIT ?",
            params,
        )
        return [_task_from_row(row) for row in rows]

    def get(self, task_id: str) -> Task:
        row = self.store.query_one(
            "SELECT rowid AS seq, * FROM tasks WHERE id = ?", (task_id,)
        )
        if row is None:
            raise NotFoundError(f"no task {task_id}")
        return _task_from_row(row)

    def find(self, task_id: str) -> Result[Task]:
        row = self.store.query_one(
            "SELECT rowid AS seq, * FROM tasks WHERE id = ?", (task_id,)
        )
        if row is None:
            return Result.err(NotFoundError(f"no task {task_id}"))
        return Result.ok(_task_from_row(row))

    def list(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        parent_task_id: str | None = None,
        since: str | None = None,
        limit: int = 20,
        newest_first: bool = True,
    ) -> list[Task]:
        sql = "SELECT rowid AS seq, * FROM tasks"
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            if status not in TASK_STATUSES:
                raise ValidationError(f"unknown task status {status!r}")
            clauses.append("status = ?")
            params.append(status)
        if kind:
            clauses.append("type = ?")
            params.append(_validate_type(kind))
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        if parent_task_id:
            clauses.append("parent_task_id = ?")
            params.append(parent_task_id)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rowid " + ("DESC" if newest_first else "ASC") + " LIMIT ?"
        params.append(int(limit))
        return [_task_from_row(row) for row in self.store.query(sql, params)]

    def children(self, task_id: str, *, limit: int = 100) -> list[Task]:
        return self.list(parent_task_id=task_id, limit=limit, newest_first=False)

    def tree(self, task_id: str, *, depth: int = 5) -> dict[str, Any]:
        task = self.get(task_id)
        node = task.to_dict()
        if depth > 0:
            node["children"] = [
                self.tree(child.id, depth=depth - 1) for child in self.children(task_id)
            ]
        else:
            node["children"] = []
        return node

    def stats(self) -> dict[str, Any]:
        by_status = {
            row["status"]: int(row["n"])
            for row in self.store.query(
                "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status", ()
            )
        }
        by_type = {
            row["type"]: int(row["n"])
            for row in self.store.query(
                "SELECT type, COUNT(*) AS n FROM tasks GROUP BY type ORDER BY n DESC",
                (),
            )
        }
        with_questions = int(
            self.store.scalar(
                "SELECT COUNT(*) FROM tasks WHERE unresolved NOT IN ('', '[]')"
            )
            or 0
        )
        return {
            "total": sum(by_status.values()),
            "by_status": by_status,
            "by_type": by_type,
            "with_open_questions": with_questions,
            "artifacts": self.table_count("artifacts"),
        }
