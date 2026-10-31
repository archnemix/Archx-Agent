"""Ai select operations for context windows."""

from __future__ import annotations

from typing import Any, Sequence

from archx_agent.helpers.exceptions import ContextOverflowError
from archx_agent.helpers.timeutil import new_id
from archx_agent.managers.conversation import Message
from archx_agent.managers.memory import tokens_of, similarity
from archx_agent.managers.context.records import ContextItem, ContextManifest
from archx_agent.managers.context.formatting import _message_units


class ContextManagerStrategiesAiSelectMixin:
    """Strategies Ai Select responsibility for ContextManager."""

    def _ai_select(
        self,
        conversation_id: str,
        messages: Sequence[Message],
        user_message: str | None,
        system_prompt: str | None,
        available: int,
        extra_instructions: str | None,
    ) -> ContextManifest:
        query_tokens = tokens_of(user_message or "")
        included: list[ContextItem] = []
        omitted: list[dict[str, Any]] = []
        used = 0
        if extra_instructions:
            included.append(
                ContextItem(
                    "system",
                    "instructions",
                    "system",
                    extra_instructions,
                    self.tokenizer.count(extra_instructions),
                    True,
                    "instructions",
                )
            )
            used += self.tokenizer.count(extra_instructions)
        units = _message_units(messages)
        scored: list[tuple[float, list[Message], str]] = []
        for unit in units:
            text = " ".join(m.content for m in unit)
            score = similarity(query_tokens, tokens_of(text)) if query_tokens else 0.0
            is_recent = unit[0].seq >= (messages[-1].seq - 3 if messages else 0)
            pinned = any(m.pinned for m in unit)
            reason_bits = []
            if pinned:
                score += 2.0
                reason_bits.append("pinned")
            if is_recent:
                score += 1.0
                reason_bits.append("recent")
            if query_tokens and score > 0.05:
                reason_bits.append("relevant to the request")
            scored.append((score, unit, ", ".join(reason_bits) or "low relevance"))

        # pinned and recent first, then by relevance
        scored.sort(key=lambda item: (-item[0], item[1][0].seq), reverse=False)
        kept: list[tuple[Message, str]] = []
        for score, unit, reason in scored:
            unit_tokens = sum(self._cost(m) for m in unit)
            pinned_unit = any(m.pinned for m in unit)
            if used + unit_tokens > available:
                if pinned_unit and self.protect_pinned:
                    raise ContextOverflowError(
                        "pinned messages do not fit in the context budget; unpin something or raise the limit",
                        available=available,
                    )
                for m in unit:
                    omitted.append(
                        {
                            "kind": "message",
                            "ref_id": m.id,
                            "seq": m.seq,
                            "tokens": self._cost(m),
                            "reason": f"not selected (score {score:.2f}, {reason})",
                            "score": round(score, 3),
                        }
                    )
                continue
            for m in unit:
                kept.append((m, reason))
            used += unit_tokens
        kept.sort(key=lambda pair: pair[0].seq)
        for message, reason in kept:
            included.append(
                ContextItem(
                    "message",
                    message.id,
                    message.role,
                    message.content,
                    self._cost(message),
                    message.pinned,
                    f"selected: {reason}"
                    + ("" if query_tokens else " (no request text to match)"),
                )
            )
        return ContextManifest(
            id=new_id("ctx_"),
            conversation_id=conversation_id,
            strategy="ai_select",
            budget=available,
            tokens_used=used,
            included=included,
            omitted=omitted,
            injected=[],
            notes="selection is heuristic relevance scoring (deterministic), not a model judgement; "
            "each item records why it was included or excluded",
        )
