"""Lifecycle operations for durable jobs."""

from __future__ import annotations

from typing import Any, Mapping

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.jobs.records import Job


class JobManagerLifecycleMixin:
    """Lifecycle responsibility for JobManager."""

    def heartbeat(
        self,
        job_id: str,
        *,
        progress: float | None = None,
        message: str | None = None,
        resource_observed: Mapping[str, Any] | None = None,
        cursor: int | None = None,
    ) -> Job:
        job = self._require_running(job_id, "heartbeat")
        fields: dict[str, Any] = {}
        if progress is not None:
            fields["progress"] = max(0.0, min(1.0, float(progress)))
        if message is not None:
            fields["message"] = message[:500]
        if resource_observed is not None:
            fields["resource_observed"] = dict(resource_observed)
        if cursor is not None:
            fields["cursor"] = int(cursor)
        if not fields:
            return job
        return self._update(job_id, **fields)

    def link_task(self, job_id: str, task_id: str) -> Job:
        """Point the job at the task that records what it did."""
        return self._update(job_id, task_id=task_id)

    def finish(self, job_id: str, *, result: Mapping[str, Any] | None = None) -> Job:
        self._require_open(job_id, "finish")
        finished = self._update(
            job_id,
            status="completed",
            ended_at=iso_now(),
            progress=1.0,
            result=dict(result or {}),
            error=None,
            control=None,
            message=None,
        )
        self._log(finished.task_id, "job_completed", finished.title)
        self.trace(
            "task",
            "job.completed",
            status="ok",
            task_id=finished.task_id,
            payload={
                "job_id": job_id,
                "kind": finished.kind,
                "attempts": finished.attempts,
            },
        )
        return finished

    def fail(
        self, job_id: str, error: str, *, result: Mapping[str, Any] | None = None
    ) -> Job:
        self._require_open(job_id, "fail")
        failed = self._update(
            job_id,
            status="failed",
            ended_at=iso_now(),
            error=str(error)[:2000],
            result=dict(result or {}) if result else None,
            control=None,
        )
        self._log(failed.task_id, "job_failed", f"{failed.title}: {error}"[:500])
        self.trace(
            "task",
            "job.failed",
            status="error",
            task_id=failed.task_id,
            error=str(error)[:500],
            payload={
                "job_id": job_id,
                "kind": failed.kind,
                "attempts": failed.attempts,
            },
        )
        return failed

    def stop(
        self,
        job_id: str,
        *,
        status: str,
        message: str | None = None,
        error: str | None = None,
        cursor: int = 0,
        result: Mapping[str, Any] | None = None,
    ) -> Job:
        """End a run the runner stopped itself (pause or cancel honoured)."""
        if status not in ("paused", "cancelled"):
            raise ValidationError(
                f"stop() ends a run as paused or cancelled, not {status!r}"
            )
        fields: dict[str, Any] = {
            "status": status,
            "control": None,
            "message": message,
            "error": error,
            "cursor": int(cursor),
        }
        if status == "cancelled":
            fields.update(ended_at=iso_now(), cancelled=1)
        if result is not None:
            fields["result"] = dict(result)
        job = self._update(job_id, **fields)
        self._log(job.task_id, f"job_{status}", message or status)
        self.trace(
            "task",
            f"job.{status}",
            status="ok",
            task_id=job.task_id,
            payload={"job_id": job_id, "cursor": cursor, "message": message},
        )
        return job
