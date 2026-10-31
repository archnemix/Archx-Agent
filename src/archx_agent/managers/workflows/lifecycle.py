"""Lifecycle operations for workflow definitions."""

from __future__ import annotations

from typing import Any, Mapping

from archx_agent.helpers.exceptions import ConflictError, ValidationError
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.workflows.constants import STATUSES
from archx_agent.managers.workflows.steps import validate_definition
from archx_agent.managers.workflows.records import Workflow


class WorkflowManagerLifecycleMixin:
    """Lifecycle responsibility for WorkflowManager."""

    def create(
        self,
        definition: Mapping[str, Any],
        *,
        mode: str | None = None,
        status: str = "approved",
        model_id: str | None = None,
        goal: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Workflow:
        normalised = validate_definition(
            {**dict(definition), "mode": mode or definition.get("mode") or "user"},
            tools=self.tools,
            max_steps=int(self._cfg("agent.max_steps", 40)),
        )
        if status not in STATUSES:
            raise ValidationError(f"unknown workflow status {status!r}")
        now = iso_now()
        workflow = Workflow(
            id=new_id("wf_"),
            name=normalised["name"],
            mode=normalised["mode"],
            status=status,
            definition=normalised,
            created_at=now,
            updated_at=now,
            goal=(goal if goal is not None else normalised.get("goal")) or "",
            model_id=model_id or normalised.get("model"),
            metadata={**normalised.get("metadata", {}), **(metadata or {})},
        )
        self._write("workflow.create", {"workflow": workflow.to_dict()})
        self.trace(
            "agent_run",
            "workflow.created",
            status="ok",
            task_id=workflow.task_id,
            payload={
                "workflow_id": workflow.id,
                "name": workflow.name,
                "mode": workflow.mode,
                "status": workflow.status,
                "steps": len(workflow.steps),
            },
        )
        return self.get(workflow.id)

    def _update(self, workflow_id: str, **fields: Any) -> Workflow:
        self.get(workflow_id)
        self._write("workflow.update", {"id": workflow_id, "fields": fields})
        return self.get(workflow_id)

    def approve(self, workflow_id: str, *, by: str = "user:cli") -> Workflow:
        wf = self.get(workflow_id)
        if wf.status != "proposed":
            raise ConflictError(f"workflow {workflow_id} is {wf.status}, not proposed")
        self._trace_status(wf, "workflow.approved", {"by": by})
        return self._update(
            workflow_id, status="approved", metadata={**wf.metadata, "approved_by": by}
        )

    def reject(
        self, workflow_id: str, *, reason: str = "rejected by the user"
    ) -> Workflow:
        wf = self.get(workflow_id)
        if wf.terminal:
            raise ConflictError(f"workflow {workflow_id} already {wf.status}")
        self._trace_status(
            wf, "workflow.rejected", {"reason": reason}, status="warning"
        )
        return self._update(
            workflow_id, status="cancelled", error=reason, finished_at=iso_now()
        )

    def cancel(
        self, workflow_id: str, *, reason: str = "cancelled by the user"
    ) -> Workflow:
        wf = self.get(workflow_id)
        if wf.terminal:
            raise ConflictError(f"workflow {workflow_id} already {wf.status}")
        self._trace_status(
            wf, "workflow.cancelled", {"reason": reason}, status="warning"
        )
        return self._update(
            workflow_id, status="cancelled", error=reason, finished_at=iso_now()
        )

    def mark_running(
        self,
        workflow_id: str,
        *,
        task_id: str | None = None,
        conversation_id: str | None = None,
    ) -> Workflow:
        wf = self.get(workflow_id)
        if wf.terminal:
            raise ConflictError(f"workflow {workflow_id} already {wf.status}")
        fields: dict[str, Any] = {
            "status": "running",
            "started_at": wf.started_at or iso_now(),
        }
        if task_id:
            fields["task_id"] = task_id
        if conversation_id:
            fields["conversation_id"] = conversation_id
        self._trace_status(wf, "workflow.started", {"task_id": task_id})
        return self._update(workflow_id, **fields)

    def finish(
        self,
        workflow_id: str,
        *,
        status: str = "completed",
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Workflow:
        if status not in ("completed", "failed", "cancelled"):
            raise ValidationError(f"a workflow cannot finish as {status!r}")
        wf = self.get(workflow_id)
        fields: dict[str, Any] = {
            "status": status,
            "finished_at": iso_now(),
            "error": error,
        }
        if metadata:
            fields["metadata"] = {**wf.metadata, **metadata}
        self._trace_status(
            wf,
            f"workflow.{status}",
            {"error": error},
            status="ok" if status == "completed" else "error",
        )
        return self._update(workflow_id, **fields)

    def _trace_status(
        self, wf: Workflow, name: str, payload: dict[str, Any], *, status: str = "ok"
    ) -> None:
        self.trace(
            "agent_run",
            name,
            status=status,
            task_id=wf.task_id,
            payload={"workflow_id": wf.id, "name": wf.name, **payload},
        )
