"""Record types and row conversion for context windows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextItem:
    kind: str  # message | summary | memory | system | request | project
    ref_id: str
    role: str
    content: str
    tokens: int
    pinned: bool = False
    reason: str = ""
    untrusted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref_id": self.ref_id,
            "role": self.role,
            "tokens": self.tokens,
            "pinned": self.pinned,
            "reason": self.reason,
            "untrusted": self.untrusted,
            "preview": self.content[:120],
        }


@dataclass
class ContextManifest:
    id: str
    conversation_id: str
    strategy: str
    budget: int
    tokens_used: int
    included: list[ContextItem]
    omitted: list[dict[str, Any]]
    injected: list[dict[str, str]]
    notes: str | None = None
    degraded: bool = False
    summarizer: str | None = None
    memory_tokens: int = 0
    created_at: str = ""
    proposal_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "strategy": self.strategy,
            "budget": self.budget,
            "tokens_used": self.tokens_used,
            "included": [i.to_dict() for i in self.included],
            "omitted": self.omitted,
            "injected": self.injected,
            "notes": self.notes,
            "degraded": self.degraded,
            "summarizer": self.summarizer,
            "memory_tokens": self.memory_tokens,
            "created_at": self.created_at,
            "proposal_id": self.proposal_id,
        }


@dataclass
class Proposal:
    """An AI-proposed context change. Nothing is applied until approved."""

    id: str
    conversation_id: str
    strategy: str
    summarise: list[dict[str, Any]] = field(default_factory=list)
    remove: list[dict[str, Any]] = field(default_factory=list)
    retain: list[dict[str, Any]] = field(default_factory=list)
    retrieve: list[dict[str, Any]] = field(default_factory=list)
    rationale: str = ""
    estimated_tokens: int = 0
    created_at: str = ""
    approved_at: str | None = None
    rejected_at: str | None = None
    applied_manifest_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "strategy": self.strategy,
            "summarise": self.summarise,
            "remove": self.remove,
            "retain": self.retain,
            "retrieve": self.retrieve,
            "rationale": self.rationale,
            "estimated_tokens": self.estimated_tokens,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "rejected_at": self.rejected_at,
            "applied_manifest_id": self.applied_manifest_id,
            "requires_approval": True,
        }


@dataclass
class Summary:
    id: str
    conversation_id: str
    source_start_seq: int
    source_end_seq: int
    content: str
    token_estimate: int
    generator: str
    created_at: str
    superseded_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "source_start_seq": self.source_start_seq,
            "source_end_seq": self.source_end_seq,
            "content": self.content,
            "token_estimate": self.token_estimate,
            "generator": self.generator,
            "created_at": self.created_at,
            "superseded_by": self.superseded_by,
        }


def _summary_from_row(row: dict[str, Any]) -> Summary:
    return Summary(
        id=row["id"],
        conversation_id=row["conversation_id"],
        source_start_seq=row["source_start_seq"],
        source_end_seq=row["source_end_seq"],
        content=row["content"],
        token_estimate=row["token_estimate"],
        generator=row["generator"],
        created_at=row["created_at"],
        superseded_by=row["superseded_by"],
    )
