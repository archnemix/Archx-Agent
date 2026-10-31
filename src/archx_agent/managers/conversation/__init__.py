"""Conversations and messages.

Guarantees
----------
* Message order is ``(conversation_id, seq)`` where ``seq`` is allocated inside
  the write transaction - never by timestamp.
* Clearing the visible context (:meth:`ConversationManager.clear_context`) marks
  messages ``excluded`` but never deletes them; deleting a conversation is a
  separate, explicit, recoverable operation.
* Every write goes through the shared coordinator, so each one is journalled.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .manager import ConversationManager as ConversationManager
from .constants import CONVERSATION_TABLES as CONVERSATION_TABLES, ROLES as ROLES
from .records import (
    Message as Message,
    Conversation as Conversation,
    _message_from_row as _message_from_row,
    _conversation_from_row as _conversation_from_row,
)
from .matching import _escape_like as _escape_like, _excerpt as _excerpt


__all__ = ["ConversationManager", "Conversation", "Message", "ROLES"]
