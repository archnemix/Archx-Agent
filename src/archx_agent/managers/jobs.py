"""The job queue: durable work that outlives the process that accepted it.

A *job* is a unit of work a worker claims and runs. It is not a task: a task is
the record of what happened (M24), a job is the instruction to do something. The
two are linked - a job that runs creates or adopts exactly one task and appends
its milestones to that task's timeline - but the queue has its own state machine
because a queue must answer questions a history cannot: who claimed this, how
many attempts are left, has the deadline passed, is a pause pending?

State machine::

    queued ──claim──► running ──ok──────► completed
      ▲  │               │ └──error─────► failed
      │  │               ├──timeout─────► failed (hard deadline, no retry)
      │  │               ├──pause───────► paused ──resume──► queued
      │  │               └──cancel──────► cancelled
      │  └──pause──► paused
      │
      └──resume / recover (crash) ── from paused / interrupted

Design rules:

* **The queue survives the process.** A running job records its pid, worker name
  and deadline. When a workspace opens, :meth:`JobManager.recover` looks at those
  rows: a job whose process is gone is requeued while it has attempts left, and
  marked ``interrupted`` (not completed) when it does not.
* **A claim is one transaction.** The read of "what is queued" and the write of
  "this one is now mine" happen inside a single journalled write, so two workers
  cannot claim the same row.
* **Timeouts are deadlines, not hints.** The deadline is computed at claim time
  and stored. The runner enforces it while the job runs (killing a child process
  group), and any worker that notices an expired deadline fails the row, so a
  crashed worker's job does not sit in ``running`` forever.
* **Pause is cooperative and durable.** ``pause`` on a queued job is immediate.
  On a running job it records intent; the runner stops at the next checkpoint
  and persists the position it reached, which is what ``resume`` continues from.
  A job kind that cannot be frozen (a running child process) refuses the pause
  instead of pretending.
* **Retries are for crashes, not for failures.** A job that ran and failed keeps
  its error; retrying side effects automatically is not a scheduler's call.
* **Ordering is a sequence.** ``queue_seq`` is assigned inside the enqueue
  transaction and, like every ordering in this codebase, drives ``ORDER BY``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_from_ts, iso_now, new_id, parse_iso

from .base import BaseManager

JOB_TABLES = ("jobs",)

#: What a job can be. New kinds register a runner in the application layer; the
#: manager itself does not execute anything.
JOB_KINDS = ("command", "workflow")

#: Kinds a running job may be paused at a checkpoint. A child process cannot be
#: frozen safely (its children, sockets and temp files would be in an unknown
#: state), so it is not in this set.
PAUSABLE_KINDS = frozenset({"workflow"})

STATUSES = ("queued", "running", "paused", "completed", "failed", "cancelled", "interrupted")
TERMINAL = frozenset({"completed", "failed", "cancelled"})

CONTROLS = ("pause", "cancel", None)

DEFAULT_ESTIMATES: dict[str, dict[str, int]] = {
    "command": {"cpu_percent": 25, "memory_mb": 256},
    "workflow": {"cpu_percent": 50, "memory_mb": 512},
}

_UPDATE_COLUMNS = {
    "status", "message", "error", "progress", "result", "resource_observed",
    "resource_estimate", "task_id", "project_id", "control", "cursor", "attempts",
    "started_at", "ended_at", "deadline", "pid", "worker", "requeued_at", "cancelled",
    "max_attempts", "timeout_seconds", "priority", "payload",
}
_JSON_COLUMNS = {"payload", "result", "resource_estimate", "resource_observed"}


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return default


def _int(value: Any, name: str, *, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{name} must be an integer, got {value!r}")
    if not lo <= value <= hi:
        raise ValidationError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


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
            return parse_iso(self.deadline).timestamp() <= (now if now is not None else time.time())
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


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - another user's process
        return True
    except OSError:  # pragma: no cover - defensive
        return False
    return True


class JobManager(BaseManager):
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

    # -- config ------------------------------------------------------------
    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001 - a bad config must not stop the queue
            return default

    # -- write plumbing ----------------------------------------------------
    def register_handlers(self) -> None:
        self.coordinator.register("job.enqueue", self._apply_enqueue)
        self.coordinator.register("job.claim", self._apply_claim)
        self.coordinator.register("job.update", self._apply_update)

    def _apply_enqueue(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        job = payload["job"]
        if job.get("dedupe_key"):
            existing = tx.query(
                "SELECT id, status FROM jobs WHERE dedupe_key = ? AND status IN"
                " ('queued', 'running', 'paused') ORDER BY queue_seq LIMIT 1",
                (job["dedupe_key"],),
            )
            if existing:
                return {"id": existing[0]["id"], "deduped": True, "status": existing[0]["status"]}
        seq_row = tx.query("SELECT COALESCE(MAX(queue_seq), 0) + 1 AS next FROM jobs")
        queue_seq = int(seq_row[0]["next"]) if seq_row else 1
        tx.execute(
            "INSERT INTO jobs(id, kind, title, payload, status, priority, queue_seq, created_at,"
            " started_at, ended_at, deadline, progress, message, error, resource_estimate,"
            " resource_observed, result, task_id, project_id, cancelled, attempts, max_attempts,"
            " timeout_seconds, pid, worker, requeued_at, control, cursor, dedupe_key)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job["id"], job["kind"], job["title"], json_text(job.get("payload") or {}),
                job["status"], int(job["priority"]), queue_seq, job["created_at"],
                job.get("started_at"), job.get("ended_at"), job.get("deadline"),
                float(job.get("progress") or 0), job.get("message"), job.get("error"),
                json_text(job.get("resource_estimate") or {}),
                json_text(job.get("resource_observed") or {}),
                json_text(job["result"]) if job.get("result") else None,
                job.get("task_id"), job.get("project_id"), 0,
                int(job.get("attempts") or 0), int(job.get("max_attempts") or 1),
                job.get("timeout_seconds"), job.get("pid"), job.get("worker"),
                job.get("requeued_at"), job.get("control"), int(job.get("cursor") or 0),
                job.get("dedupe_key"),
            ),
        )
        return {"id": job["id"], "queue_seq": queue_seq, "deduped": False}

    def _apply_claim(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        """Pick the best queued job that fits and mark it running - atomically."""
        if payload.get("job_id"):
            rows = tx.query(
                "SELECT * FROM jobs WHERE status = 'queued' AND id = ?", (payload["job_id"],)
            )
        else:
            rows = tx.query(
                "SELECT * FROM jobs WHERE status = 'queued'"
                " ORDER BY priority DESC, queue_seq ASC LIMIT 100"
            )
        cpu_free = float(payload.get("cpu_free", 100))
        mem_free = float(payload.get("memory_free", 10**6))
        kinds = payload.get("kinds")
        chosen = None
        for row in rows:
            if kinds and row["kind"] not in kinds:
                continue
            est = _json(row.get("resource_estimate"), {})
            if float(est.get("cpu_percent", 0)) > cpu_free:
                continue
            if float(est.get("memory_mb", 0)) > mem_free:
                continue
            chosen = row
            break
        if chosen is None:
            return {"job": None}
        timeout = chosen.get("timeout_seconds") or int(self._cfg("scheduler.job_timeout_seconds", 3600))
        now = iso_now()
        attempts = int(chosen.get("attempts") or 0) + 1
        deadline = iso_from_ts(time.time() + float(timeout))
        tx.execute(
            "UPDATE jobs SET status = 'running', worker = ?, pid = ?, started_at = ?,"
            " deadline = ?, attempts = ?, control = NULL, ended_at = NULL, progress = 0"
            " WHERE id = ? AND status = 'queued'",
            (
                payload["worker"], os.getpid(), now, deadline, attempts, chosen["id"],
            ),
        )
        row = tx.query("SELECT * FROM jobs WHERE id = ?", (chosen["id"],))
        return {"job": dict(row[0]) if row else None, "attempts": attempts, "deadline": deadline}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = dict(payload["fields"])
        unknown = set(fields) - _UPDATE_COLUMNS
        if unknown:  # pragma: no cover - guard against a typo becoming SQL
            raise ValidationError(f"cannot update job column(s): {', '.join(sorted(unknown))}")
        for key in _JSON_COLUMNS & set(fields):
            fields[key] = json_text(fields[key] if fields[key] is not None else {})
        sets = ", ".join(f"{key} = ?" for key in fields) or "status = status"
        tx.execute(f"UPDATE jobs SET {sets} WHERE id = ?", [*fields.values(), payload["id"]])
        return {"id": payload["id"], "updated": len(fields)}

    def _update(self, job_id: str, **fields: Any) -> Job:
        self.get(job_id)
        self._write("job.update", {"id": job_id, "fields": fields})
        return self.get(job_id)

    # -- submission --------------------------------------------------------
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
            max_attempts if max_attempts is not None else self._cfg("scheduler.max_attempts", 2),
            "max_attempts", lo=1, hi=100,
        )
        timeout = _int(
            timeout if timeout is not None else self._cfg("scheduler.job_timeout_seconds", 3600),
            "timeout", lo=1, hi=864000,
        )
        estimate = {**DEFAULT_ESTIMATES[kind], **dict(resource_estimate or {})}
        for key in ("cpu_percent", "memory_mb"):
            if key not in estimate:
                raise ValidationError(f"resource estimate needs {key!r}")
            _int(int(estimate[key]), key, lo=1, hi=100 if key == "cpu_percent" else 1_000_000)
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
                "task", "job.deduped", status="ok",
                payload={"job_id": result["id"], "dedupe_key": dedupe_key, "kind": kind},
            )
            return self.get(result["id"])
        job.queue_seq = int(result.get("queue_seq") or 0)
        self.trace(
            "task", "job.queued", status="ok", task_id=task_id, project_id=project_id,
            payload={
                "job_id": job.id, "kind": kind, "title": job.title,
                "priority": priority, "timeout": timeout, "queue_seq": job.queue_seq,
            },
        )
        return self.get(job.id)

    # -- claiming ----------------------------------------------------------
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
            self._log(job.task_id, "job_started", f"{job.title} (attempt {job.attempts})")
        self.trace(
            "task", "job.started", status="ok", task_id=job.task_id,
            payload={
                "job_id": job.id, "kind": job.kind, "worker": job.worker,
                "attempts": job.attempts, "deadline": job.deadline,
            },
        )
        return job

    # -- progress ----------------------------------------------------------
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

    # -- completion --------------------------------------------------------
    def finish(self, job_id: str, *, result: Mapping[str, Any] | None = None) -> Job:
        job = self._require_open(job_id, "finish")
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
            "task", "job.completed", status="ok", task_id=finished.task_id,
            payload={"job_id": job_id, "kind": finished.kind, "attempts": finished.attempts},
        )
        return finished

    def fail(self, job_id: str, error: str, *, result: Mapping[str, Any] | None = None) -> Job:
        job = self._require_open(job_id, "fail")
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
            "task", "job.failed", status="error", task_id=failed.task_id,
            error=str(error)[:500],
            payload={"job_id": job_id, "kind": failed.kind, "attempts": failed.attempts},
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
            raise ValidationError(f"stop() ends a run as paused or cancelled, not {status!r}")
        fields: dict[str, Any] = {
            "status": status, "control": None, "message": message, "error": error,
            "cursor": int(cursor),
        }
        if status == "cancelled":
            fields.update(ended_at=iso_now(), cancelled=1)
        if result is not None:
            fields["result"] = dict(result)
        job = self._update(job_id, **fields)
        self._log(job.task_id, f"job_{status}", message or status)
        self.trace(
            "task", f"job.{status}", status="ok",
            task_id=job.task_id, payload={"job_id": job_id, "cursor": cursor, "message": message},
        )
        return job

    # -- control -----------------------------------------------------------
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
                "task", "job.paused", status="ok", task_id=paused.task_id,
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
            "task", "job.pause_requested", status="ok", task_id=updated.task_id,
            payload={"job_id": job_id, "reason": reason},
        )
        return updated

    def resume(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status != "paused":
            raise ConflictError(f"job {job_id} is {job.status}, not paused")
        resumed = self._update(
            job_id, status="queued", requeued_at=iso_now(), control=None,
            message=f"resumed from step {job.cursor}" if job.cursor else "resumed",
        )
        self._log(resumed.task_id, "job_resumed", f"cursor {job.cursor}")
        self.trace(
            "task", "job.resumed", status="ok", task_id=resumed.task_id,
            payload={"job_id": job_id, "cursor": job.cursor},
        )
        return resumed

    def cancel(self, job_id: str, *, reason: str = "cancelled by the user") -> Job:
        job = self.get(job_id)
        if job.terminal:
            raise ConflictError(f"job {job_id} already {job.status}")
        if job.status == "interrupted":
            return self._update(job_id, status="cancelled", cancelled=1, error=reason,
                               ended_at=iso_now())
        if job.status in ("queued", "paused"):
            job = self._update(
                job_id, status="cancelled", cancelled=1, error=reason[:2000],
                ended_at=iso_now(), control=None,
            )
            self._log(job.task_id, "job_cancelled", reason)
            self.trace(
                "task", "job.cancelled", status="ok", task_id=job.task_id,
                payload={"job_id": job_id, "reason": reason, "before_start": True},
            )
            return job
        updated = self._update(job_id, control="cancel", message="cancel requested"[:500])
        self.trace(
            "task", "job.cancel_requested", status="ok", task_id=updated.task_id,
            payload={"job_id": job_id, "reason": reason},
        )
        return updated

    def retry(self, job_id: str, *, force: bool = False) -> Job:
        job = self.get(job_id)
        if job.status == "completed":
            raise ConflictError(f"job {job_id} completed; submit a new job instead of retrying")
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
            **({"max_attempts": job.attempts + 1} if force and job.attempts >= job.max_attempts else {}),
        )
        self._log(retried.task_id, "job_retried", f"attempts {retried.attempts}")
        self.trace(
            "task", "job.retried", status="ok", task_id=retried.task_id,
            payload={"job_id": job_id, "attempts": retried.attempts, "forced": force},
        )
        return retried

    def control(self, job_id: str) -> str | None:
        """What the runner should do next: ``pause``, ``cancel`` or ``None``."""
        row = self.store.query_one("SELECT control FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            raise NotFoundError(f"no job {job_id}")
        return row["control"]

    # -- recovery ----------------------------------------------------------
    def recover(self, *, stale_after: int | None = None) -> dict[str, Any]:
        """Repair the queue after a crash.

        A running row whose pid is dead (or which has outlived ``stale_after``
        seconds under a different worker) is either requeued - it still has
        attempts left and its kind is resumable - or marked ``interrupted`` so it
        is not silently reported as finished work.
        """
        now = time.time()
        stale_after = int(
            stale_after if stale_after is not None else self._cfg("scheduler.stale_after_seconds", 900)
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
                        fresh = now - parse_iso(job.started_at).timestamp() < stale_after
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
                self._log(job.task_id, "job_requeued", f"attempts {job.attempts}/{job.max_attempts}")
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
                "task", "job.recovered",
                status="warning",
                task_id=job.task_id,
                payload={
                    "job_id": job.id,
                    "outcome": "requeued" if job.id in requeued else "interrupted",
                    "attempts": job.attempts,
                },
            )
        return {"requeued": len(requeued), "interrupted": len(interrupted),
                "skipped": len(skipped), "requeued_ids": requeued,
                "interrupted_ids": interrupted, "skipped_ids": skipped}

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
                "task", "job.timed_out", status="error", task_id=job.task_id,
                error="hard deadline passed",
                payload={"job_id": job.id, "timeout": job.timeout_seconds},
            )
            expired.append(job.id)
        return {"expired": len(expired), "ids": expired}

    # -- reads -------------------------------------------------------------
    def get(self, job_id: str) -> Job:
        row = self.store.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            raise NotFoundError(f"no job {job_id}")
        return _from_row(row)

    def find(self, ref: str) -> Job | None:
        row = self.store.query_one("SELECT * FROM jobs WHERE id = ?", (ref,))
        if row is None:
            rows = self.store.query(
                "SELECT * FROM jobs WHERE id LIKE ? ORDER BY queue_seq LIMIT 2", (f"{ref}%",)
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
            " status = 'paused' OR (status = 'queued' AND (attempts > 0 OR cursor > 0)))", ()
        )
        return {row["task_id"] for row in rows}

    def running(self) -> list[Job]:
        return [_from_row(row) for row in self.store.query(
            "SELECT * FROM jobs WHERE status = 'running' ORDER BY queue_seq"
        )]

    def stats(self) -> dict[str, Any]:
        rows = self.store.query("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
        by_kind = self.store.query("SELECT kind, COUNT(*) AS n FROM jobs GROUP BY kind")
        return {
            "total": sum(int(row["n"]) for row in rows),
            "by_status": {row["status"]: int(row["n"]) for row in rows},
            "by_kind": {row["kind"]: int(row["n"]) for row in by_kind},
            "queued": int(self.store.scalar("SELECT COUNT(*) FROM jobs WHERE status='queued'") or 0),
            "running": int(self.store.scalar("SELECT COUNT(*) FROM jobs WHERE status='running'") or 0),
            "paused": int(self.store.scalar("SELECT COUNT(*) FROM jobs WHERE status='paused'") or 0),
        }

    # -- helpers -----------------------------------------------------------
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
            raise ConflictError(f"cannot {action} job {job_id}: it is {job.status}, not running")
        return job


__all__ = [
    "CONTROLS",
    "DEFAULT_ESTIMATES",
    "JOB_KINDS",
    "PAUSABLE_KINDS",
    "STATUSES",
    "TERMINAL",
    "Job",
    "JobManager",
]
