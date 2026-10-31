"""Manual operations for context windows."""

from __future__ import annotations

from typing import Any, Sequence

from archx_agent.helpers.exceptions import ContextOverflowError
from archx_agent.helpers.timeutil import new_id
from archx_agent.managers.conversation import Message
from archx_agent.managers.context.records import ContextItem, ContextManifest


class ContextManagerStrategiesManualMixin:
    """Strategies Manual responsibility for ContextManager."""

    def _manual(
        self,
        conversation_id: str,
        messages: Sequence[Message],
        user_message: str | None,
        system_prompt: str | None,
        budget: int,
        manual_ids: Sequence[str],
        memory_items: Sequence[ContextItem],
        extra_instructions: str | None,
    ) -> ContextManifest:
        selected = set(manual_ids)
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
        for message in messages:
            take = message.id in selected or (message.pinned and self.protect_pinned)
            cost = self._cost(message)
            if take:
                if (
                    used
                    + cost
                    + (self.tokenizer.count(user_message) if user_message else 0)
                    > budget
                ):
                    raise ContextOverflowError(
                        f"the manual selection needs more than the {budget}-token budget; "
                        "deselect some messages (pinned items are never dropped silently)",
                        budget=budget,
                        requested=len(selected),
                    )
                included.append(
                    ContextItem(
                        "message",
                        message.id,
                        message.role,
                        message.content,
                        cost,
                        message.pinned,
                        "manually included"
                        if message.id in selected
                        else "pinned (always kept)",
                    )
                )
                used += cost
            else:
                omitted.append(
                    {
                        "kind": "message",
                        "ref_id": message.id,
                        "seq": message.seq,
                        "tokens": cost,
                        "reason": "not selected manually",
                    }
                )
        manifest = ContextManifest(
            id=new_id("ctx_"),
            conversation_id=conversation_id,
            strategy="manual",
            budget=budget,
            tokens_used=used,
            included=included,
            omitted=omitted,
            injected=[],
            notes=f"{len(selected)} message(s) selected manually",
        )
        return manifest
