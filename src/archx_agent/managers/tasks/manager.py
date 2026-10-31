"""Composition and shared configuration for task history."""

from __future__ import annotations

from archx_agent.helpers.timeutil import new_id
from archx_agent.managers.base import BaseManager
from archx_agent.managers.tasks.constants import TASK_TABLES
from archx_agent.managers.tasks.writes import TaskManagerWritesMixin
from archx_agent.managers.tasks.lifecycle import TaskManagerLifecycleMixin
from archx_agent.managers.tasks.history import TaskManagerHistoryMixin
from archx_agent.managers.tasks.artifacts import TaskManagerArtifactsMixin
from archx_agent.managers.tasks.queries import TaskManagerQueriesMixin


class TaskManager(
    TaskManagerWritesMixin,
    TaskManagerLifecycleMixin,
    TaskManagerHistoryMixin,
    TaskManagerArtifactsMixin,
    TaskManagerQueriesMixin,
    BaseManager,
):
    """Durable task history plus the artifacts a task produced."""

    tables = TASK_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        events=None,
        versions=None,
        home: str | None = None,
        max_version_bytes: int = 1_048_576,
        instance: str | None = None,
    ) -> None:
        self.versions = versions
        self.home = home
        self.max_version_bytes = int(max_version_bytes)
        # Every opened workspace is an owner. A task records which instance and process
        # started it, so a later open can tell "this is stale" from "another process is
        # still working on it" instead of guessing.
        self.instance = instance or new_id("ws_")
        super().__init__(store, coordinator, events=events)
