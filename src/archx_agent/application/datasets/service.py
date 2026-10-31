"""Service composition and shared collaborators for dataset preparation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolError,
)
from archx_agent.managers.tools import ToolContext
from archx_agent.application.datasets.scanning import DatasetServiceScanningMixin
from archx_agent.application.datasets.cleaning import DatasetServiceCleaningMixin
from archx_agent.application.datasets.splitting import DatasetServiceSplittingMixin
from archx_agent.application.datasets.exports import DatasetServiceExportsMixin
from archx_agent.application.datasets.queries import DatasetServiceQueriesMixin


class DatasetService(
    DatasetServiceScanningMixin,
    DatasetServiceCleaningMixin,
    DatasetServiceSplittingMixin,
    DatasetServiceExportsMixin,
    DatasetServiceQueriesMixin,
):
    """Build a dataset out of files in the tool roots, and keep every decision visible."""

    def __init__(self, ws) -> None:
        self.ws = ws

    @property
    def manager(self):
        return self.ws.datasets

    def _execute(self, name: str, arguments: dict[str, Any], context: ToolContext):
        run = self.ws.tools.execute(
            name, arguments, context=context, requester="datasets"
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
        base = Path(self.ws.config.path("paths.artifacts")) / "datasets"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def create(
        self,
        name: str,
        sources: list[str],
        *,
        license: str | None = None,
        notes: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        dataset = self.manager.create(
            name=name,
            sources=[str(s) for s in sources],
            license=(license or "unknown"),
            task_id=task_id,
            metadata={"notes": notes} if notes else {},
        )
        return self.view(dataset.id)
