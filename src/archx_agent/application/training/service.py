"""Service composition and shared collaborators for training workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolError,
)
from archx_agent.managers.tools import ToolContext
from archx_agent.application.training.preflight import TrainingServicePreflightMixin
from archx_agent.application.training.runner import TrainingServiceRunnerMixin
from archx_agent.application.training.artifacts import TrainingServiceArtifactsMixin
from archx_agent.application.training.evaluation import TrainingServiceEvaluationMixin


class TrainingService(
    TrainingServicePreflightMixin,
    TrainingServiceRunnerMixin,
    TrainingServiceArtifactsMixin,
    TrainingServiceEvaluationMixin,
):
    """Run the two trainers that work here, and say why the others cannot."""

    def __init__(self, ws) -> None:
        self.ws = ws

    @property
    def manager(self):
        return self.ws.training

    def _execute(self, name: str, arguments: dict[str, Any], context: ToolContext):
        run = self.ws.tools.execute(
            name, arguments, context=context, requester="training"
        )
        if run.status == "denied":
            approval = getattr(run, "approval_id", None)
            if approval:
                raise ApprovalRequiredError(
                    f"{name} needs approval: approve {approval} or grant the capability",
                    approval_id=approval,
                )
            raise PermissionDeniedError(run.error or f"{name} was refused")
        if run.status == "failed":
            raise ToolError(run.error or f"{name} failed")
        return run

    def _context(self, purpose: str, task_id: str | None = None) -> ToolContext:
        return ToolContext(task_id=task_id, purpose=purpose)

    def _artifacts_dir(self) -> Path:
        base = Path(self.ws.config.path("paths.artifacts")) / "training"
        base.mkdir(parents=True, exist_ok=True)
        return base
