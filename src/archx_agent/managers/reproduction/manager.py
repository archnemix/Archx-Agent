"""Compose ReproductionManager; implementation parts share one manager instance."""

from __future__ import annotations
from ..base import BaseManager
from .records import REPRODUCTION_TABLES

from .writes import ReproductionManagerWritesMixin
from .environment import ReproductionManagerEnvironmentMixin
from .tools import ReproductionManagerToolsMixin
from .assessment import ReproductionManagerAssessmentMixin
from .records_api import ReproductionManagerRecordsApiMixin


class ReproductionManager(
    ReproductionManagerWritesMixin,
    ReproductionManagerEnvironmentMixin,
    ReproductionManagerToolsMixin,
    ReproductionManagerAssessmentMixin,
    ReproductionManagerRecordsApiMixin,
    BaseManager,
):
    """Assess, record and re-check how a task could be reproduced."""

    tables = REPRODUCTION_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        tasks,
        models=None,
        tools=None,
        conversations=None,
        mcp=None,
        extensions=None,
        config=None,
        events=None,
        home: str | None = None,
        app_version: str = "",
        schema_version: int | None = None,
    ) -> None:
        self.tasks = tasks
        self.models = models
        self.tools = tools
        self.conversations = conversations
        self.mcp = mcp
        self.extensions = extensions
        self.config = config
        self.home = home
        self.app_version = app_version
        self._schema_version = schema_version
        super().__init__(store, coordinator, events=events)
