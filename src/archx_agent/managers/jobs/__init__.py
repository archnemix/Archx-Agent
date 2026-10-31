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

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .manager import JobManager as JobManager
from .constants import (
    JOB_TABLES as JOB_TABLES,
    JOB_KINDS as JOB_KINDS,
    PAUSABLE_KINDS as PAUSABLE_KINDS,
    STATUSES as STATUSES,
    TERMINAL as TERMINAL,
    CONTROLS as CONTROLS,
    DEFAULT_ESTIMATES as DEFAULT_ESTIMATES,
    _UPDATE_COLUMNS as _UPDATE_COLUMNS,
    _JSON_COLUMNS as _JSON_COLUMNS,
)
from .records import Job as Job, _from_row as _from_row
from .validation import _json as _json, _int as _int
from .processes import _pid_alive as _pid_alive


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
