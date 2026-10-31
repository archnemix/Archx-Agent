"""History operations for workflow definitions."""

from __future__ import annotations

from typing import Any, Mapping

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.workflows.records import WorkflowStep, _step_from_row


class WorkflowManagerHistoryMixin:
    """History responsibility for WorkflowManager."""

    def add_step(
        self,
        workflow_id: str,
        *,
        seq: int,
        kind: str,
        title: str,
        spec: Mapping[str, Any] | None = None,
        status: str = "running",
        task_id: str | None = None,
    ) -> WorkflowStep:
        self.get(workflow_id)
        step = WorkflowStep(
            id=new_id("ws_"),
            workflow_id=workflow_id,
            seq=int(seq),
            kind=kind,
            title=title,
            spec=dict(spec or {}),
            status=status,
            started_at=iso_now() if status == "running" else None,
            task_id=task_id,
        )
        self._write("workflow.step", {"step": step.to_dict()})
        return self.step(step.id)

    def finish_step(
        self,
        step_id: str,
        *,
        status: str,
        output: str | None = None,
        error: str | None = None,
        tokens: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowStep:
        if status not in ("succeeded", "failed", "skipped"):
            raise ValidationError(f"a step cannot finish as {status!r}")
        fields: dict[str, Any] = {
            "status": status,
            "ended_at": iso_now(),
            "output": (output or "")[:20000] or None,
            "error": (error or "")[:2000] or None,
            "tokens": int(tokens),
        }
        if metadata:
            fields["metadata"] = metadata
        self._write("workflow.step_update", {"id": step_id, "fields": fields})
        return self.step(step_id)

    def step(self, step_id: str) -> WorkflowStep:
        row = self.store.query_one(
            "SELECT * FROM workflow_steps WHERE id = ?", (step_id,)
        )
        if row is None:
            raise NotFoundError(f"no workflow step {step_id}")
        return _step_from_row(row)

    def steps(self, workflow_id: str) -> list[WorkflowStep]:
        rows = self.store.query(
            "SELECT * FROM workflow_steps WHERE workflow_id = ? ORDER BY seq",
            (workflow_id,),
        )
        return [_step_from_row(row) for row in rows]
