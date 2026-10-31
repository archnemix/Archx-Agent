"""ConversationManager writes."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now


class ConversationManagerWritesMixin:
    """Writes responsibility for ConversationManager."""

    def register_handlers(self) -> None:
        self.coordinator.register("conversation.setting", self._apply_setting)
        self.coordinator.register("conversation.create", self._apply_create)
        self.coordinator.register("conversation.update", self._apply_update)
        self.coordinator.register("message.append", self._apply_message)
        self.coordinator.register("message.update", self._apply_message_update)

    def _apply_setting(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        conversation_id = payload["conversation_id"]
        row = tx.query_one(
            "SELECT deleted_at FROM conversations WHERE id = ?", (conversation_id,)
        )
        if row is None or row["deleted_at"] is not None:
            raise ValidationError(
                "cannot set a setting for a missing or deleted conversation"
            )
        key = payload["key"]
        if not isinstance(key, str) or not key.strip():
            raise ValidationError("conversation setting key must be a nonempty string")
        tx.execute(
            "INSERT INTO conversation_settings(conversation_id, key, value) VALUES (?,?,?)"
            " ON CONFLICT(conversation_id, key) DO UPDATE SET value=excluded.value",
            (conversation_id, key, payload["value"]),
        )
        return {"conversation_id": conversation_id, "key": key}

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
        changed = tx.execute(
            f"UPDATE conversations SET {', '.join(sets)} WHERE id = ?", params
        )
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
        allowed = {
            "content",
            "pinned",
            "excluded",
            "metadata",
            "tool_calls",
            "tool_results",
        }
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
        changed = tx.execute(
            f"UPDATE messages SET {', '.join(sets)} WHERE id = ?", params
        )
        return {"id": msg_id, "changed": changed}
