"""ConversationManager messages."""

from __future__ import annotations

from typing import Any, Sequence

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.conversation.constants import ROLES
from archx_agent.managers.conversation.records import Message, _message_from_row


class ConversationManagerMessagesMixin:
    """Messages responsibility for ConversationManager."""

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        tool_calls: Sequence[dict[str, Any]] | None = None,
        tool_results: Sequence[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        pinned: bool = False,
        message_id: str | None = None,
    ) -> Message:
        if role not in ROLES:
            raise ValidationError(
                f"invalid role {role!r} (expected one of {list(ROLES)})"
            )
        if content is None:
            raise ValidationError("message content must be a string")
        conv = self.require(conversation_id)
        msg = Message(
            id=message_id or new_id("msg_"),
            conversation_id=conv.id,
            seq=0,
            role=role,
            content=content,
            created_at=iso_now(),
            token_estimate=self.tokenizer.count(content),
            pinned=pinned,
            tool_calls=list(tool_calls or []),
            tool_results=list(tool_results or []),
            metadata=metadata or {},
        )
        result = self._write("message.append", {"message": msg.to_dict()})
        msg.seq = int(result["seq"])
        self.trace(
            "message",
            "message.appended",
            conversation_id=conversation_id,
            message_id=msg.id,
            payload={
                "role": role,
                "seq": msg.seq,
                "chars": len(content),
                "tokens": msg.token_estimate,
            },
        )
        return msg

    def messages(
        self,
        conversation_id: str,
        *,
        include_excluded: bool = False,
        limit: int | None = None,
        upto_seq: int | None = None,
    ) -> list[Message]:
        clauses = ["conversation_id = ?"]
        params: list[Any] = [conversation_id]
        if not include_excluded:
            clauses.append("excluded = 0")
        if upto_seq is not None:
            clauses.append("seq <= ?")
            params.append(int(upto_seq))
        sql = f"SELECT * FROM messages WHERE {' AND '.join(clauses)} ORDER BY seq"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [_message_from_row(r) for r in self.store.query(sql, params)]

    def message_count(self, conversation_id: str) -> int:
        return int(
            self.store.scalar(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            or 0
        )

    def context_tokens(self, conversation_id: str) -> int:
        value = self.store.scalar(
            "SELECT COALESCE(SUM(token_estimate), 0) FROM messages WHERE conversation_id = ? AND excluded = 0",
            (conversation_id,),
        )
        return int(value or 0)

    def clear_context(self, conversation_id: str) -> int:
        """Hide messages from the active context without deleting history."""
        self.require(conversation_id)
        with self.store.write_tx() as tx:
            changed = tx.execute(
                "UPDATE messages SET excluded = 1 WHERE conversation_id = ? AND excluded = 0 AND pinned = 0",
                (conversation_id,),
            )
        self.trace(
            "conversation",
            "context.cleared",
            conversation_id=conversation_id,
            payload={"messages_hidden": int(changed)},
        )
        return int(changed)

    def restore_context(self, conversation_id: str) -> int:
        with self.store.write_tx() as tx:
            changed = tx.execute(
                "UPDATE messages SET excluded = 0 WHERE conversation_id = ?",
                (conversation_id,),
            )
        self.trace("conversation", "context.restored", conversation_id=conversation_id)
        return int(changed)

    def pin_message(self, message_id: str, pinned: bool = True) -> None:
        self._write("message.update", {"id": message_id, "fields": {"pinned": pinned}})

    def exclude_message(self, message_id: str, excluded: bool = True) -> None:
        self._write(
            "message.update", {"id": message_id, "fields": {"excluded": excluded}}
        )

    def edit_message(self, message_id: str, content: str) -> None:
        self._write(
            "message.update",
            {"id": message_id, "fields": {"content": content}},
        )
        self.trace(
            "message",
            "message.edited",
            message_id=message_id,
            payload={"chars": len(content)},
        )

    def find_message(self, message_id: str) -> Message | None:
        row = self.store.query_one("SELECT * FROM messages WHERE id = ?", (message_id,))
        return _message_from_row(row) if row else None
