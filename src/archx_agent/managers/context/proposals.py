"""Proposals operations for context windows."""

from __future__ import annotations

import json
from typing import Any

from archx_agent.helpers.exceptions import NotFoundError
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.context.records import Proposal


class ContextManagerProposalsMixin:
    """Proposals responsibility for ContextManager."""

    def propose(
        self,
        conversation_id: str,
        *,
        user_message: str | None = None,
        budget_tokens: int | None = None,
    ) -> Proposal:
        """Propose context changes. Never applies anything."""
        self.conversations.require(conversation_id)
        budget = budget_tokens if budget_tokens is not None else self.budget()
        messages = self.conversations.messages(conversation_id)
        total = sum(self.tokenizer.count(m.content) for m in messages)
        proposal = Proposal(
            id=new_id("prop_"),
            conversation_id=conversation_id,
            strategy="ai_proposed",
            created_at=iso_now(),
        )
        if total <= budget:
            proposal.rationale = f"the conversation fits in the {budget}-token budget; no change is needed"
            proposal.retain = [
                {"ref_id": m.id, "seq": m.seq, "reason": "fits the budget"}
                for m in messages
            ]
            proposal.estimated_tokens = total
            self._save_proposal(proposal)
            self.trace(
                "context",
                "context.proposal",
                conversation_id=conversation_id,
                payload={
                    "proposal_id": proposal.id,
                    "changes": 0,
                    "estimated_tokens": total,
                },
            )
            return proposal
        keep_recent = max(2, len(messages) // 4)
        older = messages[:-keep_recent]
        recent = messages[-keep_recent:]
        if older:
            proposal.summarise = [
                {
                    "start_seq": older[0].seq,
                    "end_seq": older[-1].seq,
                    "reason": "older messages can be summarised without losing the originals",
                }
            ]
        proposal.retain = [
            {"ref_id": m.id, "seq": m.seq, "reason": "recent turn"} for m in recent
        ]
        proposal.rationale = (
            f"conversation uses ~{total} tokens against a {budget}-token budget; summarise "
            f"messages {older[0].seq if older else 0}-{older[-1].seq if older else 0} and keep the last {len(recent)}"
        )
        proposal.estimated_tokens = sum(self.tokenizer.count(m.content) for m in recent)
        self._save_proposal(proposal)
        self.trace(
            "context",
            "context.proposal",
            conversation_id=conversation_id,
            payload={
                "proposal_id": proposal.id,
                "summarise": proposal.summarise,
                "retained": [r["ref_id"] for r in proposal.retain],
                "estimated_tokens": proposal.estimated_tokens,
                "requires_approval": True,
            },
        )
        return proposal

    def get_proposal(self, proposal_id: str) -> Proposal:
        row = self.store.query_one(
            "SELECT * FROM context_proposals WHERE id = ?", (proposal_id,)
        )
        if row is None:
            raise NotFoundError(f"proposal {proposal_id} not found", id=proposal_id)
        data = json.loads(row["payload"])
        return Proposal(
            id=data["id"],
            conversation_id=data["conversation_id"],
            strategy=data.get("strategy", "ai_proposed"),
            summarise=data.get("summarise") or [],
            remove=data.get("remove") or [],
            retain=data.get("retain") or [],
            retrieve=data.get("retrieve") or [],
            rationale=data.get("rationale") or "",
            estimated_tokens=int(data.get("estimated_tokens") or 0),
            created_at=data.get("created_at") or row["created_at"],
            approved_at=row["approved_at"],
            rejected_at=row["rejected_at"],
            applied_manifest_id=row["applied_manifest_id"],
        )

    def proposals(self, conversation_id: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.store.query(
            "SELECT id, rationale, estimated_tokens, created_at, approved_at, applied_manifest_id,"
            " rejected_at FROM context_proposals WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
            (conversation_id, limit),
        )

    def reject_proposal(self, proposal_id: str, *, reason: str = "") -> None:
        self.get_proposal(proposal_id)
        with self.store.write_tx() as tx:
            tx.execute(
                "UPDATE context_proposals SET rejected_at = ?, rationale = COALESCE(rationale,'') || ? WHERE id = ?",
                (
                    iso_now(),
                    f" [rejected: {reason}]" if reason else " [rejected]",
                    proposal_id,
                ),
            )
        self.trace(
            "context",
            "context.proposal_rejected",
            payload={"proposal_id": proposal_id, "reason": reason},
        )

    def _save_proposal(self, proposal: Proposal) -> None:
        self._write("context.proposal", {"proposal": proposal.to_dict()})

    def mark_proposal_applied(self, proposal_id: str, manifest_id: str) -> None:
        with self.store.write_tx() as tx:
            tx.execute(
                "UPDATE context_proposals SET approved_at = ?, applied_manifest_id = ? WHERE id = ?",
                (iso_now(), manifest_id, proposal_id),
            )
        self.trace(
            "context",
            "context.proposal_applied",
            payload={"proposal_id": proposal_id, "manifest_id": manifest_id},
        )
