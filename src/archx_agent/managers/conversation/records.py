"""ConversationManager records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    id: str
    conversation_id: str
    seq: int
    role: str
    content: str
    created_at: str
    token_estimate: int = 0
    pinned: bool = False
    excluded: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "seq": self.seq,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "token_estimate": self.token_estimate,
            "pinned": self.pinned,
            "excluded": self.excluded,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "metadata": self.metadata,
        }

    def as_chat_message(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str
    last_seq: int = 0
    project_id: str | None = None
    model_id: str | None = None
    context_strategy: str | None = None
    archived: bool = False
    deleted_at: str | None = None
    pinned: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_seq": self.last_seq,
            "project_id": self.project_id,
            "model_id": self.model_id,
            "context_strategy": self.context_strategy,
            "archived": self.archived,
            "deleted_at": self.deleted_at,
            "pinned": self.pinned,
            "metadata": self.metadata,
        }


def _message_from_row(row: dict[str, Any]) -> Message:
    return Message(
        id=row["id"],
        conversation_id=row["conversation_id"],
        seq=row["seq"],
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
        token_estimate=row["token_estimate"],
        pinned=bool(row["pinned"]),
        excluded=bool(row["excluded"]),
        tool_calls=json.loads(row["tool_calls"]) if row["tool_calls"] else [],
        tool_results=json.loads(row["tool_results"]) if row["tool_results"] else [],
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
    )


def _conversation_from_row(row: dict[str, Any]) -> Conversation:
    return Conversation(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_seq=row["last_seq"],
        project_id=row["project_id"],
        model_id=row["model_id"],
        context_strategy=row["context_strategy"],
        archived=bool(row["archived"]),
        deleted_at=row["deleted_at"],
        pinned=bool(row["pinned"]),
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
    )
