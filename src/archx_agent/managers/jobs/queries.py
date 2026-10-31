"""Read and search operations for durable jobs."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.managers.jobs.constants import JOB_KINDS, STATUSES
from archx_agent.managers.jobs.records import Job, _from_row


class JobManagerQueriesMixin:
    """Queries responsibility for JobManager."""

    def get(self, job_id: str) -> Job:
        row = self.store.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            raise NotFoundError(f"no job {job_id}")
        return _from_row(row)

    def find(self, ref: str) -> Job | None:
        row = self.store.query_one("SELECT * FROM jobs WHERE id = ?", (ref,))
        if row is None:
            rows = self.store.query(
                "SELECT * FROM jobs WHERE id LIKE ? ORDER BY queue_seq LIMIT 2",
                (f"{ref}%",),
            )
            if len(rows) != 1:
                return None
            row = rows[0]
        return _from_row(row)

    def require(self, ref: str) -> Job:
        job = self.find(ref)
        if job is None:
            raise NotFoundError(f"no job {ref}")
        return job

    def list(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[Job]:
        sql = "SELECT * FROM jobs"
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            if status not in STATUSES:
                raise ValidationError(f"unknown job status {status!r}")
            clauses.append("status = ?")
            params.append(status)
        if kind:
            if kind not in JOB_KINDS:
                raise ValidationError(f"unknown job kind {kind!r}")
            clauses.append("kind = ?")
            params.append(kind)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY queue_seq DESC LIMIT ?"
        params.append(int(max(1, limit)))
        return [_from_row(row) for row in self.store.query(sql, params)]

    def queue(self) -> list[Job]:
        """What would run next, in the order it would run."""
        rows = self.store.query(
            "SELECT * FROM jobs WHERE status = 'queued' ORDER BY priority DESC, queue_seq ASC"
        )
        return [_from_row(row) for row in rows]

    def protected_task_ids(self) -> set[str]:
        """Tasks a durable job still owns, so a crash sweep must not close them.

        A *paused* job will continue its task, and so will a job that was resumed into
        ``queued`` and has already started once. Sweeping either would turn a resumable
        run into an "interrupted" one and force a duplicate task on resume.
        """
        rows = self.store.query(
            "SELECT task_id FROM jobs WHERE task_id IS NOT NULL AND ("
            " status = 'paused' OR (status = 'queued' AND (attempts > 0 OR cursor > 0)))",
            (),
        )
        return {row["task_id"] for row in rows}

    def running(self) -> list[Job]:
        return [
            _from_row(row)
            for row in self.store.query(
                "SELECT * FROM jobs WHERE status = 'running' ORDER BY queue_seq"
            )
        ]

    def stats(self) -> dict[str, Any]:
        rows = self.store.query(
            "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
        )
        by_kind = self.store.query("SELECT kind, COUNT(*) AS n FROM jobs GROUP BY kind")
        return {
            "total": sum(int(row["n"]) for row in rows),
            "by_status": {row["status"]: int(row["n"]) for row in rows},
            "by_kind": {row["kind"]: int(row["n"]) for row in by_kind},
            "queued": int(
                self.store.scalar("SELECT COUNT(*) FROM jobs WHERE status='queued'")
                or 0
            ),
            "running": int(
                self.store.scalar("SELECT COUNT(*) FROM jobs WHERE status='running'")
                or 0
            ),
            "paused": int(
                self.store.scalar("SELECT COUNT(*) FROM jobs WHERE status='paused'")
                or 0
            ),
        }
