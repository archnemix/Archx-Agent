"""Summarize operations for context windows."""

from __future__ import annotations

from typing import Sequence

from archx_agent.helpers.timeutil import new_id
from archx_agent.managers.conversation import Message
from archx_agent.managers.context.records import ContextItem, ContextManifest
from archx_agent.managers.context.formatting import _message_units_flat


class ContextManagerStrategiesSummarizeMixin:
    """Strategies Summarize responsibility for ContextManager."""

    def _summarize(
        self,
        conversation_id: str,
        messages: Sequence[Message],
        user_message: str | None,
        system_prompt: str | None,
        available: int,
        extra_instructions: str | None,
    ) -> ContextManifest:
        total = sum(self.tokenizer.count(m.content) for m in messages)
        if total <= available:
            manifest = self._oldest_first(
                conversation_id,
                messages,
                user_message,
                system_prompt,
                available,
                extra_instructions,
            )
            manifest.strategy = "summarize"
            manifest.notes = "conversation already fits; no summarisation was necessary"
            return manifest
        if self.summarizer is None:
            manifest = self._oldest_first(
                conversation_id,
                messages,
                user_message,
                system_prompt,
                available,
                extra_instructions,
            )
            manifest.strategy = "summarize"
            manifest.degraded = True
            manifest.notes = "no summariser is configured (model unavailable); fell back to oldest-first removal"
            return manifest
        # find how many recent messages fit alongside a summary
        recent: list[Message] = []
        used = 0
        for message in reversed(_message_units_flat(messages)):
            cost = self._cost(message)
            if used + cost > available * 0.6:
                break
            recent.insert(0, message)
            used += cost
        cutoff = recent[0].seq if recent else messages[0].seq
        older = [m for m in messages if m.seq < cutoff]
        if not older:
            manifest = self._oldest_first(
                conversation_id,
                messages,
                user_message,
                system_prompt,
                available,
                extra_instructions,
            )
            manifest.strategy = "summarize"
            manifest.degraded = True
            manifest.notes = "nothing old enough to summarise; used oldest-first"
            return manifest
        existing = self._find_summary(conversation_id, older[0].seq, older[-1].seq)
        if existing is not None:
            summary = existing
            generator = existing.generator
        else:
            try:
                text = self.summarizer(older, "Summarise the conversation above.")
            except Exception as exc:  # noqa: BLE001 - a failed summary must degrade, not crash the turn
                fallback = self._oldest_first(
                    conversation_id,
                    messages,
                    user_message,
                    system_prompt,
                    available,
                    extra_instructions,
                )
                fallback.strategy = "summarize"
                fallback.degraded = True
                fallback.notes = (
                    f"summarisation failed ({type(exc).__name__}); fell back to oldest-first removal "
                    "and kept the originals"
                )
                self.trace(
                    "context",
                    "context.summarize_failed",
                    status="error",
                    conversation_id=conversation_id,
                    error=str(exc),
                )
                return fallback
            if not (text or "").strip():
                fallback = self._oldest_first(
                    conversation_id,
                    messages,
                    user_message,
                    system_prompt,
                    available,
                    extra_instructions,
                )
                fallback.strategy = "summarize"
                fallback.degraded = True
                fallback.notes = (
                    "the summariser returned nothing; fell back to oldest-first removal"
                )
                return fallback
            summary = self.save_summary(
                conversation_id,
                older[0].seq,
                older[-1].seq,
                text,
                generator=self.summary_generator,
            )
            generator = summary.generator
        summary_tokens = self.tokenizer.count(summary.content)
        included: list[ContextItem] = []
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
        included.append(
            ContextItem(
                "summary",
                summary.id,
                "system",
                f"[SUMMARY of messages {summary.source_start_seq}-{summary.source_end_seq}; "
                f"originals are preserved in storage and are not quoted verbatim]\n{summary.content}",
                summary_tokens + 20,
                False,
                "older messages summarised",
                untrusted=False,
            )
        )
        omitted = [
            {
                "kind": "message",
                "ref_id": m.id,
                "seq": m.seq,
                "role": m.role,
                "tokens": self.tokenizer.count(m.content),
                "reason": f"replaced in-context by summary {summary.id} (original stored)",
            }
            for m in older
        ]
        used = sum(i.tokens for i in included)
        for message in recent:
            if message.seq < cutoff:
                continue
            cost = self._cost(message)
            if used + cost > available:
                break
            included.append(
                ContextItem(
                    "message",
                    message.id,
                    message.role,
                    message.content,
                    cost,
                    message.pinned,
                    "recent turn",
                )
            )
            used += cost
        return ContextManifest(
            id=new_id("ctx_"),
            conversation_id=conversation_id,
            strategy="summarize",
            budget=available,
            tokens_used=used,
            included=included,
            omitted=omitted,
            injected=[],
            summarizer=generator,
        )
