"""ConversationManager manager."""

from __future__ import annotations


from archx_agent.helpers.tokens import Tokenizer, default_tokenizer
from archx_agent.managers.base import BaseManager
from archx_agent.managers.conversation.constants import CONVERSATION_TABLES
from archx_agent.managers.conversation.writes import ConversationManagerWritesMixin
from archx_agent.managers.conversation.lifecycle import (
    ConversationManagerLifecycleMixin,
)
from archx_agent.managers.conversation.queries import ConversationManagerQueriesMixin
from archx_agent.managers.conversation.messages import ConversationManagerMessagesMixin
from archx_agent.managers.conversation.settings import ConversationManagerSettingsMixin


class ConversationManager(
    ConversationManagerWritesMixin,
    ConversationManagerLifecycleMixin,
    ConversationManagerQueriesMixin,
    ConversationManagerMessagesMixin,
    ConversationManagerSettingsMixin,
    BaseManager,
):
    """Manager responsibility for ConversationManager."""

    tables = CONVERSATION_TABLES

    def __init__(
        self, store, coordinator, *, events=None, tokenizer: Tokenizer | None = None
    ) -> None:
        self.tokenizer = tokenizer or default_tokenizer()
        super().__init__(store, coordinator, events=events)
