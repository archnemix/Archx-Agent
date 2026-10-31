"""Composition and shared configuration for workflow definitions."""

from __future__ import annotations

from typing import Any

from archx_agent.managers.base import BaseManager
from archx_agent.managers.workflows.constants import WORKFLOW_TABLES
from archx_agent.managers.workflows.writes import WorkflowManagerWritesMixin
from archx_agent.managers.workflows.lifecycle import WorkflowManagerLifecycleMixin
from archx_agent.managers.workflows.history import WorkflowManagerHistoryMixin
from archx_agent.managers.workflows.queries import WorkflowManagerQueriesMixin


class WorkflowManager(
    WorkflowManagerWritesMixin,
    WorkflowManagerLifecycleMixin,
    WorkflowManagerHistoryMixin,
    WorkflowManagerQueriesMixin,
    BaseManager,
):
    """Definition records, status transitions and ordered step rows."""

    tables = WORKFLOW_TABLES

    def __init__(
        self, store, coordinator, *, events=None, config=None, tools=None
    ) -> None:
        self.config = config
        self.tools = tools
        super().__init__(store, coordinator, events=events)

    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001
            return default
