"""Compose ResearchManager responsibilities and initialize dependencies."""

from __future__ import annotations

from archx_agent.managers.base import BaseManager
from .records import RESEARCH_TABLES

from .writes import ResearchManagerWritesMixin
from .queries import ResearchManagerQueriesMixin
from .lifecycle import ResearchManagerLifecycleMixin
from .sources import ResearchManagerSourcesMixin

class ResearchManager(ResearchManagerWritesMixin, ResearchManagerQueriesMixin, ResearchManagerLifecycleMixin, ResearchManagerSourcesMixin, BaseManager):
    'Rows for research runs and their sources. No planning, no fetching, no prose.'

    tables = RESEARCH_TABLES

    def __init__(self, store, coordinator, *, events=None, config=None) -> None:
        self.config = config
        super().__init__(store, coordinator, events=events)
