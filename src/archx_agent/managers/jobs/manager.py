"""Composition and shared configuration for durable jobs."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import ConflictError
from archx_agent.helpers.timeutil import new_id
from archx_agent.managers.base import BaseManager
from archx_agent.managers.jobs.constants import JOB_TABLES
from archx_agent.managers.jobs.records import Job
from archx_agent.managers.jobs.writes import JobManagerWritesMixin
from archx_agent.managers.jobs.submission import JobManagerSubmissionMixin
from archx_agent.managers.jobs.lifecycle import JobManagerLifecycleMixin
from archx_agent.managers.jobs.controls import JobManagerControlsMixin
from archx_agent.managers.jobs.recovery import JobManagerRecoveryMixin
from archx_agent.managers.jobs.queries import JobManagerQueriesMixin


class JobManager(
    JobManagerWritesMixin,
    JobManagerSubmissionMixin,
    JobManagerLifecycleMixin,
    JobManagerControlsMixin,
    JobManagerRecoveryMixin,
    JobManagerQueriesMixin,
    BaseManager,
):
    """Durable queue with priorities, deadlines, attempts, pause and recovery."""

    tables = JOB_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        events=None,
        config=None,
        tasks=None,
        instance: str | None = None,
    ) -> None:
        self.config = config
        self.tasks = tasks
        self.instance = instance or new_id("wk_")
        super().__init__(store, coordinator, events=events)

    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001 - a bad config must not stop the queue
            return default

    def _log(self, task_id: str | None, kind: str, detail: str | None = None) -> None:
        """Append to the *task* timeline. The job does not keep a second history."""
        if not task_id or self.tasks is None:
            return
        try:
            self.tasks.log(task_id, kind, detail=detail)
        except Exception:  # noqa: BLE001 - a closed task must not break the queue
            return

    def _require_open(self, job_id: str, action: str) -> Job:
        job = self.get(job_id)
        if job.terminal:
            raise ConflictError(f"cannot {action} job {job_id}: it is {job.status}")
        return job

    def _require_running(self, job_id: str, action: str) -> Job:
        job = self.get(job_id)
        if job.status != "running":
            raise ConflictError(
                f"cannot {action} job {job_id}: it is {job.status}, not running"
            )
        return job
