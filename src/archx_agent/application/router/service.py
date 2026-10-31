"""Compose ModelRouter responsibilities and initialize dependencies."""

from __future__ import annotations

from typing import Any, Callable
from archx_agent.managers.models import ModelManager, ModelRecord

from .evaluation import ModelRouterEvaluationMixin
from .selection import ModelRouterSelectionMixin
from .probing import ModelRouterProbingMixin

class ModelRouter(ModelRouterEvaluationMixin, ModelRouterSelectionMixin, ModelRouterProbingMixin):
    'Selects models for tasks using capability states and workspace policy.'

    def __init__(
        self,
        models: ModelManager,
        *,
        config: Any,
        runtime_for: Callable[[ModelRecord], Any],
        availability_check: Callable[[ModelRecord], tuple[bool, str]] | None = None,
        remote_check: Callable[[ModelRecord], None] | None = None,
        events: Any | None = None,
    ) -> None:
        self.models = models
        self.config = config
        self.runtime_for = runtime_for
        self.availability_check = availability_check
        self.remote_check = remote_check
        self.events = events
