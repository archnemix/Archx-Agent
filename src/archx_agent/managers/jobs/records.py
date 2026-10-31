"""Record types and row conversion for durable jobs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from archx_agent.helpers.timeutil import parse_iso
from archx_agent.managers.jobs.constants import TERMINAL
from archx_agent.managers.jobs.validation import _json


@dataclass
class Job:
    id: str
    kind: str
    title: str
    status: str
    queue_seq: int
    priority: int = 5
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    deadline: str | None = None
    requeued_at: str | None = None
    progress: float = 0.0
    message: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    resource_estimate: dict[str, Any] = field(default_factory=dict)
    resource_observed: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None
    project_id: str | None = None
    attempts: int = 0
    max_attempts: int = 1
    timeout_seconds: int | None = None
    pid: int | None = None
    worker: str | None = None
    control: str | None = None
    cursor: int = 0
    cancelled: bool = False

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

    @property
    def attempts_left(self) -> int:
        return max(0, self.max_attempts - self.attempts)

    def expired(self, now: float | None = None) -> bool:
        if not self.deadline or self.status != "running":
            return False
        try:
            return parse_iso(self.deadline).timestamp() <= (
                now if now is not None else time.time()
            )
        except ValueError:  # pragma: no cover - defensive
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "queue_seq": self.queue_seq,
            "priority": self.priority,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "deadline": self.deadline,
            "requeued_at": self.requeued_at,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "result": self.result,
            "resource_estimate": dict(self.resource_estimate),
            "resource_observed": dict(self.resource_observed),
            "task_id": self.task_id,
            "project_id": self.project_id,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "attempts_left": self.attempts_left,
            "timeout_seconds": self.timeout_seconds,
            "pid": self.pid,
            "worker": self.worker,
            "control": self.control,
            "cursor": self.cursor,
            "cancelled": self.cancelled,
        }


def _from_row(row: Mapping[str, Any]) -> Job:
    return Job(
        id=row["id"],
        kind=row["kind"],
        title=row.get("title") or "",
        status=row["status"],
        queue_seq=int(row.get("queue_seq") or 0),
        priority=int(row.get("priority") or 5),
        payload=_json(row.get("payload"), {}),
        created_at=row.get("created_at") or "",
        started_at=row.get("started_at"),
        ended_at=row.get("ended_at"),
        deadline=row.get("deadline"),
        requeued_at=row.get("requeued_at"),
        progress=float(row.get("progress") or 0),
        message=row.get("message"),
        error=row.get("error"),
        result=_json(row.get("result"), None),
        resource_estimate=_json(row.get("resource_estimate"), {}),
        resource_observed=_json(row.get("resource_observed"), {}),
        task_id=row.get("task_id"),
        project_id=row.get("project_id"),
        attempts=int(row.get("attempts") or 0),
        max_attempts=int(row.get("max_attempts") or 1),
        timeout_seconds=row.get("timeout_seconds"),
        pid=row.get("pid"),
        worker=row.get("worker"),
        control=row.get("control"),
        cursor=int(row.get("cursor") or 0),
        cancelled=bool(row.get("cancelled") or 0),
    )
