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
"""

from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text, sha256_file
from archx_agent.helpers.result import Result
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

TASK_TABLES = ("tasks", "task_log", "artifacts")

TASK_TYPES = (
    "chat",
    "tool",
    "memory",
    "context",
    "agent",
    "research",
    "coding",
    "learning",
    "experiment",
    "training",
    "dataset",
    "game",
    "automation",
    "maintenance",
    "system",
)

TASK_STATUSES = ("queued", "running", "completed", "failed", "cancelled", "interrupted")
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})

_LIST_COLUMNS = {"agents", "tools", "input_refs", "output_refs", "unresolved"}
_JSON_COLUMNS = {"resource_use", "version_info", "metadata"}


def _validate_type(kind: str) -> str:
    value = (kind or "").strip()
    if value not in TASK_TYPES:
        raise ValidationError(f"unknown task type {kind!r} (known: {', '.join(TASK_TYPES)})")
    return value


def _title(text: str | None, fallback: str) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        cleaned = fallback
    return cleaned[:200]


def _pid_alive(pid: int) -> bool:
    """Is this pid alive? Used only to avoid declaring someone else's work dead."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:  # pragma: no cover - defensive
        return False
    return True


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):  # pragma: no cover - defensive
        return default


@dataclass
class Task:
    id: str
    type: str
    title: str
    status: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    conversation_id: str | None = None
    project_id: str | None = None
    parent_task_id: str | None = None
    run_id: str | None = None
    model_id: str | None = None
    agents: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    resource_use: dict[str, Any] = field(default_factory=dict)
    cost_estimate: float | None = None
    input_refs: list[str] = field(default_factory=list)
    output_refs: list[str] = field(default_factory=list)
    error: str | None = None
    unresolved: list[str] = field(default_factory=list)
    trace_event_id: str | None = None
    version_info: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    seq: int | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def resumable(self) -> bool:
        """Can work continue on this task without inventing a new one?"""
        return self.status in ("queued", "running", "interrupted")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "seq": self.seq,
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "conversation_id": self.conversation_id,
            "project_id": self.project_id,
            "parent_task_id": self.parent_task_id,
            "run_id": self.run_id,
            "model_id": self.model_id,
            "agents": list(self.agents),
            "tools": list(self.tools),
            "resource_use": dict(self.resource_use),
            "cost_estimate": self.cost_estimate,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "error": self.error,
            "unresolved": list(self.unresolved),
            "trace_event_id": self.trace_event_id,
            "version_info": dict(self.version_info),
            "metadata": dict(self.metadata),
            "terminal": self.terminal,
            "resumable": self.resumable,
        }


@dataclass
class Artifact:
    id: str
    task_id: str | None
    kind: str
    name: str
    path: str
    created_at: str
    project_id: str | None = None
    rel_path: str | None = None
    checksum: str | None = None
    size: int | None = None
    mime: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def exists(self) -> bool:
        return Path(self.path).exists()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "rel_path": self.rel_path,
            "checksum": self.checksum,
            "size": self.size,
            "mime": self.mime,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "exists": self.exists,
        }


def _task_from_row(row: dict[str, Any]) -> Task:
    return Task(
        id=row["id"],
        seq=row.get("seq"),
        type=row["type"],
        title=row["title"],
        status=row["status"],
        created_at=row["created_at"],
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        conversation_id=row.get("conversation_id"),
        project_id=row.get("project_id"),
        parent_task_id=row.get("parent_task_id"),
        run_id=row.get("run_id"),
        model_id=row.get("model_id"),
        agents=_json(row.get("agents"), []),
        tools=_json(row.get("tools"), []),
        resource_use=_json(row.get("resource_use"), {}),
        cost_estimate=row.get("cost_estimate"),
        input_refs=_json(row.get("input_refs"), []),
        output_refs=_json(row.get("output_refs"), []),
        error=row.get("error"),
        unresolved=_json(row.get("unresolved"), []),
        trace_event_id=row.get("trace_event_id"),
        version_info=_json(row.get("version_info"), {}),
        metadata=_json(row.get("metadata"), {}),
    )


def _artifact_from_row(row: dict[str, Any]) -> Artifact:
    return Artifact(
        id=row["id"],
        task_id=row.get("task_id"),
        project_id=row.get("project_id"),
        kind=row.get("kind") or "file",
        name=row.get("name") or "",
        path=row.get("path") or "",
        rel_path=row.get("rel_path"),
        checksum=row.get("checksum"),
        size=row.get("size"),
        mime=row.get("mime"),
        created_at=row["created_at"],
        metadata=_json(row.get("metadata"), {}),
    )


class TaskManager(BaseManager):
    """Durable task history plus the artifacts a task produced."""

    tables = TASK_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        events=None,
        versions=None,
        home: str | None = None,
        max_version_bytes: int = 1_048_576,
        instance: str | None = None,
    ) -> None:
        self.versions = versions
        self.home = home
        self.max_version_bytes = int(max_version_bytes)
        # Every opened workspace is an owner. A task records which instance and process
        # started it, so a later open can tell "this is stale" from "another process is
        # still working on it" instead of guessing.
        self.instance = instance or new_id("ws_")
        super().__init__(store, coordinator, events=events)

    # -- write plumbing ----------------------------------------------------
    def register_handlers(self) -> None:
        self.coordinator.register("task.create", self._apply_create)
        self.coordinator.register("task.update", self._apply_update)
        self.coordinator.register("task.log", self._apply_log)
        self.coordinator.register("task.artifact", self._apply_artifact)

    def _apply_create(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        t = payload["task"]
        tx.execute(
            "INSERT INTO tasks(id, type, title, status, conversation_id, project_id,"
            " parent_task_id, run_id, created_at, started_at, completed_at, model_id, agents,"
            " tools, resource_use, cost_estimate, input_refs, output_refs, error, unresolved,"
            " trace_event_id, version_info, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                t["id"], t["type"], t["title"], t["status"], t.get("conversation_id"),
                t.get("project_id"), t.get("parent_task_id"), t.get("run_id"),
                t["created_at"], t.get("started_at"), t.get("completed_at"),
                t.get("model_id"), json_text(t.get("agents") or []),
                json_text(t.get("tools") or []), json_text(t.get("resource_use") or {}),
                t.get("cost_estimate"), json_text(t.get("input_refs") or []),
                json_text(t.get("output_refs") or []), t.get("error"),
                json_text(t.get("unresolved") or []), t.get("trace_event_id"),
                json_text(t.get("version_info") or {}), json_text(t.get("metadata") or {}),
            ),
        )
        row = tx.query("SELECT rowid AS seq FROM tasks WHERE id = ?", (t["id"],))
        return {"id": t["id"], "seq": row[0]["seq"] if row else None}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        sets: list[str] = []
        params: list[Any] = []
        for key, value in payload["fields"].items():
            if key in _LIST_COLUMNS or key in _JSON_COLUMNS:
                value = json_text(value if value is not None else ([] if key in _LIST_COLUMNS else {}))
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:  # pragma: no cover - callers always pass fields
            return {"id": payload["id"], "updated": 0}
        params.append(payload["id"])
        tx.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params)
        return {"id": payload["id"], "updated": len(sets)}

    def _apply_log(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        entry = payload["entry"]
        tx.execute(
            "INSERT INTO task_log(task_id, at, kind, detail, event_id) VALUES (?,?,?,?,?)",
            (entry["task_id"], entry["at"], entry["kind"], entry.get("detail"), entry.get("event_id")),
        )
        row = tx.query("SELECT last_insert_rowid() AS seq")
        return {"seq": row[0]["seq"] if row else None}

    def _apply_artifact(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        a = payload["artifact"]
        tx.execute(
            "INSERT INTO artifacts(id, task_id, project_id, kind, name, path, rel_path,"
            " checksum, size, mime, created_at, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                a["id"], a.get("task_id"), a.get("project_id"), a["kind"], a["name"],
                a["path"], a.get("rel_path"), a.get("checksum"), a.get("size"),
                a.get("mime"), a["created_at"], json_text(a.get("metadata") or {}),
            ),
        )
        return {"id": a["id"]}

    # -- creation ----------------------------------------------------------
    def create(
        self,
        kind: str,
        title: str | None = None,
        *,
        conversation_id: str | None = None,
        project_id: str | None = None,
        parent_task_id: str | None = None,
        model_id: str | None = None,
        run_id: str | None = None,
        agents: Sequence[str] | None = None,
        tools: Sequence[str] | None = None,
        inputs: Sequence[str] | None = None,
        metadata: dict[str, Any] | None = None,
        start: bool = False,
        manual: bool = False,
    ) -> Task:
        """Record a task. ``start=True`` also marks it running (the common case).

        ``manual=True`` marks a task the *user* keeps track of (``archx-agent tasks
        start``), not one this process is executing. A manual task is never swept as
        interrupted, because the process that created it exits immediately by design.
        """
        task_type = _validate_type(kind)
        if parent_task_id is not None:
            self.get(parent_task_id)  # raises NotFoundError for a dangling parent
        now = iso_now()
        task = Task(
            id=new_id("tk_"),
            type=task_type,
            title=_title(title, f"{task_type} task"),
            status="running" if start else "queued",
            created_at=now,
            started_at=now if start else None,
            conversation_id=conversation_id,
            project_id=project_id,
            parent_task_id=parent_task_id,
            run_id=run_id,
            model_id=model_id,
            agents=list(agents or []),
            tools=list(tools or []),
            input_refs=list(inputs or []),
            metadata={
                **dict(metadata or {}),
                "instance": self.instance,
                "pid": os.getpid(),
                "manual": bool(manual),
            },
        )
        result = self._write("task.create", {"task": task.to_dict()})
        task.seq = result.get("seq")
        self.log(task.id, "created", detail=f"{task.type}: {task.title}")
        if start:
            self.log(task.id, "started")
        event_id = self.trace(
            "task",
            "task.created",
            status="ok",
            conversation_id=conversation_id,
            task_id=task.id,
            project_id=project_id,
            payload={"type": task.type, "title": task.title, "status": task.status},
        )
        if event_id:
            self._set_fields(task.id, trace_event_id=event_id)
            task.trace_event_id = event_id
        return task

    def start(
        self,
        task_id: str,
        *,
        model_id: str | None = None,
        tools: Sequence[str] | None = None,
        agents: Sequence[str] | None = None,
    ) -> Task:
        """Move a queued task to running."""
        task = self.get(task_id)
        if task.terminal:
            raise ConflictError(f"task {task_id} already finished ({task.status})")
        if task.status == "running":
            raise ConflictError(f"task {task_id} is already running")
        fields: dict[str, Any] = {"status": "running", "started_at": iso_now()}
        if model_id:
            fields["model_id"] = model_id
        if tools is not None:
            fields["tools"] = list(tools)
        if agents is not None:
            fields["agents"] = list(agents)
        self._set_fields(task.id, **fields)
        self.log(task.id, "started")
        return self.get(task.id)

    # -- state transitions -------------------------------------------------
    def complete(
        self,
        task_id: str,
        *,
        summary: str | None = None,
        outputs: Sequence[str] | None = None,
        tools: Sequence[str] | None = None,
        model_id: str | None = None,
        cost_estimate: float | None = None,
        resource_use: dict[str, Any] | None = None,
        version_info: dict[str, Any] | None = None,
    ) -> Task:
        task = self._require_open(task_id, "complete")
        now = iso_now()
        fields: dict[str, Any] = {
            "status": "completed",
            "completed_at": now,
            "started_at": task.started_at or now,
        }
        if outputs is not None:
            fields["output_refs"] = list(outputs)
        if tools is not None:
            fields["tools"] = list(tools)
        if model_id:
            fields["model_id"] = model_id
        if cost_estimate is not None:
            fields["cost_estimate"] = float(cost_estimate)
        if resource_use is not None:
            fields["resource_use"] = dict(resource_use)
        if version_info is not None:
            fields["version_info"] = dict(version_info)
        self._set_fields(task_id, **fields)
        if summary:
            self.log(task_id, "summary", detail=summary[:4000])
        self.log(task_id, "completed")
        self.trace(
            "task", "task.completed", status="ok", task_id=task_id,
            conversation_id=task.conversation_id, project_id=task.project_id,
            payload={"summary": (summary or "")[:500], "tools": fields.get("tools", task.tools)},
        )
        return self.get(task_id)

    def fail(
        self,
        task_id: str,
        error: BaseException | str,
        *,
        unresolved: Sequence[str] | None = None,
        resource_use: dict[str, Any] | None = None,
    ) -> Task:
        task = self._require_open(task_id, "fail")
        message = error if isinstance(error, str) else (getattr(error, "message", None) or str(error))
        now = iso_now()
        fields: dict[str, Any] = {
            "status": "failed",
            "completed_at": now,
            "started_at": task.started_at or now,
            "error": f"{type(error).__name__}: {message}" if not isinstance(error, str) else message,
        }
        # An exception type is evidence about the failure; keep it short.
        fields["error"] = str(fields["error"])[:2000]
        if unresolved is not None:
            fields["unresolved"] = list(unresolved)
        if resource_use is not None:
            fields["resource_use"] = dict(resource_use)
        self._set_fields(task_id, **fields)
        self.log(task_id, "failed", detail=fields["error"])
        self.trace(
            "task", "task.failed", status="error", task_id=task_id,
            conversation_id=task.conversation_id, project_id=task.project_id,
            error=fields["error"],
        )
        return self.get(task_id)

    def cancel(self, task_id: str, reason: str = "") -> Task:
        task = self._require_open(task_id, "cancel")
        now = iso_now()
        self._set_fields(
            task_id,
            status="cancelled",
            completed_at=now,
            started_at=task.started_at or now,
            error=(reason or "cancelled by the user")[:2000],
        )
        self.log(task_id, "cancelled", detail=reason or None)
        self.trace(
            "task", "task.cancelled", status="warning", task_id=task_id,
            conversation_id=task.conversation_id, payload={"reason": reason},
        )
        return self.get(task_id)

    def interrupt(self, task_id: str, reason: str = "the process ended before the task finished") -> Task:
        task = self.get(task_id)
        if task.terminal:
            return task
        now = iso_now()
        self._set_fields(
            task_id,
            status="interrupted",
            completed_at=now,
            started_at=task.started_at or now,
            error=reason[:2000],
        )
        self.log(task_id, "interrupted", detail=reason)
        self.trace(
            "task", "task.interrupted", status="warning", task_id=task_id,
            conversation_id=task.conversation_id, error=reason,
        )
        return self.get(task_id)

    def interrupt_stale(self) -> dict[str, Any]:
        """Mark tasks a *dead* process left running.

        This is deliberately a *record*, not a cleanup: a task that was running when the
        process died is reported as interrupted so a later reader does not believe it
        completed. It never deletes anything.

        Three cases are distinguished:

        * a task owned by another **live** process is left alone (that process may still
          be working) and reported in ``skipped``;
        * a task the user tracks manually (``tasks start``) is left alone - the CLI
          process exits immediately by design, so its pid proves nothing;
        * everything else is interrupted, with the reason recorded.
        """
        rows = self.store.query(
            "SELECT id, metadata FROM tasks WHERE status = 'running' ORDER BY rowid", ()
        )
        interrupted: list[str] = []
        skipped: list[str] = []
        for row in rows:
            meta = _json(row.get("metadata"), {})
            if meta.get("manual"):
                skipped.append(row["id"])
                continue
            pid = meta.get("pid")
            if isinstance(pid, int) and pid != os.getpid() and _pid_alive(pid):
                skipped.append(row["id"])
                continue
            self.interrupt(
                row["id"],
                "interrupted on start: the process that owned this task is gone",
            )
            interrupted.append(row["id"])
        if interrupted:
            self.trace(
                "task", "task.swept", status="warning", payload={"interrupted": interrupted}
            )
        return {"interrupted": len(interrupted), "ids": interrupted, "skipped": skipped}

    def _require_open(self, task_id: str, action: str) -> Task:
        task = self.get(task_id)
        if task.terminal:
            raise ConflictError(
                f"cannot {action} task {task_id}: it is already {task.status}"
            )
        return task

    def _set_fields(self, task_id: str, **fields: Any) -> None:
        if not fields:  # pragma: no cover
            return
        self._write("task.update", {"id": task_id, "fields": fields})

    # -- linking -----------------------------------------------------------
    def link(
        self,
        task_id: str,
        *,
        conversation_id: str | None = None,
        project_id: str | None = None,
        run_id: str | None = None,
        model_id: str | None = None,
        tools: Sequence[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        task = self.get(task_id)
        fields: dict[str, Any] = {}
        if conversation_id:
            fields["conversation_id"] = conversation_id
        if project_id:
            fields["project_id"] = project_id
        if run_id:
            fields["run_id"] = run_id
        if model_id:
            fields["model_id"] = model_id
        if tools is not None:
            merged = list(dict.fromkeys([*task.tools, *tools]))
            fields["tools"] = merged
        if metadata:
            merged_meta = {**task.metadata, **metadata}
            fields["metadata"] = merged_meta
        if fields:
            self._set_fields(task_id, **fields)
        return self.get(task_id)

    def set_inputs(self, task_id: str, inputs: Sequence[str]) -> Task:
        self.get(task_id)
        self._set_fields(task_id, input_refs=[str(item) for item in inputs])
        return self.get(task_id)

    def add_question(self, task_id: str, question: str) -> Task:
        text = " ".join((question or "").split())
        if not text:
            raise ValidationError("a question must not be empty")
        task = self.get(task_id)
        if text in task.unresolved:
            return task
        self._set_fields(task_id, unresolved=[*task.unresolved, text])
        self.log(task_id, "question", detail=text)
        return self.get(task_id)

    def resolve_question(self, task_id: str, question: str | int) -> Task:
        task = self.get(task_id)
        if not task.unresolved:
            raise ValidationError(f"task {task_id} has no open questions")
        remaining = list(task.unresolved)
        if isinstance(question, int) or (isinstance(question, str) and question.isdigit()):
            index = int(question)
            if index < 0 or index >= len(remaining):
                raise ValidationError(
                    f"question index {index} is out of range (0..{len(remaining) - 1})"
                )
            removed = remaining.pop(index)
        else:
            if question not in remaining:
                raise NotFoundError(f"no open question {question!r} on task {task_id}")
            remaining.remove(question)
            removed = question
        self._set_fields(task_id, unresolved=remaining)
        self.log(task_id, "resolved", detail=removed)
        return self.get(task_id)

    def log(self, task_id: str, kind: str, *, detail: str | None = None, event_id: str | None = None) -> int | None:
        entry = {
            "task_id": task_id,
            "at": iso_now(),
            "kind": (kind or "").strip()[:60] or "note",
            "detail": (detail or "")[:4000] or None,
            "event_id": event_id,
        }
        result = self._write("task.log", {"entry": entry})
        return result.get("seq") if isinstance(result, dict) else None

    def timeline(self, task_id: str) -> list[dict[str, Any]]:
        self.get(task_id)  # 404 for an unknown task instead of an empty list
        rows = self.store.query(
            "SELECT * FROM task_log WHERE task_id = ? ORDER BY seq", (task_id,)
        )
        return rows

    def tool_runs(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT * FROM tool_runs WHERE task_id = ? ORDER BY seq, started_at", (task_id,)
        )
        for row in rows:
            for column in ("arguments", "result"):
                if row.get(column):
                    try:
                        row[column] = json.loads(row[column])
                    except json.JSONDecodeError:  # pragma: no cover
                        pass
        return rows

    # -- artifacts ---------------------------------------------------------
    def attach_artifact(
        self,
        task_id: str,
        path: str,
        *,
        kind: str = "file",
        name: str | None = None,
        record_version: bool = True,
    ) -> Artifact:
        task = self.get(task_id)
        file_path = Path(path).expanduser()
        if not file_path.exists() or not file_path.is_file():
            raise NotFoundError(f"artifact file not found: {path}")
        size = file_path.stat().st_size
        checksum = sha256_file(file_path)
        rel_path = None
        if self.home:
            try:
                rel_path = str(file_path.resolve().relative_to(Path(self.home).resolve()))
            except ValueError:
                rel_path = None
        metadata: dict[str, Any] = {}
        if record_version and self.versions is not None:
            try:
                write = self.versions.record(
                    "artifact",
                    str(file_path.resolve()),
                    path=file_path,
                    note=f"attached to task {task.id}",
                    created_by="task",
                )
                metadata["version_id"] = write.version.id
                metadata["version"] = write.version.version
                metadata["version_created"] = write.created
            except Exception as exc:  # noqa: BLE001 - versioning must not lose the artifact
                metadata["version_error"] = getattr(exc, "message", None) or str(exc)
        artifact = Artifact(
            id=new_id("ar_"),
            task_id=task.id,
            project_id=task.project_id,
            kind=(kind or "file").strip()[:40],
            name=(name or file_path.name)[:200],
            path=str(file_path.resolve()),
            rel_path=rel_path,
            checksum=checksum,
            size=size,
            mime=mimetypes.guess_type(str(file_path))[0],
            created_at=iso_now(),
            metadata=metadata,
        )
        self._write("task.artifact", {"artifact": artifact.to_dict()})
        self.log(task.id, "artifact", detail=f"{artifact.kind}: {artifact.name} ({size} bytes)")
        self.trace(
            "artifact", "artifact.attached", status="ok", task_id=task.id,
            conversation_id=task.conversation_id, project_id=task.project_id,
            payload={"artifact_id": artifact.id, "path": artifact.path, "sha256": checksum},
        )
        return artifact

    def artifacts(self, task_id: str | None = None, *, limit: int = 100) -> list[Artifact]:
        if task_id:
            rows = self.store.query(
                "SELECT * FROM artifacts WHERE task_id = ? ORDER BY created_at, id LIMIT ?",
                (task_id, int(limit)),
            )
        else:
            rows = self.store.query(
                "SELECT * FROM artifacts ORDER BY created_at DESC, id LIMIT ?", (int(limit),)
            )
        return [_artifact_from_row(row) for row in rows]

    def artifact(self, artifact_id: str) -> Result[Artifact]:
        row = self.store.query_one("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
        if row is None:
            return Result.err(NotFoundError(f"no artifact {artifact_id}"))
        return Result.ok(_artifact_from_row(row))

    # -- reads -------------------------------------------------------------
    def get(self, task_id: str) -> Task:
        row = self.store.query_one(
            "SELECT rowid AS seq, * FROM tasks WHERE id = ?", (task_id,)
        )
        if row is None:
            raise NotFoundError(f"no task {task_id}")
        return _task_from_row(row)

    def find(self, task_id: str) -> Result[Task]:
        row = self.store.query_one(
            "SELECT rowid AS seq, * FROM tasks WHERE id = ?", (task_id,)
        )
        if row is None:
            return Result.err(NotFoundError(f"no task {task_id}"))
        return Result.ok(_task_from_row(row))

    def list(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        parent_task_id: str | None = None,
        since: str | None = None,
        limit: int = 20,
        newest_first: bool = True,
    ) -> list[Task]:
        sql = "SELECT rowid AS seq, * FROM tasks"
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            if status not in TASK_STATUSES:
                raise ValidationError(f"unknown task status {status!r}")
            clauses.append("status = ?")
            params.append(status)
        if kind:
            clauses.append("type = ?")
            params.append(_validate_type(kind))
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        if parent_task_id:
            clauses.append("parent_task_id = ?")
            params.append(parent_task_id)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rowid " + ("DESC" if newest_first else "ASC") + " LIMIT ?"
        params.append(int(limit))
        return [_task_from_row(row) for row in self.store.query(sql, params)]

    def children(self, task_id: str, *, limit: int = 100) -> list[Task]:
        return self.list(parent_task_id=task_id, limit=limit, newest_first=False)

    def tree(self, task_id: str, *, depth: int = 5) -> dict[str, Any]:
        task = self.get(task_id)
        node = task.to_dict()
        if depth > 0:
            node["children"] = [self.tree(child.id, depth=depth - 1) for child in self.children(task_id)]
        else:
            node["children"] = []
        return node

    def stats(self) -> dict[str, Any]:
        by_status = {
            row["status"]: int(row["n"])
            for row in self.store.query(
                "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status", ()
            )
        }
        by_type = {
            row["type"]: int(row["n"])
            for row in self.store.query(
                "SELECT type, COUNT(*) AS n FROM tasks GROUP BY type ORDER BY n DESC", ()
            )
        }
        with_questions = int(
            self.store.scalar("SELECT COUNT(*) FROM tasks WHERE unresolved NOT IN ('', '[]')") or 0
        )
        return {
            "total": sum(by_status.values()),
            "by_status": by_status,
            "by_type": by_type,
            "with_open_questions": with_questions,
            "artifacts": self.table_count("artifacts"),
        }


__all__ = [
    "Artifact",
    "TASK_STATUSES",
    "TASK_TABLES",
    "TASK_TYPES",
    "TERMINAL_STATUSES",
    "Task",
    "TaskManager",
]
