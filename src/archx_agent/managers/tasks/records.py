"""Record types and row conversion for task history."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archx_agent.managers.tasks.constants import TERMINAL_STATUSES
from archx_agent.managers.tasks.validation import _json


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
