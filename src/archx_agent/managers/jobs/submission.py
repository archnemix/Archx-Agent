"""Submission operations for durable jobs."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.jobs.constants import JOB_KINDS, DEFAULT_ESTIMATES
from archx_agent.managers.jobs.records import Job, _from_row
from archx_agent.managers.jobs.validation import _int


class JobManagerSubmissionMixin:
    """Submission responsibility for JobManager."""

    def enqueue(
        self,
        kind: str,
        title: str | None = None,
        payload: Mapping[str, Any] | None = None,
        *,
        priority: int = 5,
        timeout: int | None = None,
        max_attempts: int | None = None,
        resource_estimate: Mapping[str, Any] | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
        dedupe_key: str | None = None,
    ) -> Job:
        """Accept work. Returns the job - which is *queued*, never "done"."""
        if kind not in JOB_KINDS:
            raise ValidationError(
                f"unknown job kind {kind!r} (known: {', '.join(JOB_KINDS)})"
            )
        priority = _int(priority, "priority", lo=0, hi=9)
        max_attempts = _int(
            max_attempts
            if max_attempts is not None
            else self._cfg("scheduler.max_attempts", 2),
            "max_attempts",
            lo=1,
            hi=100,
        )
        timeout = _int(
            timeout
            if timeout is not None
            else self._cfg("scheduler.job_timeout_seconds", 3600),
            "timeout",
            lo=1,
            hi=864000,
        )
        estimate = {**DEFAULT_ESTIMATES[kind], **dict(resource_estimate or {})}
        for key in ("cpu_percent", "memory_mb"):
            if key not in estimate:
                raise ValidationError(f"resource estimate needs {key!r}")
            _int(
                int(estimate[key]),
                key,
                lo=1,
                hi=100 if key == "cpu_percent" else 1_000_000,
            )
        data = dict(payload or {})
        job = Job(
            id=new_id("jb_"),
            kind=kind,
            title=(title or f"{kind} job")[:200],
            status="queued",
            queue_seq=0,
            priority=priority,
            payload=data,
            created_at=iso_now(),
            max_attempts=max_attempts,
            timeout_seconds=timeout,
            resource_estimate={k: int(v) for k, v in estimate.items()},
            task_id=task_id,
            project_id=project_id,
        )
        result = self._write(
            "job.enqueue",
            {"job": {**job.to_dict(), "dedupe_key": dedupe_key}},
        )
        if result.get("deduped"):
            self.trace(
                "task",
                "job.deduped",
                status="ok",
                payload={
                    "job_id": result["id"],
                    "dedupe_key": dedupe_key,
                    "kind": kind,
                },
            )
            return self.get(result["id"])
        job.queue_seq = int(result.get("queue_seq") or 0)
        self.trace(
            "task",
            "job.queued",
            status="ok",
            task_id=task_id,
            project_id=project_id,
            payload={
                "job_id": job.id,
                "kind": kind,
                "title": job.title,
                "priority": priority,
                "timeout": timeout,
                "queue_seq": job.queue_seq,
            },
        )
        return self.get(job.id)

    def claim(
        self,
        *,
        worker: str | None = None,
        cpu_free: float = 100.0,
        memory_free: float = 1_000_000.0,
        kinds: Sequence[str] | None = None,
        job_id: str | None = None,
    ) -> Job | None:
        """Claim one fitting job, or return ``None`` when nothing is runnable.

        ``job_id`` narrows the claim to one specific queued job - "run this one now" -
        without letting a caller jump the queue for anything else.
        """
        worker = worker or f"{self.instance}:{os.getpid()}"
        result = self._write(
            "job.claim",
            {
                "worker": worker,
                "cpu_free": float(cpu_free),
                "memory_free": float(memory_free),
                "kinds": list(kinds) if kinds else None,
                "job_id": job_id,
            },
        )
        row = result.get("job")
        if not row:
            return None
        job = _from_row(row)
        if job.task_id:
            self._log(
                job.task_id, "job_started", f"{job.title} (attempt {job.attempts})"
            )
        self.trace(
            "task",
            "job.started",
            status="ok",
            task_id=job.task_id,
            payload={
                "job_id": job.id,
                "kind": job.kind,
                "worker": job.worker,
                "attempts": job.attempts,
                "deadline": job.deadline,
            },
        )
        return job
