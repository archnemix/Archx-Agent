"""History operations for task history."""

from __future__ import annotations

import json
from typing import Any, Sequence

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.tasks.records import Task


class TaskManagerHistoryMixin:
    """History responsibility for TaskManager."""

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
        if isinstance(question, int) or (
            isinstance(question, str) and question.isdigit()
        ):
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

    def log(
        self,
        task_id: str,
        kind: str,
        *,
        detail: str | None = None,
        event_id: str | None = None,
    ) -> int | None:
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
            "SELECT * FROM tool_runs WHERE task_id = ? ORDER BY seq, started_at",
            (task_id,),
        )
        for row in rows:
            for column in ("arguments", "result"):
                if row.get(column):
                    try:
                        row[column] = json.loads(row[column])
                    except json.JSONDecodeError:  # pragma: no cover
                        pass
        return rows
