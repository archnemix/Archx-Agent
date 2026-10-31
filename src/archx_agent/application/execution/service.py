"""Service composition and shared collaborators for execution targets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolError,
)
from archx_agent.managers.tools import ToolContext
from archx_agent.application.execution.targets import ExecutionServiceTargetsMixin
from archx_agent.application.execution.runner import ExecutionServiceRunnerMixin
from archx_agent.application.execution.remote import ExecutionServiceRemoteMixin
from archx_agent.application.execution.sync import ExecutionServiceSyncMixin
from archx_agent.application.execution.presentation import (
    ExecutionServicePresentationMixin,
)


class ExecutionService(
    ExecutionServiceTargetsMixin,
    ExecutionServiceRunnerMixin,
    ExecutionServiceRemoteMixin,
    ExecutionServiceSyncMixin,
    ExecutionServicePresentationMixin,
):
    """Run a command on a chosen backend, and record where it ran and what came back."""

    def __init__(self, ws) -> None:
        self.ws = ws

    @property
    def manager(self):
        return self.ws.execution

    def _execute(self, name: str, arguments: dict[str, Any], purpose: str):
        run = self.ws.tools.execute(
            name, arguments, context=ToolContext(purpose=purpose), requester="execution"
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

    def _artifacts_dir(self) -> Path:
        base = Path(self.ws.config.path("paths.artifacts")) / "execution"
        base.mkdir(parents=True, exist_ok=True)
        return base
