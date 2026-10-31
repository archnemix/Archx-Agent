"""Oldest first operations for context windows."""

from __future__ import annotations

from typing import Any, Sequence

from archx_agent.helpers.exceptions import ContextOverflowError
from archx_agent.helpers.timeutil import new_id
from archx_agent.managers.conversation import Message
from archx_agent.managers.context.records import ContextItem, ContextManifest
from archx_agent.managers.context.formatting import _message_units


class ContextManagerStrategiesOldestFirstMixin:
    """Strategies Oldest First responsibility for ContextManager."""

    def _oldest_first(
        self,
        conversation_id: str,
        messages: Sequence[Message],
        user_message: str | None,
        system_prompt: str | None,
        available: int,
        extra_instructions: str | None,
    ) -> ContextManifest:
        included: list[ContextItem] = []
        omitted: list[dict[str, Any]] = []
        used = 0
        if extra_instructions:
            item = ContextItem(
                "system",
                "instructions",
                "system",
                extra_instructions,
                self.tokenizer.count(extra_instructions),
                True,
                "instructions",
            )
            included.append(item)
            used += item.tokens
        # newest first, protecting pinned content and whole tool units
        units = _message_units(messages)
        kept: list[ContextItem] = []
        for unit in reversed(units):
            unit_tokens = sum(self._cost(m) for m in unit)
            pinned_unit = any(m.pinned for m in unit)
            if used + unit_tokens > available and not (
                pinned_unit and self.protect_pinned
            ):
                for m in unit:
                    omitted.append(
                        {
                            "kind": "message",
                            "ref_id": m.id,
                            "seq": m.seq,
                            "role": m.role,
                            "tokens": self._cost(m),
                            "reason": "older turn dropped to fit the context window (stored, not deleted)",
                        }
                    )
                continue
            for m in unit:
                kept.append(
                    ContextItem(
                        "message",
                        m.id,
                        m.role,
                        m.content,
                        self._cost(m),
                        m.pinned,
                        "pinned" if m.pinned else "recent turn",
                    )
                )
                used += self._cost(m)
        kept.reverse()
        included.extend(kept)
        pinned_tokens = sum(i.tokens for i in included if i.pinned)
        if pinned_tokens > available:
            raise ContextOverflowError(
                f"pinned content alone needs {pinned_tokens} tokens but only {available} are available; "
                "unpin something or raise the context limit (pinned content is never dropped silently)",
                pinned_tokens=pinned_tokens,
                available=available,
            )
        return ContextManifest(
            id=new_id("ctx_"),
            conversation_id=conversation_id,
            strategy="oldest_first",
            budget=available,
            tokens_used=used,
            included=included,
            omitted=omitted,
            injected=[],
            notes=None,
            summarizer=None,
        )
