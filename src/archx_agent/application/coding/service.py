"""Service composition and shared collaborators for coding sessions."""

from __future__ import annotations

from typing import Any, Mapping

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolError,
)
from archx_agent.managers.coding import CodeSession
from archx_agent.managers.tools import ToolContext
from archx_agent.application.coding.sessions import CodingWorkspaceSessionsMixin
from archx_agent.application.coding.files import CodingWorkspaceFilesMixin
from archx_agent.application.coding.commands import CodingWorkspaceCommandsMixin

from .records import _Before


class CodingWorkspace(
    CodingWorkspaceSessionsMixin,
    CodingWorkspaceFilesMixin,
    CodingWorkspaceCommandsMixin,
):
    """Sessions, edits and runs. Constructed per access from the workspace, like the others."""

    _Before = _Before

    def __init__(self, ws) -> None:
        self.ws = ws

    @property
    def manager(self):
        return self.ws.coding

    def _context(self, session: CodeSession, purpose: str) -> ToolContext:
        return ToolContext(
            task_id=session.task_id,
            project_id=session.project_id,
            purpose=purpose,
        )

    def _execute(self, name: str, arguments: Mapping[str, Any], context: ToolContext):
        """Run one tool. A refusal becomes a domain error naming the approval, not a half-write."""
        run = self.ws.tools.execute(
            name, arguments, context=context, requester="coding"
        )
        if run.status == "denied":
            approval = getattr(run, "approval_id", None)
            reason = run.error or f"{name} was refused"
            if approval:
                raise ApprovalRequiredError(
                    f"{name} needs approval: approve {approval} or grant the capability",
                    approval_id=approval,
                )
            raise PermissionDeniedError(reason)
        if run.status == "failed":
            raise ToolError(run.error or f"{name} failed")
        return run
