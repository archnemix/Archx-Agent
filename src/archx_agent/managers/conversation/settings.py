"""ConversationManager settings."""

from __future__ import annotations

import json
from typing import Any

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.jsonio import json_text


class ConversationManagerSettingsMixin:
    """Settings responsibility for ConversationManager."""

    def set_setting(self, conversation_id: str, key: str, value: Any) -> None:
        self.require(conversation_id)
        if not isinstance(key, str) or not key.strip():
            raise ValidationError("conversation setting key must be a nonempty string")
        try:
            encoded = json_text(value)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ValidationError(
                "conversation setting value must be JSON serializable"
            ) from exc
        self._write(
            "conversation.setting",
            {
                "conversation_id": conversation_id,
                "key": key,
                "value": encoded,
            },
        )

    def get_setting(self, conversation_id: str, key: str, default: Any = None) -> Any:
        row = self.store.query_one(
            "SELECT value FROM conversation_settings WHERE conversation_id = ? AND key = ?",
            (conversation_id, key),
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
            "SELECT key, value FROM conversation_settings WHERE conversation_id = ?",
            (conversation_id,),
        ):
            try:
                out[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:  # pragma: no cover
                out[row["key"]] = row["value"]
        return out
