"""Composition and shared configuration for context windows."""

from __future__ import annotations

from archx_agent.helpers.tokens import Tokenizer, default_tokenizer
from archx_agent.managers.base import BaseManager
from archx_agent.managers.conversation import ConversationManager
from archx_agent.managers.memory import MemoryManager
from archx_agent.managers.context.constants import CONTEXT_TABLES, Summarizer
from archx_agent.managers.context.writes import ContextManagerWritesMixin
from archx_agent.managers.context.builder import ContextManagerBuilderMixin
from archx_agent.managers.context.strategies.oldest_first import (
    ContextManagerStrategiesOldestFirstMixin,
)
from archx_agent.managers.context.strategies.summarize import (
    ContextManagerStrategiesSummarizeMixin,
)
from archx_agent.managers.context.strategies.ai_select import (
    ContextManagerStrategiesAiSelectMixin,
)
from archx_agent.managers.context.strategies.manual import (
    ContextManagerStrategiesManualMixin,
)
from archx_agent.managers.context.strategies.proposed import (
    ContextManagerStrategiesProposedMixin,
)
from archx_agent.managers.context.proposals import ContextManagerProposalsMixin
from archx_agent.managers.context.history import ContextManagerHistoryMixin


class ContextManager(
    ContextManagerWritesMixin,
    ContextManagerBuilderMixin,
    ContextManagerStrategiesOldestFirstMixin,
    ContextManagerStrategiesSummarizeMixin,
    ContextManagerStrategiesAiSelectMixin,
    ContextManagerStrategiesManualMixin,
    ContextManagerStrategiesProposedMixin,
    ContextManagerProposalsMixin,
    ContextManagerHistoryMixin,
    BaseManager,
):
    """Compose context windows around shared collaborators."""

    tables = CONTEXT_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        events=None,
        conversations: ConversationManager,
        memory: MemoryManager | None = None,
        tokenizer: Tokenizer | None = None,
        summarizer: Summarizer | None = None,
        context_limit: int = 2048,
        output_budget: int = 512,
        reserve_tokens: int = 256,
        memory_budget_ratio: float = 0.25,
        protect_pinned: bool = True,
        default_strategy: str = "oldest_first",
    ) -> None:
        self.conversations = conversations
        self.memory = memory
        self.tokenizer = tokenizer or default_tokenizer()
        self.summarizer = summarizer
        #: recorded in every stored summary so a simulated/absent generator is visible
        self.summary_generator = "model"
        self.context_limit = context_limit
        self.output_budget = output_budget
        self.reserve_tokens = reserve_tokens
        self.memory_budget_ratio = memory_budget_ratio
        self.protect_pinned = protect_pinned
        self.default_strategy = default_strategy
        super().__init__(store, coordinator, events=events)
