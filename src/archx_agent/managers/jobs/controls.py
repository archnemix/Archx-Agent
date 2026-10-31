"""Controls operations for durable jobs."""

from __future__ import annotations

from archx_agent.helpers.exceptions import ConflictError, NotFoundError
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.jobs.constants import PAUSABLE_KINDS
from archx_agent.managers.jobs.records import Job


class JobManagerControlsMixin:
    """Controls responsibility for JobManager."""

    def pause(self, job_id: str, *, reason: str = "paused by the user") -> Job:
        job = self.get(job_id)
        if job.status == "paused":
            raise ConflictError(f"job {job_id} is already paused")
        if job.terminal or job.status == "interrupted":
            raise ConflictError(f"job {job_id} is {job.status}; nothing to pause")
        if job.status == "queued":
            paused = self._update(
                job_id, status="paused", control=None, message=reason[:500]
            )
            self._log(paused.task_id, "job_paused", reason)
            self.trace(
                "task",
                "job.paused",
                status="ok",
                task_id=paused.task_id,
                payload={"job_id": job_id, "before_start": True, "reason": reason},
            )
            return paused
        if job.kind not in PAUSABLE_KINDS:
            raise ConflictError(
                f"a running {job.kind} job cannot be paused (it owns a child process); "
                "cancel it instead, or pause it before it starts"
            )
        updated = self._update(job_id, control="pause", message="pause requested"[:500])
        self.trace(
            "task",
            "job.pause_requested",
            status="ok",
            task_id=updated.task_id,
            payload={"job_id": job_id, "reason": reason},
        )
        return updated

    def resume(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status != "paused":
            raise ConflictError(f"job {job_id} is {job.status}, not paused")
        resumed = self._update(
            job_id,
            status="queued",
            requeued_at=iso_now(),
            control=None,
            message=f"resumed from step {job.cursor}" if job.cursor else "resumed",
        )
        self._log(resumed.task_id, "job_resumed", f"cursor {job.cursor}")
        self.trace(
            "task",
            "job.resumed",
            status="ok",
            task_id=resumed.task_id,
            payload={"job_id": job_id, "cursor": job.cursor},
        )
        return resumed

    def cancel(self, job_id: str, *, reason: str = "cancelled by the user") -> Job:
        job = self.get(job_id)
        if job.terminal:
            raise ConflictError(f"job {job_id} already {job.status}")
        if job.status == "interrupted":
            return self._update(
                job_id,
                status="cancelled",
                cancelled=1,
                error=reason,
                ended_at=iso_now(),
            )
        if job.status in ("queued", "paused"):
            job = self._update(
                job_id,
                status="cancelled",
                cancelled=1,
                error=reason[:2000],
                ended_at=iso_now(),
                control=None,
            )
            self._log(job.task_id, "job_cancelled", reason)
            self.trace(
                "task",
                "job.cancelled",
                status="ok",
                task_id=job.task_id,
                payload={"job_id": job_id, "reason": reason, "before_start": True},
            )
            return job
        updated = self._update(
            job_id, control="cancel", message="cancel requested"[:500]
        )
        self.trace(
            "task",
            "job.cancel_requested",
            status="ok",
            task_id=updated.task_id,
            payload={"job_id": job_id, "reason": reason},
        )
        return updated

    def retry(self, job_id: str, *, force: bool = False) -> Job:
        job = self.get(job_id)
        if job.status == "completed":
            raise ConflictError(
                f"job {job_id} completed; submit a new job instead of retrying"
            )
        if job.status == "running":
            raise ConflictError(f"job {job_id} is running; cancel it first")
        if job.attempts >= job.max_attempts and not force:
            raise ConflictError(
                f"job {job_id} used all {job.max_attempts} attempt(s); pass force to retry anyway"
            )
        retried = self._update(
            job_id,
            status="queued",
            control=None,
            error=None,
            ended_at=None,
            requeued_at=iso_now(),
            message="retried by the user",
            **(
                {"max_attempts": job.attempts + 1}
                if force and job.attempts >= job.max_attempts
                else {}
            ),
        )
        self._log(retried.task_id, "job_retried", f"attempts {retried.attempts}")
        self.trace(
            "task",
            "job.retried",
            status="ok",
            task_id=retried.task_id,
            payload={"job_id": job_id, "attempts": retried.attempts, "forced": force},
        )
        return retried

    def control(self, job_id: str) -> str | None:
        """What the runner should do next: ``pause``, ``cancel`` or ``None``."""
        row = self.store.query_one("SELECT control FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            raise NotFoundError(f"no job {job_id}")
        return row["control"]
