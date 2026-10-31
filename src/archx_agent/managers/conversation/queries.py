"""ConversationManager queries."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.conversation.records import (
    Conversation,
    _conversation_from_row,
)
from archx_agent.managers.conversation.matching import _escape_like, _excerpt


class ConversationManagerQueriesMixin:
    """Queries responsibility for ConversationManager."""

    def get(
        self, conversation_id: str, *, include_deleted: bool = False
    ) -> Result[Conversation]:
        row = self.store.query_one(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        )
        if row is None:
            return Err(
                NotFoundError(
                    f"conversation {conversation_id} not found", id=conversation_id
                )
            )
        conv = _conversation_from_row(row)
        if conv.deleted_at and not include_deleted:
            return Err(
                NotFoundError(
                    f"conversation {conversation_id} was deleted", id=conversation_id
                )
            )
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
        ordered = sorted(
            hits.values(), key=lambda h: (-h["score"], h["updated_at"]), reverse=False
        )
        return ordered[:limit]

    def export(
        self, conversation_id: str, *, fmt: str = "json", include_excluded: bool = True
    ) -> str:
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
            lines = [
                f"# {conv.title}",
                "",
                f"_Created {conv.created_at} - exported {iso_now()}_",
                "",
            ]
            for msg in messages:
                lines.append(f"## {msg.role} ({msg.created_at})")
                lines.append("")
                lines.append(msg.content)
                lines.append("")
            return "\n".join(lines)
        raise ValidationError(
            f"unsupported export format {fmt!r} (use json or markdown)"
        )

    def stats(self) -> dict[str, Any]:
        return {
            "conversations": self.table_count("conversations"),
            "messages": self.table_count("messages"),
            "active_conversations": int(
                self.store.scalar(
                    "SELECT COUNT(*) FROM conversations WHERE deleted_at IS NULL"
                )
                or 0
            ),
        }
