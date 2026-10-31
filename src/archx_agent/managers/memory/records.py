"""Record types and row conversion for memory governance."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from archx_agent.managers.memory.constants import INJECTABLE


@dataclass
class Memory:
    id: str
    kind: str
    scope: str
    scope_id: str | None
    slot: str | None
    title: str
    content: str
    summary: str | None
    category: str
    project_id: str | None
    conversation_id: str | None
    task_id: str | None
    source: str
    provenance: dict[str, Any]
    confidence: float
    status: str
    pinned: bool
    tags: list[str]
    details: dict[str, Any]
    evidence: list[Any]
    verification: str | None
    environment: str | None
    limitations: str | None
    worked: bool | None
    expires_at: str | None
    last_accessed_at: str | None
    access_count: int
    duplicate_of: str | None
    supersedes: str | None
    version: int
    embedding_state: str
    embedding_ref: str | None
    artifact_path: str | None
    checksum: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "slot": self.slot,
            "title": self.title,
            "content": self.content,
            "summary": self.summary,
            "category": self.category,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "task_id": self.task_id,
            "source": self.source,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "status": self.status,
            "pinned": self.pinned,
            "tags": self.tags,
            "details": self.details,
            "evidence": self.evidence,
            "verification": self.verification,
            "environment": self.environment,
            "limitations": self.limitations,
            "worked": self.worked,
            "expires_at": self.expires_at,
            "last_accessed_at": self.last_accessed_at,
            "access_count": self.access_count,
            "duplicate_of": self.duplicate_of,
            "supersedes": self.supersedes,
            "version": self.version,
            "embedding_state": self.embedding_state,
            "embedding_ref": self.embedding_ref,
            "artifact_path": self.artifact_path,
            "checksum": self.checksum,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }

    @property
    def is_injectable(self) -> bool:
        return self.kind in INJECTABLE and self.status == "active"

    @property
    def is_current(self) -> bool:
        return self.status == "active" and self.deleted_at is None


@dataclass
class SearchHit:
    memory: Memory
    score: float
    reason: str


@dataclass
class SearchOutcome:
    hits: list[SearchHit]
    mode: str
    degraded: bool
    degraded_reason: str | None = None

    @property
    def items(self) -> list[Memory]:
        return [h.memory for h in self.hits]


@dataclass
class RetrievalResult:
    items: list[Memory]
    tokens_used: int
    budget: int
    omitted: list[dict[str, Any]] = field(default_factory=list)
    included: list[dict[str, Any]] = field(default_factory=list)
    degraded: bool = False
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [m.to_dict() for m in self.items],
            "tokens_used": self.tokens_used,
            "budget": self.budget,
            "included": self.included,
            "omitted": self.omitted,
            "degraded": self.degraded,
            "notes": self.notes,
        }


def _row_to_memory(row: dict[str, Any]) -> Memory:
    return Memory(
        id=row["id"],
        kind=row["kind"],
        scope=row["scope"],
        scope_id=row["scope_id"],
        slot=row["slot"],
        title=row["title"],
        content=row["content"],
        summary=row["summary"],
        category=row["category"],
        project_id=row["project_id"],
        conversation_id=row["conversation_id"],
        task_id=row["task_id"],
        source=row["source"],
        provenance=json.loads(row["provenance"]) if row["provenance"] else {},
        confidence=row["confidence"],
        status=row["status"],
        pinned=bool(row["pinned"]),
        tags=json.loads(row["tags"]) if row["tags"] else [],
        details=json.loads(row["details"]) if row["details"] else {},
        evidence=json.loads(row["evidence"]) if row["evidence"] else [],
        verification=row["verification"],
        environment=row["environment"],
        limitations=row["limitations"],
        worked=None if row["worked"] is None else bool(row["worked"]),
        expires_at=row["expires_at"],
        last_accessed_at=row["last_accessed_at"],
        access_count=row["access_count"],
        duplicate_of=row["duplicate_of"],
        supersedes=row["supersedes"],
        version=row["version"],
        embedding_state=row["embedding_state"],
        embedding_ref=row["embedding_ref"],
        artifact_path=row["artifact_path"],
        checksum=row["checksum"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )
