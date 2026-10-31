"""ConversationManager lifecycle."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.result import Result
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.conversation.records import Conversation


class ConversationManagerLifecycleMixin:
    """Lifecycle responsibility for ConversationManager."""

    def create(
        self,
        title: str = "New conversation",
        *,
        project_id: str | None = None,
        model_id: str | None = None,
        context_strategy: str | None = None,
        metadata: dict[str, Any] | None = None,
        conversation_id: str | None = None,
    ) -> Conversation:
        title = (title or "").strip() or "New conversation"
        if len(title) > 300:
            raise ValidationError("conversation title must be 300 characters or fewer")
        now = iso_now()
        conv = Conversation(
            id=conversation_id or new_id("conv_"),
            title=title,
            created_at=now,
            updated_at=now,
            project_id=project_id,
            model_id=model_id,
            context_strategy=context_strategy,
            metadata=metadata or {},
        )
        self._write("conversation.create", {"conversation": conv.to_dict()})
        self.trace(
            "conversation",
            "conversation.created",
            conversation_id=conv.id,
            payload={"title": conv.title, "project_id": project_id},
        )
        return conv

    def rename(self, conversation_id: str, title: str) -> Conversation:
        title = (title or "").strip()
        if not title:
            raise ValidationError("conversation title must not be empty")
        self.require(conversation_id)
        self._write(
            "conversation.update", {"id": conversation_id, "fields": {"title": title}}
        )
        self.trace(
            "conversation",
            "conversation.renamed",
            conversation_id=conversation_id,
            payload={"title": title},
        )
        return self.require(conversation_id)

    def set_model(self, conversation_id: str, model_id: str | None) -> None:
        self._write(
            "conversation.update",
            {"id": conversation_id, "fields": {"model_id": model_id}},
        )

    def set_context_strategy(self, conversation_id: str, strategy: str | None) -> None:
        self._write(
            "conversation.update",
            {"id": conversation_id, "fields": {"context_strategy": strategy}},
        )

    def attach_project(
        self, conversation_id: str, project_id: str
    ) -> Result["Conversation"]:
        """Attach a conversation to a project (one project per conversation)."""
        existing = self.get(conversation_id)
        if existing.is_err:
            return existing
        self.link_project(conversation_id, project_id)
        return self.get(conversation_id)

    def archive(self, conversation_id: str, archived: bool = True) -> None:
        self._write(
            "conversation.update",
            {"id": conversation_id, "fields": {"archived": archived}},
        )

    def pin(self, conversation_id: str, pinned: bool = True) -> None:
        self._write(
            "conversation.update", {"id": conversation_id, "fields": {"pinned": pinned}}
        )

    def link_project(self, conversation_id: str, project_id: str | None) -> None:
        self._write(
            "conversation.update",
            {"id": conversation_id, "fields": {"project_id": project_id}},
        )

    def delete(
        self, conversation_id: str, *, hard: bool = False, confirm: bool = False
    ) -> str:
        """Delete a conversation.

        Soft delete (default) hides it but keeps the data recoverable. Hard
        delete removes messages and the conversation row and requires
        ``confirm=True``.
        """
        self.require(conversation_id)
        if hard:
            if not confirm:
                raise ValidationError("hard delete requires explicit confirmation")
            deleted = self.store.scalar(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            with self.store.write_tx() as tx:
                tx.execute(
                    "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
                )
                tx.execute(
                    "DELETE FROM conversation_settings WHERE conversation_id = ?",
                    (conversation_id,),
                )
                tx.execute(
                    "UPDATE conversations SET deleted_at = ? WHERE id = ?",
                    (iso_now(), conversation_id),
                )
            self.trace(
                "conversation",
                "conversation.hard_deleted",
                conversation_id=conversation_id,
                payload={"messages_removed": int(deleted or 0)},
            )
            return "hard_deleted"
        self._write(
            "conversation.update",
            {"id": conversation_id, "fields": {"deleted_at": iso_now()}},
        )
        self.trace(
            "conversation", "conversation.deleted", conversation_id=conversation_id
        )
        return "soft_deleted"

    def restore(self, conversation_id: str) -> Conversation:
        self.get(conversation_id, include_deleted=True).ok_or_raise()
        self._write(
            "conversation.update",
            {"id": conversation_id, "fields": {"deleted_at": None}},
        )
        return self.require(conversation_id)
