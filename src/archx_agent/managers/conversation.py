"""Conversations and messages.

Guarantees
----------
* Message order is ``(conversation_id, seq)`` where ``seq`` is allocated inside
  the write transaction - never by timestamp.
* Clearing the visible context (:meth:`ConversationManager.clear_context`) marks
  messages ``excluded`` but never deletes them; deleting a conversation is a
  separate, explicit, recoverable operation.
* Every write goes through the shared coordinator, so each one is journalled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.helpers.tokens import Tokenizer, default_tokenizer

from .base import BaseManager

CONVERSATION_TABLES = ("conversations", "messages", "conversation_settings")

ROLES = ("system", "user", "assistant", "tool")


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


class ConversationManager(BaseManager):
    tables = CONVERSATION_TABLES

    def __init__(self, store, coordinator, *, events=None, tokenizer: Tokenizer | None = None) -> None:
        self.tokenizer = tokenizer or default_tokenizer()
        super().__init__(store, coordinator, events=events)

    # -- write handlers ---------------------------------------------------
    def register_handlers(self) -> None:
        self.coordinator.register("conversation.create", self._apply_create)
        self.coordinator.register("conversation.update", self._apply_update)
        self.coordinator.register("message.append", self._apply_message)
        self.coordinator.register("message.update", self._apply_message_update)

    def _apply_create(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        conv = payload["conversation"]
        tx.execute(
            "INSERT INTO conversations(id, title, created_at, updated_at, last_seq, project_id, model_id,"
            " context_strategy, archived, deleted_at, pinned, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                conv["id"],
                conv["title"],
                conv["created_at"],
                conv["updated_at"],
                conv.get("last_seq", 0),
                conv.get("project_id"),
                conv.get("model_id"),
                conv.get("context_strategy"),
                int(conv.get("archived", False)),
                conv.get("deleted_at"),
                int(conv.get("pinned", False)),
                json_text(conv.get("metadata") or {}),
            ),
        )
        return {"id": conv["id"]}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        conv_id = payload["id"]
        fields = payload["fields"]
        allowed = {
            "title",
            "model_id",
            "context_strategy",
            "archived",
            "deleted_at",
            "pinned",
            "project_id",
            "metadata",
            "updated_at",
        }
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValidationError(f"cannot update conversation field {key!r}")
            if key == "metadata":
                value = json_text(value or {})
            if key in {"archived", "pinned"}:
                value = int(bool(value))
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:
            return {"id": conv_id, "changed": 0}
        sets.append("updated_at = ?")
        params.append(fields.get("updated_at") or iso_now())
        params.append(conv_id)
        changed = tx.execute(f"UPDATE conversations SET {', '.join(sets)} WHERE id = ?", params)
        return {"id": conv_id, "changed": changed}

    def _apply_message(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        msg = payload["message"]
        seq = tx.scalar(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id = ?",
            (msg["conversation_id"],),
        )
        tx.execute(
            "INSERT INTO messages(id, conversation_id, seq, role, content, created_at, token_estimate,"
            " pinned, excluded, tool_calls, tool_results, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                msg["id"],
                msg["conversation_id"],
                int(seq),
                msg["role"],
                msg["content"],
                msg["created_at"],
                msg.get("token_estimate", 0),
                int(msg.get("pinned", False)),
                int(msg.get("excluded", False)),
                json_text(msg.get("tool_calls") or []),
                json_text(msg.get("tool_results") or []),
                json_text(msg.get("metadata") or {}),
            ),
        )
        tx.execute(
            "UPDATE conversations SET last_seq = ?, updated_at = ? WHERE id = ?",
            (int(seq), msg["created_at"], msg["conversation_id"]),
        )
        return {"id": msg["id"], "seq": int(seq)}

    def _apply_message_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        msg_id = payload["id"]
        fields = payload["fields"]
        allowed = {"content", "pinned", "excluded", "metadata", "tool_calls", "tool_results"}
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValidationError(f"cannot update message field {key!r}")
            if key in {"pinned", "excluded"}:
                value = int(bool(value))
            elif key in {"metadata", "tool_calls", "tool_results"}:
                value = json_text(value or ({} if key == "metadata" else []))
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:
            return {"id": msg_id, "changed": 0}
        params.append(msg_id)
        changed = tx.execute(f"UPDATE messages SET {', '.join(sets)} WHERE id = ?", params)
        return {"id": msg_id, "changed": changed}

    # -- conversations ----------------------------------------------------
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

    def get(self, conversation_id: str, *, include_deleted: bool = False) -> Result[Conversation]:
        row = self.store.query_one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        if row is None:
            return Err(NotFoundError(f"conversation {conversation_id} not found", id=conversation_id))
        conv = _conversation_from_row(row)
        if conv.deleted_at and not include_deleted:
            return Err(NotFoundError(f"conversation {conversation_id} was deleted", id=conversation_id))
        return Ok(conv)

    def require(self, conversation_id: str) -> Conversation:
        return self.get(conversation_id).ok_or_raise()

    def list_conversations(
        self,
        *,
        search: str | None = None,
        project_id: str | None = None,
        include_archived: bool = False,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        clauses = []
        params: list[Any] = []
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if not include_archived:
            clauses.append("archived = 0")
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if search:
            clauses.append(
                "(title LIKE ? ESCAPE '\\' OR id IN (SELECT conversation_id FROM messages"
                " WHERE content LIKE ? ESCAPE '\\'))"
            )
            like = f"%{_escape_like(search)}%"
            params.extend([like, like])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.store.query(
            f"SELECT * FROM conversations{where} ORDER BY pinned DESC, updated_at DESC, id LIMIT ? OFFSET ?",
            (*params, max(1, limit), max(0, offset)),
        )
        return [_conversation_from_row(r) for r in rows]

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Search conversation titles and message bodies; returns ranked hits."""
        query = (query or "").strip()
        if len(query) < 2:
            return []
        like = f"%{_escape_like(query)}%"
        hits: dict[str, dict[str, Any]] = {}
        for row in self.store.query(
            "SELECT id, title, updated_at FROM conversations WHERE deleted_at IS NULL AND title LIKE ? ESCAPE '\\'"
            " ORDER BY updated_at DESC LIMIT ?",
            (like, limit),
        ):
            hits[row["id"]] = {
                "conversation_id": row["id"],
                "title": row["title"],
                "matched": "title",
                "excerpt": row["title"],
                "updated_at": row["updated_at"],
                "score": 2.0,
            }
        for row in self.store.query(
            "SELECT m.conversation_id, m.content, m.seq, c.title, c.updated_at FROM messages m"
            " JOIN conversations c ON c.id = m.conversation_id"
            " WHERE c.deleted_at IS NULL AND m.content LIKE ? ESCAPE '\\'"
            " ORDER BY c.updated_at DESC, m.seq DESC LIMIT ?",
            (like, limit * 3),
        ):
            cid = row["conversation_id"]
            excerpt = _excerpt(row["content"], query)
            existing = hits.get(cid)
            score = 1.0 + min(1.0, row["content"].lower().count(query.lower()) / 5)
            if existing:
                existing["score"] += score
                if existing["matched"] == "title":
                    existing["matched"] = "title+message"
            else:
                hits[cid] = {
                    "conversation_id": cid,
                    "title": row["title"],
                    "matched": "message",
                    "excerpt": excerpt,
                    "updated_at": row["updated_at"],
                    "score": score,
                    "seq": row["seq"],
                }
        ordered = sorted(hits.values(), key=lambda h: (-h["score"], h["updated_at"]), reverse=False)
        return ordered[:limit]

    def rename(self, conversation_id: str, title: str) -> Conversation:
        title = (title or "").strip()
        if not title:
            raise ValidationError("conversation title must not be empty")
        self.require(conversation_id)
        self._write("conversation.update", {"id": conversation_id, "fields": {"title": title}})
        self.trace("conversation", "conversation.renamed", conversation_id=conversation_id, payload={"title": title})
        return self.require(conversation_id)

    def set_model(self, conversation_id: str, model_id: str | None) -> None:
        self._write("conversation.update", {"id": conversation_id, "fields": {"model_id": model_id}})

    def set_context_strategy(self, conversation_id: str, strategy: str | None) -> None:
        self._write("conversation.update", {"id": conversation_id, "fields": {"context_strategy": strategy}})

    def attach_project(self, conversation_id: str, project_id: str) -> Result["Conversation"]:
        """Attach a conversation to a project (one project per conversation)."""
        existing = self.get(conversation_id)
        if existing.is_err:
            return existing
        self.link_project(conversation_id, project_id)
        return self.get(conversation_id)

    def archive(self, conversation_id: str, archived: bool = True) -> None:
        self._write("conversation.update", {"id": conversation_id, "fields": {"archived": archived}})

    def pin(self, conversation_id: str, pinned: bool = True) -> None:
        self._write("conversation.update", {"id": conversation_id, "fields": {"pinned": pinned}})

    def link_project(self, conversation_id: str, project_id: str | None) -> None:
        self._write("conversation.update", {"id": conversation_id, "fields": {"project_id": project_id}})

    def delete(self, conversation_id: str, *, hard: bool = False, confirm: bool = False) -> str:
        """Delete a conversation.

        Soft delete (default) hides it but keeps the data recoverable. Hard
        delete removes messages and the conversation row and requires
        ``confirm=True``.
        """
        self.require(conversation_id)
        if hard:
            if not confirm:
                raise ValidationError("hard delete requires explicit confirmation")
            deleted = self.store.scalar("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,))
            with self.store.write_tx() as tx:
                tx.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
                tx.execute("DELETE FROM conversation_settings WHERE conversation_id = ?", (conversation_id,))
                tx.execute("UPDATE conversations SET deleted_at = ? WHERE id = ?", (iso_now(), conversation_id))
            self.trace(
                "conversation",
                "conversation.hard_deleted",
                conversation_id=conversation_id,
                payload={"messages_removed": int(deleted or 0)},
            )
            return "hard_deleted"
        self._write("conversation.update", {"id": conversation_id, "fields": {"deleted_at": iso_now()}})
        self.trace("conversation", "conversation.deleted", conversation_id=conversation_id)
        return "soft_deleted"

    def restore(self, conversation_id: str) -> Conversation:
        self.get(conversation_id, include_deleted=True).ok_or_raise()
        self._write("conversation.update", {"id": conversation_id, "fields": {"deleted_at": None}})
        return self.require(conversation_id)

    # -- messages ---------------------------------------------------------
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
            raise ValidationError(f"invalid role {role!r} (expected one of {list(ROLES)})")
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
            self.store.scalar("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,)) or 0
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
            changed = tx.execute("UPDATE messages SET excluded = 0 WHERE conversation_id = ?", (conversation_id,))
        self.trace("conversation", "context.restored", conversation_id=conversation_id)
        return int(changed)

    def pin_message(self, message_id: str, pinned: bool = True) -> None:
        self._write("message.update", {"id": message_id, "fields": {"pinned": pinned}})

    def exclude_message(self, message_id: str, excluded: bool = True) -> None:
        self._write("message.update", {"id": message_id, "fields": {"excluded": excluded}})

    def edit_message(self, message_id: str, content: str) -> None:
        self._write(
            "message.update",
            {"id": message_id, "fields": {"content": content}},
        )
        self.trace("message", "message.edited", message_id=message_id, payload={"chars": len(content)})

    def find_message(self, message_id: str) -> Message | None:
        row = self.store.query_one("SELECT * FROM messages WHERE id = ?", (message_id,))
        return _message_from_row(row) if row else None

    # -- settings ---------------------------------------------------------
    def set_setting(self, conversation_id: str, key: str, value: Any) -> None:
        with self.store.write_tx() as tx:
            tx.execute(
                "INSERT INTO conversation_settings(conversation_id, key, value) VALUES (?,?,?)"
                " ON CONFLICT(conversation_id) DO UPDATE SET key=excluded.key, value=excluded.value",
                (conversation_id, key, json_text(value)),
            )

    def get_setting(self, conversation_id: str, key: str, default: Any = None) -> Any:
        row = self.store.query_one(
            "SELECT value FROM conversation_settings WHERE conversation_id = ? AND key = ?", (conversation_id, key)
        )
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:  # pragma: no cover
            return default

    def settings(self, conversation_id: str) -> dict[str, Any]:
        out = {}
        for row in self.store.query(
            "SELECT key, value FROM conversation_settings WHERE conversation_id = ?", (conversation_id,)
        ):
            try:
                out[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:  # pragma: no cover
                out[row["key"]] = row["value"]
        return out

    # -- export -----------------------------------------------------------
    def export(self, conversation_id: str, *, fmt: str = "json", include_excluded: bool = True) -> str:
        conv = self.require(conversation_id)
        messages = self.messages(conversation_id, include_excluded=include_excluded)
        if fmt == "json":
            return json_text(
                {
                    "conversation": conv.to_dict(),
                    "messages": [m.to_dict() for m in messages],
                    "exported_at": iso_now(),
                }
            )
        if fmt == "markdown":
            lines = [f"# {conv.title}", "", f"_Created {conv.created_at} - exported {iso_now()}_", ""]
            for msg in messages:
                lines.append(f"## {msg.role} ({msg.created_at})")
                lines.append("")
                lines.append(msg.content)
                lines.append("")
            return "\n".join(lines)
        raise ValidationError(f"unsupported export format {fmt!r} (use json or markdown)")

    def stats(self) -> dict[str, Any]:
        return {
            "conversations": self.table_count("conversations"),
            "messages": self.table_count("messages"),
            "active_conversations": int(
                self.store.scalar("SELECT COUNT(*) FROM conversations WHERE deleted_at IS NULL") or 0
            ),
        }


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _excerpt(content: str, query: str, *, width: int = 120) -> str:
    lower = content.lower()
    idx = lower.find(query.lower())
    if idx < 0:
        return content[:width]
    start = max(0, idx - width // 3)
    end = min(len(content), start + width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    return f"{prefix}{content[start:end]}{suffix}"


__all__ = ["ConversationManager", "Conversation", "Message", "ROLES"]
