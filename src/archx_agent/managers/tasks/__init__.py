"""Task history: what happened, in what order, and with what attached.

A *task* is the durable record of one unit of work - a chat turn, a tool call, an agent
run, a training job. It exists so the application can answer "what did I do, what did it
produce, and what is still open?" without reading the trace, and so a later milestone
(workflows, scheduler, GUI) has one place to look instead of inventing another.

Design rules:

* **One history.** The ``tasks`` table created in v5 is the only task store. There is no
  parallel "run history": tool runs point at a task, agent runs will too.
* **Ordering is a sequence.** A task's own steps live in ``task_log`` with an
  ``AUTOINCREMENT`` key, and tasks are ordered by their insertion rowid, never by a
  timestamp that two writes can share.
* **Terminal states are final.** Completing, failing or cancelling a finished task is a
  conflict, not a silent overwrite; a task that was running when the process died is
  marked ``interrupted`` (it is not invented as completed).
* **Artifacts are references, not copies.** An artifact records where a file is, what it
  hashed to and which content version it corresponds to. The file itself stays where the
  user put it, and deleting the row never deletes their data.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .manager import TaskManager as TaskManager
from .constants import (
    TASK_TABLES as TASK_TABLES,
    TASK_TYPES as TASK_TYPES,
    TASK_STATUSES as TASK_STATUSES,
    TERMINAL_STATUSES as TERMINAL_STATUSES,
    _LIST_COLUMNS as _LIST_COLUMNS,
    _JSON_COLUMNS as _JSON_COLUMNS,
)
from .records import (
    Task as Task,
    Artifact as Artifact,
    _task_from_row as _task_from_row,
    _artifact_from_row as _artifact_from_row,
)
from .validation import (
    _validate_type as _validate_type,
    _title as _title,
    _json as _json,
)
from .processes import _pid_alive as _pid_alive
from .matching import _terms as _terms


__all__ = [
    "Artifact",
    "TASK_STATUSES",
    "TASK_TABLES",
    "TASK_TYPES",
    "TERMINAL_STATUSES",
    "Task",
    "TaskManager",
]
