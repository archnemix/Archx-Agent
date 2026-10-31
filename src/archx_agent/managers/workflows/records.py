"""Record types and row conversion for workflow definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from archx_agent.managers.workflows.constants import TERMINAL
from archx_agent.managers.workflows.steps import StepSpec, parse_steps


@dataclass
class Workflow:
    id: str
    name: str
    mode: str
    status: str
    definition: dict[str, Any]
    created_at: str
    updated_at: str
    goal: str = ""
    model_id: str | None = None
    task_id: str | None = None
    conversation_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def steps(self) -> list[StepSpec]:
        return parse_steps(self.definition.get("steps"))

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

    def to_dict(self, *, with_definition: bool = True) -> dict[str, Any]:
        data = {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            "status": self.status,
            "goal": self.goal,
            "model_id": self.model_id,
            "task_id": self.task_id,
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "metadata": dict(self.metadata),
            "step_count": len(self.steps),
        }
        if with_definition:
            data["definition"] = dict(self.definition)
        return data


@dataclass
class WorkflowStep:
    id: str
    workflow_id: str
    seq: int
    kind: str
    status: str
    title: str = ""
    spec: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    ended_at: str | None = None
    output: str | None = None
    error: str | None = None
    task_id: str | None = None
    tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "seq": self.seq,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "spec": dict(self.spec),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "output": self.output,
            "error": self.error,
            "task_id": self.task_id,
            "tokens": self.tokens,
            "metadata": dict(self.metadata),
        }


def _workflow_from_row(row: Mapping[str, Any]) -> Workflow:
    return Workflow(
        id=row["id"],
        name=row["name"],
        mode=row["mode"],
        status=row["status"],
        definition=json.loads(row["definition"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        goal=row.get("goal") or "",
        model_id=row.get("model_id"),
        task_id=row.get("task_id"),
        conversation_id=row.get("conversation_id"),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        error=row.get("error"),
        metadata=json.loads(row["metadata"]) if row.get("metadata") else {},
    )


def _step_from_row(row: Mapping[str, Any]) -> WorkflowStep:
    return WorkflowStep(
        id=row["id"],
        workflow_id=row["workflow_id"],
        seq=int(row["seq"]),
        kind=row["kind"],
        status=row["status"],
        title=row.get("title") or "",
        spec=json.loads(row["spec"]) if row.get("spec") else {},
        started_at=row.get("started_at"),
        ended_at=row.get("ended_at"),
        output=row.get("output"),
        error=row.get("error"),
        task_id=row.get("task_id"),
        tokens=int(row.get("tokens") or 0),
        metadata=json.loads(row["metadata"]) if row.get("metadata") else {},
    )
