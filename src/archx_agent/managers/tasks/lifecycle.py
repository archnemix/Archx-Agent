"""Lifecycle operations for task history."""

from __future__ import annotations

import os
from typing import Any, Collection, Sequence

from archx_agent.helpers.exceptions import ConflictError
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.tasks.records import Task
from archx_agent.managers.tasks.validation import _validate_type, _title, _json
from archx_agent.managers.tasks.processes import _pid_alive


class TaskManagerLifecycleMixin:
    """Lifecycle responsibility for TaskManager."""

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
            "task",
            "task.completed",
            status="ok",
            task_id=task_id,
            conversation_id=task.conversation_id,
            project_id=task.project_id,
            payload={
                "summary": (summary or "")[:500],
                "tools": fields.get("tools", task.tools),
            },
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
        message = (
            error
            if isinstance(error, str)
            else (getattr(error, "message", None) or str(error))
        )
        now = iso_now()
        fields: dict[str, Any] = {
            "status": "failed",
            "completed_at": now,
            "started_at": task.started_at or now,
            "error": f"{type(error).__name__}: {message}"
            if not isinstance(error, str)
            else message,
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
            "task",
            "task.failed",
            status="error",
            task_id=task_id,
            conversation_id=task.conversation_id,
            project_id=task.project_id,
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
            "task",
            "task.cancelled",
            status="warning",
            task_id=task_id,
            conversation_id=task.conversation_id,
            payload={"reason": reason},
        )
        return self.get(task_id)

    def interrupt(
        self, task_id: str, reason: str = "the process ended before the task finished"
    ) -> Task:
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
            "task",
            "task.interrupted",
            status="warning",
            task_id=task_id,
            conversation_id=task.conversation_id,
            error=reason,
        )
        return self.get(task_id)

    def interrupt_stale(self, *, protect: Collection[str] = ()) -> dict[str, Any]:
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

        ``protect`` names tasks that another durable record still owns - a *paused job*
        continues them, so sweeping them would make a resumable run look dead.
        """
        rows = self.store.query(
            "SELECT id, metadata FROM tasks WHERE status = 'running' ORDER BY rowid", ()
        )
        interrupted: list[str] = []
        skipped: list[str] = []
        protected = set(protect or ())
        for row in rows:
            meta = _json(row.get("metadata"), {})
            if row["id"] in protected:
                skipped.append(row["id"])
                continue
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
                "task",
                "task.swept",
                status="warning",
                payload={"interrupted": interrupted},
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
