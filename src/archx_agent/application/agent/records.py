"""AgentRunner records, constants and pure validation helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from archx_agent.helpers.exceptions import (
    ArchxError,
    ValidationError,
)

PLAN_SYSTEM_PROMPT = (
    "You are a planner for a local-first assistant. Reply with ONE JSON object and nothing "
    "else. The object has keys: name (short), goal, and steps (a list). Each step has a "
    "kind: 'model' (with 'prompt'), 'tool' (with 'tool' and 'args'), 'memory' (with "
    "'query'), 'note' (with 'text'), or 'subagent' (with 'goal'). Use {{goal}} and "
    "{{step.N.output}} inside prompts to refer to earlier results. Only name tools from "
    "the provided list. Never invent capabilities; the user still has to grant them."
)

MAX_OUTPUT = 8000

@dataclass
class Budget:
    max_steps: int
    max_seconds: float
    token_budget: int
    max_subagents: int
    steps_done: int = 0
    tokens: int = 0
    subagents: int = 0
    started: float = field(default_factory=time.perf_counter)

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    def check(self) -> None:
        if self.elapsed > self.max_seconds:
            raise ValidationError(
                f"the workflow exceeded agent.max_wall_seconds={int(self.max_seconds)}s "
                f"after {self.steps_done} step(s)"
            )
        if self.tokens > self.token_budget:
            raise ValidationError(
                f"the workflow used {self.tokens} tokens, above agent.token_budget={self.token_budget}"
            )

@dataclass
class RunResult:
    workflow_id: str
    task_id: str
    status: str
    steps: list[dict[str, Any]]
    summary: str
    tokens: int
    elapsed_ms: float
    cancelled: bool = False
    approval_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "status": self.status,
            "steps": self.steps,
            "summary": self.summary,
            "tokens": self.tokens,
            "elapsed_ms": self.elapsed_ms,
            "cancelled": self.cancelled,
            "approval_id": self.approval_id,
        }

class WorkflowFailed(ArchxError):
    """A run stopped because a step failed.

    Carries the workflow and task ids so a caller can report them without re-querying, and
    the approval id when the failure was a missing permission (the run is resumable after
    approval because nothing was granted and nothing ran).
    """

    def __init__(
        self,
        message: str,
        *,
        workflow_id: str | None = None,
        task_id: str | None = None,
        approval_id: str | None = None,
        steps: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.workflow_id = workflow_id
        self.task_id = task_id
        self.approval_id = approval_id
        self.steps = steps or []

class RunPaused(Exception):
    """A run stopped at a step boundary because a pause was requested.

    Everything already written stays: the workflow is still ``running``, the task is
    still open, and ``cursor`` says how many steps are done - which is exactly what
    ``run(resume=True)`` needs.
    """

    def __init__(
        self,
        message: str,
        *,
        workflow_id: str,
        task_id: str,
        conversation_id: str | None,
        cursor: int,
        steps: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.workflow_id = workflow_id
        self.task_id = task_id
        self.conversation_id = conversation_id
        self.cursor = cursor
        self.steps = steps or []

def _walk(steps):
    for step in steps:
        yield step
        yield from _walk(step.steps)
