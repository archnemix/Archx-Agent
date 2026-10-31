"""Recovery operations for durable jobs."""

from __future__ import annotations

import os
import time
from typing import Any

from archx_agent.helpers.timeutil import iso_now, parse_iso
from archx_agent.managers.jobs.records import _from_row
from archx_agent.managers.jobs.processes import _pid_alive


class JobManagerRecoveryMixin:
    """Recovery responsibility for JobManager."""

    def recover(self, *, stale_after: int | None = None) -> dict[str, Any]:
        """Repair the queue after a crash.

        A running row whose pid is dead (or which has outlived ``stale_after``
        seconds under a different worker) is either requeued - it still has
        attempts left and its kind is resumable - or marked ``interrupted`` so it
        is not silently reported as finished work.
        """
        now = time.time()
        stale_after = int(
            stale_after
            if stale_after is not None
            else self._cfg("scheduler.stale_after_seconds", 900)
        )
        rows = self.store.query("SELECT * FROM jobs WHERE status = 'running'")
        requeued: list[str] = []
        interrupted: list[str] = []
        skipped: list[str] = []
        for row in rows:
            job = _from_row(row)
            if _pid_alive(job.pid):
                same_process = job.pid == os.getpid()
                fresh = True
                if job.started_at:
                    try:
                        fresh = (
                            now - parse_iso(job.started_at).timestamp() < stale_after
                        )
                    except ValueError:  # pragma: no cover - defensive
                        fresh = True
                if same_process or fresh:
                    skipped.append(job.id)
                    continue
            if job.attempts < job.max_attempts:
                self._update(
                    job.id,
                    status="queued",
                    worker=None,
                    pid=None,
                    requeued_at=iso_now(),
                    message="requeued after its worker disappeared",
                )
                self._log(
                    job.task_id,
                    "job_requeued",
                    f"attempts {job.attempts}/{job.max_attempts}",
                )
                requeued.append(job.id)
            else:
                self._update(
                    job.id,
                    status="interrupted",
                    ended_at=iso_now(),
                    error="the worker running this job disappeared",
                )
                self._log(job.task_id, "job_interrupted", "worker disappeared")
                interrupted.append(job.id)
            self.trace(
                "task",
                "job.recovered",
                status="warning",
                task_id=job.task_id,
                payload={
                    "job_id": job.id,
                    "outcome": "requeued" if job.id in requeued else "interrupted",
                    "attempts": job.attempts,
                },
            )
        return {
            "requeued": len(requeued),
            "interrupted": len(interrupted),
            "skipped": len(skipped),
            "requeued_ids": requeued,
            "interrupted_ids": interrupted,
            "skipped_ids": skipped,
        }

    def reap_expired(self) -> dict[str, Any]:
        """Fail running jobs whose hard deadline has passed.

        No automatic retry: a job killed mid-flight may already have had side
        effects, so the scheduler reports the timeout instead of repeating it.
        """
        rows = self.store.query(
            "SELECT * FROM jobs WHERE status = 'running' AND deadline IS NOT NULL"
        )
        expired: list[str] = []
        now = time.time()
        for row in rows:
            job = _from_row(row)
            if not job.expired(now):
                continue
            self._update(
                job.id,
                status="failed",
                ended_at=iso_now(),
                error=f"timed out after {job.timeout_seconds}s (hard deadline)",
                control=None,
            )
            self._log(job.task_id, "job_timed_out", f"after {job.timeout_seconds}s")
            self.trace(
                "task",
                "job.timed_out",
                status="error",
                task_id=job.task_id,
                error="hard deadline passed",
                payload={"job_id": job.id, "timeout": job.timeout_seconds},
            )
            expired.append(job.id)
        return {"expired": len(expired), "ids": expired}
