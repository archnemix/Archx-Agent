"""Record types and row conversion for tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    summary: str
    capability: str | None
    risk: str
    inputs: dict[str, str]
    required: tuple[str, ...] = ()
    types: dict[str, str] = field(default_factory=dict)
    supports_dry_run: bool = False
    side_effects: str = "none"
    builtin: bool = True
    origin: str = "builtin"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": self.summary,
            "capability": self.capability,
            "risk": self.risk,
            "inputs": self.inputs,
            "required": list(self.required),
            "types": self.types or {name: "str" for name in self.inputs},
            "supports_dry_run": self.supports_dry_run,
            "side_effects": self.side_effects,
            "builtin": self.builtin,
            "origin": self.origin,
            "protected": self.capability is not None,
        }


@dataclass
class ToolContext:
    conversation_id: str | None = None
    task_id: str | None = None
    project_id: str | None = None
    purpose: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "purpose": self.purpose,
        }


@dataclass
class ToolRun:
    """What happened when a tool was asked to do something.

    A run exists for refusals too: "the agent tried to write a file and was
    denied" is exactly the evidence a permission system must keep.
    """

    id: str
    tool: str
    status: str  # running | succeeded | failed | denied
    arguments: dict[str, Any]
    started_at: str
    ended_at: str | None = None
    duration_ms: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    permission_id: str | None = None
    approval_id: str | None = None
    decision: str | None = None
    dry_run: bool = False
    truncated: bool = False
    seq: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "status": self.status,
            "arguments": self.arguments,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "error": self.error,
            "permission_id": self.permission_id,
            "approval_id": self.approval_id,
            "decision": self.decision,
            "dry_run": self.dry_run,
            "truncated": self.truncated,
            "seq": self.seq,
        }
