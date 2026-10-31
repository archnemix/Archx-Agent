"""Composition and shared configuration for learning records."""

from __future__ import annotations

from typing import Any

from archx_agent.managers.base import BaseManager
from archx_agent.managers.learning.constants import LEARNING_TABLES
from archx_agent.managers.learning.writes import LearningManagerWritesMixin
from archx_agent.managers.learning.goals import LearningManagerGoalsMixin
from archx_agent.managers.learning.items import LearningManagerItemsMixin
from archx_agent.managers.learning.sessions import LearningManagerSessionsMixin
from archx_agent.managers.learning.queries import LearningManagerQueriesMixin


class LearningManager(
    LearningManagerWritesMixin,
    LearningManagerGoalsMixin,
    LearningManagerItemsMixin,
    LearningManagerSessionsMixin,
    LearningManagerQueriesMixin,
    BaseManager,
):
    """Rows for goals, items, sessions and attempts. Scheduling lives in the service."""

    tables = LEARNING_TABLES

    def __init__(self, store, coordinator, *, events=None, config=None) -> None:
        self.config = config
        super().__init__(store, coordinator, events=events)

    def _cfg(self, key: str, default: Any) -> Any:
        config = getattr(self, "config", None)
        if config is None:
            return default
        try:
            return config.get(key)
        except Exception:  # noqa: BLE001 - a missing key must not break a read
            return default
