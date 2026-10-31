"""Proposed operations for context windows."""

from __future__ import annotations

from typing import Any, Sequence

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.timeutil import new_id
from archx_agent.managers.conversation import Message
from archx_agent.managers.context.records import ContextItem, ContextManifest, Proposal


class ContextManagerStrategiesProposedMixin:
    """Strategies Proposed responsibility for ContextManager."""

    def _from_proposal(
        self,
        conversation_id: str,
        messages: Sequence[Message],
        user_message: str | None,
        system_prompt: str | None,
        available: int,
        proposal: Proposal,
        extra_instructions: str | None,
    ) -> ContextManifest:
        remove_ids = {entry["ref_id"] for entry in proposal.remove}
        retain_ids = {entry["ref_id"] for entry in proposal.retain}
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
        for entry in proposal.summarise:
            summary = self._find_summary(
                conversation_id, entry["start_seq"], entry["end_seq"]
            )
            if summary is None:
                if self.summarizer is None:
                    raise ValidationError(
                        "the approved proposal requires summarisation but no summariser is configured; "
                        "configure a model or reject the proposal"
                    )
                text = self.summarizer(
                    [
                        m
                        for m in messages
                        if entry["start_seq"] <= m.seq <= entry["end_seq"]
                    ],
                    "Summarise for the approved proposal.",
                )
                summary = self.save_summary(
                    conversation_id,
                    entry["start_seq"],
                    entry["end_seq"],
                    text,
                    generator=self.summary_generator,
                )
            cost = self.tokenizer.count(summary.content)
            included.append(
                ContextItem(
                    "summary",
                    summary.id,
                    "system",
                    summary.content,
                    cost,
                    False,
                    "approved summarisation",
                )
            )
            used += cost
        for message in messages:
            if (
                remove_ids
                and message.id in remove_ids
                and not (message.pinned and self.protect_pinned)
            ):
                omitted.append(
                    {
                        "kind": "message",
                        "ref_id": message.id,
                        "seq": message.seq,
                        "tokens": self._cost(message),
                        "reason": "removed by an approved proposal",
                    }
                )
                continue
            if any(
                entry["start_seq"] <= message.seq <= entry["end_seq"]
                for entry in proposal.summarise
            ) and not (message.pinned and self.protect_pinned):
                omitted.append(
                    {
                        "kind": "message",
                        "ref_id": message.id,
                        "seq": message.seq,
                        "tokens": self._cost(message),
                        "reason": "replaced by an approved summary",
                    }
                )
                continue
            cost = self._cost(message)
            if used + cost > available and not (message.pinned and self.protect_pinned):
                omitted.append(
                    {
                        "kind": "message",
                        "ref_id": message.id,
                        "seq": message.seq,
                        "reason": "over budget",
                    }
                )
                continue
            included.append(
                ContextItem(
                    "message",
                    message.id,
                    message.role,
                    message.content,
                    cost,
                    message.pinned,
                    "retained by approved proposal"
                    if message.id in retain_ids
                    else "kept",
                )
            )
            used += cost
        return ContextManifest(
            id=new_id("ctx_"),
            conversation_id=conversation_id,
            strategy="ai_proposed",
            budget=available,
            tokens_used=used,
            included=included,
            omitted=omitted,
            injected=[],
            notes=f"applied approved proposal {proposal.id}: {proposal.rationale}",
            proposal_id=proposal.id,
        )
