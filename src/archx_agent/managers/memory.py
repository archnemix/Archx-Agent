"""The six memory systems (M17).

| kind | purpose | scope | injected into prompts | lifecycle |
|------|---------|-------|----------------------|-----------|
| active | current task state: goal, constraints, pending steps, tool state | conversation or task | yes, first | expires (TTL) / cleared when the task ends |
| permanent | user-approved durable preferences and facts | global | yes | explicit only; user edits/deletes |
| archival | historical reference material | any | **never** | retention policy marks expired |
| project | goals, decisions, requirements, known issues, commands | project | yes (project scope only) | lives with the project |
| solution | reusable verified solutions | global or project | yes, verified only | retired when disproven |
| learning | learner progress, mistakes, strengths | learner | yes (adaptive) | decays; never a permanent label |

Invariants enforced here:

* every record has provenance (source + origin) and timestamps;
* nothing is silently overwritten - edits snapshot the previous version;
* duplicates are detected (checksum exact, token similarity fuzzy);
* a *slot* conflict supersedes rather than overwrites;
* secrets are refused for permanent memory unless the caller explicitly opts in;
* an unverified solution can never be stored as ``verified``;
* archival memory is never injected into a prompt;
* every retrieval is logged, so "why was this in my context" is answerable.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from archx_agent.helpers import redaction
from archx_agent.helpers.exceptions import DuplicateError, NotFoundError, PathError, ValidationError
from archx_agent.helpers.jsonio import atomic_write_text, json_text, sha256_bytes, sha256_text
from archx_agent.helpers.paths import child_path, ensure_directory, safe_filename
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_from_ts, iso_now, new_id, parse_iso
from archx_agent.helpers.tokens import Tokenizer, default_tokenizer

from .base import BaseManager

MEMORY_TABLES = ("memories", "memory_history", "memory_sources", "memory_retrievals", "learning_events")

KINDS = ("active", "permanent", "archival", "project", "solution", "learning")
SCOPES = ("global", "project", "conversation", "task", "learner")

CATEGORIES = (
    "goal",
    "constraint",
    "pending_step",
    "decision",
    "temporary_decision",
    "preference",
    "fact",
    "instruction",
    "history",
    "architecture",
    "requirement",
    "known_issue",
    "build_command",
    "test_command",
    "accepted_decision",
    "solution",
    "finding",
    "progress",
    "mistake",
    "strength",
    "unresolved_concept",
    "recommendation",
    "tool_state",
    "note",
)

VERIFICATION_STATES = ("verified", "reported", "unverified", "failed", "retired")
SOURCE_TYPES = ("user", "model", "tool", "import", "system", "experiment", "document", "web")

#: never injected into prompts
NEVER_INJECTED = ("archival",)
INJECTABLE = ("active", "permanent", "project", "solution", "learning")

MAX_TITLE = 300
MAX_CONTENT = 200_000

_WORD_RE = re.compile(r"[a-z0-9_]{2,}", re.IGNORECASE)
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "you", "are", "was",
    "were", "has", "have", "had", "not", "but", "all", "any", "can", "will", "would", "should",
    "there", "their", "them", "then", "than", "when", "what", "which", "while", "about", "also",
    "使用", "und", "der", "die", "das",
}


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


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def tokens_of(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "") if w.lower() not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(a: set[str], b: set[str]) -> float:
    """Similarity used for duplicate detection.

    ``max(jaccard, containment)`` so that a short memory and a longer memory
    that fully contains it are still recognised as duplicates - short texts
    make plain Jaccard too lenient.
    """
    if not a or not b:
        return 0.0
    containment = len(a & b) / min(len(a), len(b))
    return max(jaccard(a, b), containment)


class MemoryManager(BaseManager):
    tables = MEMORY_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        events=None,
        artifacts_root: str | None = None,
        tokenizer: Tokenizer | None = None,
        duplicate_threshold: float = 0.92,
        active_ttl_minutes: int = 240,
        embedding_index: Any | None = None,
    ) -> None:
        self.embedding_index = embedding_index
        self.artifacts_root = artifacts_root
        self.tokenizer = tokenizer or default_tokenizer()
        self.duplicate_threshold = duplicate_threshold
        self.active_ttl_minutes = active_ttl_minutes
        super().__init__(store, coordinator, events=events)

    # -- write handlers ---------------------------------------------------
    def register_handlers(self) -> None:
        self.coordinator.register("memory.add", self._apply_add)
        self.coordinator.register("memory.update", self._apply_update)
        self.coordinator.register("memory.status", self._apply_status)
        self.coordinator.register("memory.delete", self._apply_delete)
        self.coordinator.register("memory.source", self._apply_source)
        self.coordinator.register("memory.artifact", self._apply_artifact)

    def _apply_add(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        m = payload["memory"]
        superseded = payload.get("supersede_ids") or []
        for old_id in superseded:
            tx.execute(
                "UPDATE memories SET status='superseded', updated_at=? WHERE id=?",
                (m["created_at"], old_id),
            )
            tx.execute(
                "INSERT INTO memory_history(memory_id, version, change, snapshot, changed_at)"
                " SELECT id, version, 'superseded', '{}', ? FROM memories WHERE id=?",
                (m["created_at"], old_id),
            )
        tx.execute(
            "INSERT INTO memories(id, kind, scope, scope_id, slot, title, content, summary, category,"
            " project_id, conversation_id, task_id, source, provenance, confidence, status, pinned, tags,"
            " details, evidence, verification, environment, limitations, worked, expires_at,"
            " last_accessed_at, access_count, duplicate_of, supersedes, version, embedding_state,"
            " embedding_ref, artifact_path, checksum, created_at, updated_at, deleted_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                m["id"],
                m["kind"],
                m["scope"],
                m.get("scope_id"),
                m.get("slot"),
                m["title"],
                m["content"],
                m.get("summary"),
                m["category"],
                m.get("project_id"),
                m.get("conversation_id"),
                m.get("task_id"),
                m["source"],
                json_text(m.get("provenance") or {}),
                m.get("confidence", 0.8),
                m.get("status", "active"),
                int(bool(m.get("pinned"))),
                json_text(m.get("tags") or []),
                json_text(m.get("details") or {}),
                json_text(m.get("evidence") or []),
                m.get("verification"),
                m.get("environment"),
                m.get("limitations"),
                None if m.get("worked") is None else int(bool(m["worked"])),
                m.get("expires_at"),
                None,
                0,
                m.get("duplicate_of"),
                m.get("supersedes"),
                1,
                m.get("embedding_state", "awaiting"),
                None,
                m.get("artifact_path"),
                m.get("checksum"),
                m["created_at"],
                m["updated_at"],
                None,
            ),
        )
        return {"id": m["id"], "superseded": superseded}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        memory_id = payload["id"]
        fields = payload["fields"]
        row = tx.query_one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        if row is None:
            raise NotFoundError(f"memory {memory_id} not found", id=memory_id)
        tx.execute(
            "INSERT INTO memory_history(memory_id, version, change, snapshot, changed_at) VALUES (?,?,?,?,?)",
            (memory_id, row["version"], payload.get("change", "update"), json_text(row), payload["now"]),
        )
        allowed = {
            "title",
            "content",
            "summary",
            "category",
            "status",
            "pinned",
            "tags",
            "details",
            "evidence",
            "verification",
            "environment",
            "limitations",
            "worked",
            "expires_at",
            "confidence",
            "slot",
            "checksum",
            "embedding_state",
            "embedding_ref",
        }
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValidationError(f"cannot update memory field {key!r}")
            if key in {"tags", "details", "evidence"}:
                value = json_text(value or ({} if key == "details" else []))
            elif key in {"pinned"}:
                value = int(bool(value))
            elif key == "worked":
                value = None if value is None else int(bool(value))
            sets.append(f"{key} = ?")
            params.append(value)
        sets.extend(["version = version + 1", "updated_at = ?"])
        params.append(payload["now"])
        params.append(memory_id)
        tx.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id = ?", params)
        return {"id": memory_id, "version": int(row["version"]) + 1}

    def _apply_status(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        for memory_id in payload["ids"]:
            row = tx.query_one("SELECT version FROM memories WHERE id = ?", (memory_id,))
            if row is None:
                continue
            tx.execute(
                "INSERT INTO memory_history(memory_id, version, change, snapshot, changed_at)"
                " SELECT id, version, ?, '{}', ? FROM memories WHERE id = ?",
                (payload["status"], payload["now"], memory_id),
            )
            tx.execute(
                "UPDATE memories SET status=?, updated_at=? WHERE id=?",
                (payload["status"], payload["now"], memory_id),
            )
        return {"updated": len(payload["ids"])}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        memory_id = payload["id"]
        if payload.get("hard"):
            tx.execute(
                "INSERT INTO memory_history(memory_id, version, change, snapshot, changed_at)"
                " SELECT id, version, 'hard_deleted', ?, ? FROM memories WHERE id = ?",
                (json_text({"checksum": payload.get("checksum")}), payload["now"], memory_id),
            )
            tx.execute("DELETE FROM memory_sources WHERE memory_id = ?", (memory_id,))
            tx.execute("DELETE FROM memory_retrievals WHERE memory_id = ?", (memory_id,))
            tx.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return {"id": memory_id, "hard": True}
        tx.execute(
            "UPDATE memories SET status='deleted', deleted_at=?, updated_at=? WHERE id=?",
            (payload["now"], payload["now"], memory_id),
        )
        tx.execute(
            "INSERT INTO memory_history(memory_id, version, change, snapshot, changed_at)"
            " SELECT id, version, 'deleted', '{}', ? FROM memories WHERE id = ?",
            (payload["now"], memory_id),
        )
        return {"id": memory_id, "hard": False}

    def _apply_source(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "INSERT INTO memory_sources(memory_id, source_type, reference, excerpt, retrieved_at, checksum)"
            " VALUES (?,?,?,?,?,?)",
            (
                payload["memory_id"],
                payload["source_type"],
                payload.get("reference"),
                payload.get("excerpt"),
                payload["now"],
                payload.get("checksum"),
            ),
        )
        return {"memory_id": payload["memory_id"]}

    def _apply_artifact(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "UPDATE memories SET artifact_path = ?, checksum = ?, updated_at = ? WHERE id = ?",
            (payload["path"], payload["checksum"], payload["now"], payload["memory_id"]),
        )
        return {"memory_id": payload["memory_id"], "path": payload["path"]}


    # -- add --------------------------------------------------------------
    def add(
        self,
        kind: str,
        title: str,
        content: str,
        *,
        category: str = "note",
        scope: str | None = None,
        scope_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
        source: str = "user",
        provenance: dict[str, Any] | None = None,
        confidence: float = 0.8,
        tags: Sequence[str] | None = None,
        pinned: bool = False,
        expires_at: str | None = None,
        details: dict[str, Any] | None = None,
        evidence: Sequence[Any] | None = None,
        verification: str | None = None,
        environment: str | None = None,
        limitations: str | None = None,
        worked: bool | None = None,
        slot: str | None = None,
        supersedes: str | None = None,
        summary: str | None = None,
        status: str = "active",
        allow_duplicate: bool = False,
        check_similarity: bool = True,
        allow_sensitive: bool = False,
        now: datetime | None = None,
        op_id: str | None = None,
    ) -> Result[Memory]:
        self._validate(kind, title, content, category, verification, details, allow_sensitive=allow_sensitive)
        scope, scope_id = self._resolve_scope(kind, scope, scope_id, project_id, conversation_id, task_id)
        current = now or datetime.now(timezone.utc)
        created = iso_from_ts(current.timestamp())
        if kind == "active" and expires_at is None and status == "active":
            expires_at = iso_from_ts((current + timedelta(minutes=self.active_ttl_minutes)).timestamp())
        if verification is None and kind == "solution":
            verification = "unverified"

        checksum = self._checksum(kind, scope, scope_id, title, content)
        existing = self.store.query_one(
            "SELECT id, title FROM memories WHERE checksum = ? AND status = 'active' AND deleted_at IS NULL",
            (checksum,),
        )
        if existing and not allow_duplicate:
            self.trace(
                "memory",
                "memory.duplicate_rejected",
                payload={"kind": kind, "existing_id": existing["id"]},
            )
            return Err(
                DuplicateError(
                    f"an identical {kind} memory already exists ({existing['id']})",
                    existing_id=existing["id"],
                    kind=kind,
                )
            )

        # A slot means "replace this logical value", so a similar previous value is
        # expected rather than a duplicate.
        if check_similarity and not allow_duplicate and not slot:
            similar = self.find_similar(
                f"{title} {content}", kinds=(kind,), scope=scope, scope_id=scope_id, limit=3
            )
            strong = [hit for hit in similar if hit.score >= self.duplicate_threshold]
            if strong:
                return Err(
                    DuplicateError(
                        "a very similar memory already exists; pass allow_duplicate=True to store it anyway",
                        existing_id=strong[0].memory.id,
                        score=round(strong[0].score, 3),
                        candidates=[h.memory.id for h in strong],
                    )
                )

        supersede_ids: list[str] = []
        if slot:
            rows = self.store.query(
                "SELECT id FROM memories WHERE kind=? AND scope=? AND COALESCE(scope_id,'')=COALESCE(?,'')"
                " AND slot=? AND status='active' AND deleted_at IS NULL",
                (kind, scope, scope_id, slot),
            )
            supersede_ids = [r["id"] for r in rows if r["id"] != supersedes]

        provenance = dict(provenance or {})
        provenance.setdefault("origin", source)
        provenance.setdefault("recorded_at", created)
        if conversation_id:
            provenance.setdefault("conversation_id", conversation_id)
        if task_id:
            provenance.setdefault("task_id", task_id)
        if project_id:
            provenance.setdefault("project_id", project_id)

        memory = Memory(
            id=new_id("mem_"),
            kind=kind,
            scope=scope,
            scope_id=scope_id,
            slot=slot,
            title=title.strip(),
            content=content,
            summary=summary or (content[:280] if len(content) > 280 else None),
            category=category,
            project_id=project_id,
            conversation_id=conversation_id,
            task_id=task_id,
            source=source,
            provenance=provenance,
            confidence=float(confidence),
            status=status,
            pinned=bool(pinned),
            tags=[str(t) for t in (tags or [])],
            details=dict(details or {}),
            evidence=list(evidence or []),
            verification=verification,
            environment=environment,
            limitations=limitations,
            worked=worked,
            expires_at=expires_at,
            last_accessed_at=None,
            access_count=0,
            duplicate_of=None,
            supersedes=supersedes or (supersede_ids[0] if supersede_ids else None),
            version=1,
            embedding_state="awaiting",
            embedding_ref=None,
            artifact_path=None,
            checksum=checksum,
            created_at=created,
            updated_at=created,
            deleted_at=None,
        )
        self._write(
            "memory.add",
            {"memory": memory.to_dict(), "supersede_ids": supersede_ids},
            op_id=op_id,
        )
        self.trace(
            "memory",
            "memory.added",
            conversation_id=conversation_id,
            task_id=task_id,
            project_id=project_id,
            payload={
                "memory_id": memory.id,
                "kind": kind,
                "scope": scope,
                "category": category,
                "chars": len(content),
                "verification": verification,
                "superseded": supersede_ids,
            },
        )
        return Ok(memory)

    def _validate(
        self,
        kind: str,
        title: str,
        content: str,
        category: str,
        verification: str | None,
        details: dict[str, Any] | None,
        *,
        allow_sensitive: bool,
    ) -> None:
        if kind not in KINDS:
            raise ValidationError(f"unknown memory kind {kind!r} (expected one of {list(KINDS)})")
        if not (title or "").strip():
            raise ValidationError("memory title must not be empty")
        if len(title) > MAX_TITLE:
            raise ValidationError(f"memory title must be {MAX_TITLE} characters or fewer")
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("memory content must not be empty")
        if len(content) > MAX_CONTENT:
            raise ValidationError(f"memory content must be {MAX_CONTENT} characters or fewer")
        if category not in CATEGORIES:
            raise ValidationError(f"unknown memory category {category!r}")
        if verification is not None and verification not in VERIFICATION_STATES:
            raise ValidationError(f"unknown verification state {verification!r}")
        if not allow_sensitive:
            if redaction.looks_secret(content) or redaction.looks_secret(title):
                raise ValidationError(
                    "refusing to store something that looks like a credential; "
                    "use the credential store or pass allow_sensitive=True deliberately"
                )
            if redaction.redact_text(content) != content:
                raise ValidationError(
                    "refusing to store credential-shaped text in memory; "
                    "pass allow_sensitive=True if this is intentional"
                )
        if kind == "solution":
            det = details or {}
            missing = [k for k in ("problem", "solution") if not det.get(k)]
            if missing:
                raise ValidationError(
                    "solution memory requires details.problem and details.solution "
                    f"(missing: {', '.join(missing)})"
                )
            if verification == "verified" and not det.get("evidence"):
                raise ValidationError(
                    "a solution cannot be stored as verified without evidence; "
                    "record how it was verified in details.evidence"
                )
            if verification is None:
                raise ValidationError("solution memory requires a verification state")
        if kind == "learning":
            det = details or {}
            if not det.get("topic"):
                raise ValidationError("learning memory requires details.topic")
            if det.get("permanent_label"):
                raise ValidationError(
                    "learning memory must not store a permanent label about the learner; "
                    "record observations instead"
                )
        if kind == "permanent" and category not in {
            "preference",
            "fact",
            "instruction",
            "constraint",
        }:
            raise ValidationError(
                "permanent memory categories are limited to preference, fact, instruction or constraint"
            )

    def _resolve_scope(
        self,
        kind: str,
        scope: str | None,
        scope_id: str | None,
        project_id: str | None,
        conversation_id: str | None,
        task_id: str | None,
    ) -> tuple[str, str | None]:
        if scope is not None and scope not in SCOPES:
            raise ValidationError(f"unknown memory scope {scope!r} (expected one of {list(SCOPES)})")
        if scope is None:
            if project_id:
                scope, scope_id = "project", project_id
            elif task_id:
                scope, scope_id = "task", task_id
            elif conversation_id:
                scope, scope_id = "conversation", conversation_id
            else:
                scope = "learner" if kind == "learning" else "global"
        if scope == "project":
            scope_id = scope_id or project_id
            if not scope_id:
                raise ValidationError("project-scoped memory requires project_id")
        elif scope == "conversation":
            scope_id = scope_id or conversation_id
            if not scope_id:
                raise ValidationError("conversation-scoped memory requires conversation_id")
        elif scope == "task":
            scope_id = scope_id or task_id
            if not scope_id:
                raise ValidationError("task-scoped memory requires task_id")
        elif scope == "learner" and not scope_id:
            scope_id = "default"
        if kind == "active" and scope not in ("conversation", "task"):
            raise ValidationError("active memory must be scoped to a conversation or a task")
        if kind == "project" and scope != "project":
            raise ValidationError("project memory must use project scope")
        return scope, scope_id

    def _checksum(self, kind: str, scope: str, scope_id: str | None, title: str, content: str) -> str:
        return sha256_text(f"{kind}\x1f{scope}\x1f{scope_id or ''}\x1f{_normalize(title)}\x1f{_normalize(content)}")

    # -- read -------------------------------------------------------------
    def get(self, memory_id: str, *, include_deleted: bool = False) -> Result[Memory]:
        row = self.store.query_one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        if row is None:
            return Err(NotFoundError(f"memory {memory_id} not found", id=memory_id))
        memory = _row_to_memory(row)
        if memory.status == "deleted" and not include_deleted:
            return Err(NotFoundError(f"memory {memory_id} was deleted", id=memory_id))
        return Ok(memory)

    def require(self, memory_id: str) -> Memory:
        return self.get(memory_id).ok_or_raise()

    def list(
        self,
        *,
        kinds: Iterable[str] | None = None,
        scope: str | None = None,
        scope_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
        category: str | None = None,
        status: str | None = "active",
        pinned: bool | None = None,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[Memory]:
        clauses, params = self._filters(
            kinds=kinds,
            scope=scope,
            scope_id=scope_id,
            project_id=project_id,
            conversation_id=conversation_id,
            task_id=task_id,
            category=category,
            status=status,
            pinned=pinned,
            include_deleted=include_deleted,
        )
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.store.query(
            f"SELECT * FROM memories{where} ORDER BY pinned DESC, created_at DESC, id LIMIT ? OFFSET ?",
            (*params, max(1, limit), max(0, offset)),
        )
        return [_row_to_memory(r) for r in rows]

    def _filters(self, **kw: Any) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        kinds = kw.get("kinds")
        if kinds:
            kinds = [k for k in kinds]
            for k in kinds:
                if k not in KINDS:
                    raise ValidationError(f"unknown memory kind {k!r}")
            clauses.append("kind IN (" + ",".join("?" * len(kinds)) + ")")
            params.extend(kinds)
        for key in ("scope", "scope_id", "project_id", "conversation_id", "task_id", "category", "status"):
            value = kw.get(key)
            if value is not None:
                clauses.append(f"{key} = ?")
                params.append(value)
        if kw.get("pinned") is not None:
            clauses.append("pinned = ?")
            params.append(int(bool(kw["pinned"])))
        if not kw.get("include_deleted"):
            clauses.append("deleted_at IS NULL")
            if kw.get("status") is None:
                clauses.append("status = 'active'")
        return clauses, params

    def search(
        self,
        query: str,
        *,
        kinds: Iterable[str] | None = None,
        scope: str | None = None,
        scope_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        category: str | None = None,
        tags: Sequence[str] | None = None,
        status: str | None = "active",
        include_deleted: bool = False,
        limit: int = 20,
        recency_boost: bool = True,
    ) -> SearchOutcome:
        """Keyword search with a documented degraded flag.

        This is the non-embedding path; it always works but is weaker than
        vector search. When the caller asks for semantic search this method
        reports ``degraded=True`` so the UI can say so instead of pretending.
        """
        query = (query or "").strip()
        q_tokens = tokens_of(query)
        clauses, params = self._filters(
            kinds=kinds,
            scope=scope,
            scope_id=scope_id,
            project_id=project_id,
            conversation_id=conversation_id,
            category=category,
            status=status,
            include_deleted=include_deleted,
        )
        if query:
            # Token-level matching: a full-phrase LIKE would miss "database locked"
            # against "Database is locked", so match the strongest tokens and rank
            # the exact phrase higher in _score().
            terms = sorted(tokens_of(query), key=len, reverse=True)[:8] or [query]
            token_clauses = []
            for term in terms:
                like = f"%{_strip_like(term)}%"
                token_clauses.append(
                    "(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\'"
                    " OR COALESCE(tags,'') LIKE ? ESCAPE '\\' OR COALESCE(summary,'') LIKE ? ESCAPE '\\')"
                )
                params.extend([like, like, like, like])
            clauses.append("(" + " OR ".join(token_clauses) + ")")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.store.query(
            f"SELECT * FROM memories{where} ORDER BY pinned DESC, created_at DESC LIMIT ?",
            (*params, max(limit * 10, 50)),
        )
        hits: list[SearchHit] = []
        now = datetime.now(timezone.utc)
        for row in rows:
            memory = _row_to_memory(row)
            score, reason = self._score(memory, q_tokens, query, tags, now if recency_boost else None)
            if query and score <= 0:
                continue
            hits.append(SearchHit(memory=memory, score=score, reason=reason))
        mode = "keyword"
        degraded = False
        degraded_reason: str | None = None
        if query and self.embedding_index is not None and getattr(self.embedding_index, "available", False):
            candidate_ids = [hit.memory.id for hit in hits] or [r["id"] for r in rows]
            try:
                scores = self.embedding_index.memory_scores(query, candidate_ids)
            except Exception as exc:  # noqa: BLE001 - retrieval must degrade, not fail
                scores = {}
                degraded = True
                degraded_reason = f"semantic scoring failed ({type(exc).__name__}); keyword results only"
            if scores:
                mode = "hybrid"
                # Relevance-only blend: recency/usage bonuses are deliberately not
                # applied here - they are not relevance signals and they diluted
                # ranking quality in the evaluation (see docs/RETRIEVAL_EVAL.md).
                query_terms = tokens_of(query)
                blended = []
                for hit in hits:
                    semantic = scores.get(hit.memory.id)
                    if semantic is None:
                        blended.append(hit)
                        continue
                    lexical = jaccard(
                        query_terms, tokens_of(f"{hit.memory.title} {hit.memory.content}")
                    )
                    title_bonus = 1.0 if query.lower() in hit.memory.title.lower() else 0.0
                    hit.score = 3.0 * max(0.0, semantic) + 2.0 * lexical + title_bonus
                    if hit.memory.pinned:
                        hit.score += 0.5
                    hit.reason = (
                        f"semantic={semantic:.3f}, lexical-overlap={lexical:.3f}"
                        + (", title-substring" if title_bonus else "")
                        + (", pinned" if hit.memory.pinned else "")
                    )
                    blended.append(hit)
                hits = blended
                missing = len(candidate_ids) - len(scores)
                if missing > 0:
                    degraded = True
                    degraded_reason = (
                        f"{missing} of {len(candidate_ids)} candidates have no embedding for the active model; "
                        "they are matched by keyword only"
                    )
            elif not degraded:
                mode = "keyword"
                degraded = query != "" and not any(
                    m.embedding_state == "embedded" for m in self.list(limit=1, status=None)
                )
                if degraded:
                    degraded_reason = (
                        "semantic (embedding) search is not available for this corpus; results are keyword-only"
                    )
        elif query:
            degraded = True
            degraded_reason = (
                "no embedding index is configured; semantic search is unavailable and results are keyword-only"
            )
        hits.sort(key=lambda h: (-h.score, h.memory.created_at), reverse=False)
        hits = hits[:limit]
        return SearchOutcome(
            hits=hits,
            mode=mode,
            degraded=degraded,
            degraded_reason=degraded_reason,
        )

    def find_similar(
        self,
        text: str,
        *,
        kinds: Iterable[str] | None = None,
        scope: str | None = None,
        scope_id: str | None = None,
        limit: int = 5,
    ) -> list[SearchHit]:
        q_tokens = tokens_of(text)
        if not q_tokens:
            return []
        clauses, params = self._filters(kinds=kinds, scope=scope, scope_id=scope_id, status="active")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.store.query(f"SELECT * FROM memories{where} ORDER BY created_at DESC LIMIT 500", params)
        scored = []
        for row in rows:
            memory = _row_to_memory(row)
            score = similarity(q_tokens, tokens_of(f"{memory.title} {memory.content}"))
            if score > 0.2:
                scored.append(SearchHit(memory=memory, score=score, reason=f"token-jaccard={score:.2f}"))
        scored.sort(key=lambda h: -h.score)
        return scored[:limit]

    def _score(
        self,
        memory: Memory,
        q_tokens: set[str],
        query: str,
        tags: Sequence[str] | None,
        now: datetime | None,
    ) -> tuple[float, str]:
        reasons: list[str] = []
        score = 0.0
        if q_tokens:
            jac = jaccard(q_tokens, tokens_of(f"{memory.title} {memory.content}"))
            score += jac * 6
            if jac:
                reasons.append(f"token-overlap={jac:.2f}")
            if query and query.lower() in memory.title.lower():
                score += 3
                reasons.append("title-substring")
            if query and query.lower() in memory.content.lower():
                score += 1.5
                reasons.append("content-substring")
        else:
            score += 1.0
            reasons.append("no-query")
        if tags:
            overlap = set(tags) & set(memory.tags)
            if overlap:
                score += 1.5 * len(overlap)
                reasons.append(f"tags={sorted(overlap)}")
        if memory.pinned:
            score += 2
            reasons.append("pinned")
        if memory.verification == "verified":
            score += 1.5
            reasons.append("verified")
        elif memory.verification in ("unverified", "reported"):
            score -= 0.5
            reasons.append(f"verification={memory.verification}")
        score += max(0.0, memory.confidence - 0.5) * 2
        if now is not None:
            try:
                age_days = max(0.0, (now - parse_iso(memory.created_at)).total_seconds() / 86400)
                score += 2.0 / (1 + age_days / 30)  # decays over months, not hours
                reasons.append(f"age_days={age_days:.1f}")
            except ValueError:  # pragma: no cover - defensive
                pass
        score += min(memory.access_count, 10) * 0.05
        return score, ", ".join(reasons) or "matched"

    # -- update / delete --------------------------------------------------
    def update(
        self,
        memory_id: str,
        *,
        change: str = "update",
        **fields: Any,
    ) -> Memory:
        memory = self.require(memory_id)
        if "title" in fields and (not fields["title"] or len(fields["title"]) > MAX_TITLE):
            raise ValidationError(f"memory title must be 1-{MAX_TITLE} characters")
        if "content" in fields:
            content = fields["content"]
            if not isinstance(content, str) or not content.strip() or len(content) > MAX_CONTENT:
                raise ValidationError(f"memory content must be 1-{MAX_CONTENT} characters")
            if redaction.looks_secret(content):
                raise ValidationError("refusing to store credential-shaped content in memory")
        if "verification" in fields and fields["verification"] not in VERIFICATION_STATES:
            raise ValidationError(f"unknown verification state {fields['verification']!r}")
        if memory.kind == "solution" and fields.get("verification") == "verified":
            evidence = fields.get("evidence", memory.evidence)
            details_evidence = (fields.get("details") or memory.details or {}).get("evidence")
            if not evidence and not details_evidence:
                raise ValidationError("cannot mark a solution verified without evidence")
        if "content" in fields or "title" in fields:
            fields["checksum"] = self._checksum(
                memory.kind,
                memory.scope,
                memory.scope_id,
                fields.get("title", memory.title),
                fields.get("content", memory.content),
            )
        self._write(
            "memory.update",
            {"id": memory_id, "fields": fields, "change": change, "now": iso_now()},
        )
        updated = self.require(memory_id)
        self.trace(
            "memory",
            "memory.updated",
            project_id=updated.project_id,
            payload={"memory_id": memory_id, "fields": sorted(fields), "version": updated.version},
        )
        return updated

    def set_status(self, memory_ids: Sequence[str], status: str) -> int:
        if not memory_ids:
            return 0
        result = self._write("memory.status", {"ids": list(memory_ids), "status": status, "now": iso_now()})
        self.trace("memory", "memory.status_changed", payload={"ids": list(memory_ids), "status": status})
        return int(result.get("updated", 0))

    def retire(self, memory_id: str, *, reason: str = "") -> Memory:
        memory = self.require(memory_id)
        if memory.kind not in ("solution", "learning", "archival", "project"):
            raise ValidationError(f"{memory.kind} memory cannot be retired (delete it instead)")
        return self.update(memory_id, change="retire", status="retired", details={**memory.details, "retire_reason": reason})

    def delete(self, memory_id: str, *, hard: bool = False) -> str:
        memory = self.require(memory_id)
        self._write(
            "memory.delete",
            {"id": memory_id, "hard": hard, "now": iso_now(), "checksum": memory.checksum},
        )
        self.trace(
            "memory",
            "memory.deleted",
            payload={"memory_id": memory_id, "kind": memory.kind, "hard": hard},
        )
        return "hard_deleted" if hard else "deleted"

    def restore(self, memory_id: str) -> Memory:
        self.get(memory_id, include_deleted=True).ok_or_raise()
        self._write("memory.update", {"id": memory_id, "fields": {"status": "active"}, "change": "restore", "now": iso_now()})
        with self.store.write_tx() as tx:
            tx.execute("UPDATE memories SET deleted_at = NULL WHERE id = ?", (memory_id,))
        return self.require(memory_id)

    # -- provenance / sources / history -----------------------------------
    def add_source(
        self,
        memory_id: str,
        *,
        source_type: str,
        reference: str | None = None,
        excerpt: str | None = None,
    ) -> None:
        if source_type not in SOURCE_TYPES:
            raise ValidationError(f"unknown source type {source_type!r}")
        self.require(memory_id)
        self._write(
            "memory.source",
            {
                "memory_id": memory_id,
                "source_type": source_type,
                "reference": reference,
                "excerpt": excerpt[:2000] if excerpt else None,
                "now": iso_now(),
                "checksum": sha256_text(f"{reference or ''}\x1f{excerpt or ''}"),
            },
        )

    def sources(self, memory_id: str) -> list[dict[str, Any]]:
        return self.store.query(
            "SELECT source_type, reference, excerpt, retrieved_at, checksum FROM memory_sources"
            " WHERE memory_id = ? ORDER BY sid",
            (memory_id,),
        )

    def history(self, memory_id: str) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT version, change, changed_at, snapshot FROM memory_history WHERE memory_id = ? ORDER BY hid",
            (memory_id,),
        )
        out = []
        for row in rows:
            snapshot = json.loads(row["snapshot"]) if row["snapshot"] else {}
            out.append(
                {
                    "version": row["version"],
                    "change": row["change"],
                    "changed_at": row["changed_at"],
                    "snapshot": snapshot,
                }
            )
        return out

    # -- artifacts (whole files live on disk, the path lives in SQLite) ---
    def attach_artifact(
        self,
        memory_id: str,
        data: bytes,
        *,
        filename: str,
        mime: str | None = None,
    ) -> str:
        if self.artifacts_root is None:
            raise PathError("artifact storage is not configured for this workspace")
        memory = self.require(memory_id)
        if not isinstance(data, (bytes, bytearray)):
            raise ValidationError("artifact data must be bytes")
        root = ensure_directory(self.artifacts_root)
        directory = ensure_directory(child_path(root, "memory", memory.id))
        target = child_path(directory, safe_filename(filename))
        if target.exists():
            target = child_path(directory, f"{sha256_bytes(bytes(data))[:12]}_{safe_filename(filename)}")
        target.write_bytes(bytes(data))
        checksum = sha256_bytes(bytes(data))
        self._write(
            "memory.artifact",
            {"memory_id": memory_id, "path": str(target), "checksum": checksum, "now": iso_now()},
        )
        self.trace(
            "memory",
            "memory.artifact_attached",
            payload={"memory_id": memory_id, "bytes": len(data), "mime": mime},
        )
        return str(target)

    def read_artifact(self, memory_id: str) -> bytes:
        memory = self.require(memory_id)
        if not memory.artifact_path:
            raise NotFoundError(f"memory {memory_id} has no artifact")
        from pathlib import Path

        path = Path(memory.artifact_path)
        if not path.exists():
            raise PathError(f"artifact file is missing: {path}", path=str(path))
        data = path.read_bytes()
        if memory.checksum and sha256_bytes(data) != memory.checksum:
            raise ValidationError("artifact checksum mismatch (file changed since it was recorded)")
        return data

    # -- retrieval --------------------------------------------------------
    def retrieve_for_context(
        self,
        *,
        budget_tokens: int,
        conversation_id: str | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
        learner_id: str | None = None,
        query: str | None = None,
        kinds: Sequence[str] | None = None,
        include_archival: bool = False,
        now: datetime | None = None,
        record: bool = True,
    ) -> RetrievalResult:
        """Select memory for the current context within a token budget.

        Priority order (documented, and reflected in the manifest):
        active > permanent > project > solution (verified) > learning.
        Archival memory is only included when explicitly requested.
        """
        if budget_tokens < 0:
            raise ValidationError("budget_tokens must be >= 0")
        base_kinds = list(kinds) if kinds else list(INJECTABLE)
        if include_archival and "archival" not in base_kinds:
            base_kinds.append("archival")
        kinds_allowed = [k for k in base_kinds if include_archival or k not in NEVER_INJECTED]
        current = now or datetime.now(timezone.utc)
        candidates: list[tuple[int, Memory, str]] = []
        priority = {"active": 0, "permanent": 1, "project": 2, "solution": 3, "learning": 4, "archival": 9}

        def gather(memories: Iterable[Memory], reason: str) -> None:
            for memory in memories:
                if memory.kind not in kinds_allowed:
                    continue
                if memory.status != "active" or memory.deleted_at is not None:
                    continue
                if memory.expires_at and _is_expired(memory.expires_at, current):
                    continue
                if memory.kind == "solution" and memory.verification not in ("verified", "reported"):
                    continue
                candidates.append((priority.get(memory.kind, 5), memory, reason))

        if conversation_id:
            gather(
                self.list(kinds=["active"], scope="conversation", scope_id=conversation_id, limit=50),
                "active memory for this conversation",
            )
        if task_id:
            gather(
                self.list(kinds=["active"], scope="task", scope_id=task_id, limit=50),
                "active memory for this task",
            )
        gather(self.list(kinds=["permanent"], limit=50), "permanent memory (global)")
        if project_id:
            gather(
                self.list(kinds=["project"], project_id=project_id, limit=50),
                "project memory",
            )
        if kinds is None or "solution" in kinds_allowed:
            solution_hits = self.search(
                query or "", kinds=["solution"], limit=10, recency_boost=False
            )
            gather([h.memory for h in solution_hits.hits], "verified solution matched the request")
        if learner_id:
            gather(
                self.list(kinds=["learning"], scope="learner", scope_id=learner_id, limit=20),
                "learning progress",
            )
        if include_archival:
            gather(self.list(kinds=["archival"], limit=10), "archival (explicitly requested)")

        # de-duplicate by id, keeping the highest priority reason
        seen: dict[str, tuple[int, Memory, str]] = {}
        for item in candidates:
            existing = seen.get(item[1].id)
            if existing is None or item[0] < existing[0]:
                seen[item[1].id] = item
        ordered = sorted(
            seen.values(),
            key=lambda item: (item[0], not item[1].pinned, item[1].created_at),
        )

        used = 0
        included: list[Memory] = []
        manifest_included: list[dict[str, Any]] = []
        omitted: list[dict[str, Any]] = []
        for prio, memory, reason in ordered:
            cost = self.tokenizer.count(f"{memory.title}\n{memory.content}")
            if used + cost > budget_tokens:
                omitted.append(
                    {
                        "memory_id": memory.id,
                        "kind": memory.kind,
                        "title": memory.title,
                        "tokens": cost,
                        "reason": "exceeded memory token budget",
                    }
                )
                continue
            used += cost
            included.append(memory)
            manifest_included.append(
                {
                    "memory_id": memory.id,
                    "kind": memory.kind,
                    "scope": memory.scope,
                    "title": memory.title,
                    "tokens": cost,
                    "priority": prio,
                    "reason": reason,
                    "verification": memory.verification,
                }
            )

        degraded = False
        notes = None
        if query:
            outcome = self.search(query, kinds=kinds_allowed, limit=5, recency_boost=False)
            degraded = outcome.degraded
            notes = outcome.degraded_reason

        if record and included:
            now_iso = iso_from_ts(current.timestamp())
            with self.store.write_tx() as tx:
                for memory in included:
                    tx.execute(
                        "INSERT INTO memory_retrievals(memory_id, used_at, reason, budget_tokens,"
                        " consumed_tokens, conversation_id, task_id) VALUES (?,?,?,?,?,?,?)",
                        (
                            memory.id,
                            now_iso,
                            next(
                                (m["reason"] for m in manifest_included if m["memory_id"] == memory.id),
                                "",
                            ),
                            budget_tokens,
                            used,
                            conversation_id,
                            task_id,
                        ),
                    )
                    tx.execute(
                        "UPDATE memories SET access_count = access_count + 1, last_accessed_at = ? WHERE id = ?",
                        (now_iso, memory.id),
                    )
            self.trace(
                "memory",
                "memory.retrieved",
                conversation_id=conversation_id,
                task_id=task_id,
                project_id=project_id,
                payload={
                    "included": [m["memory_id"] for m in manifest_included],
                    "omitted": [m["memory_id"] for m in omitted],
                    "tokens_used": used,
                    "budget": budget_tokens,
                    "degraded": degraded,
                },
            )
        return RetrievalResult(
            items=included,
            tokens_used=used,
            budget=budget_tokens,
            included=manifest_included,
            omitted=omitted,
            degraded=degraded,
            notes=notes,
        )

    def set_embedding_state(self, memory_id: str, state: str, *, model_id: str | None = None) -> None:
        if state not in ("embedded", "awaiting", "failed"):
            raise ValidationError(f"unknown embedding state {state!r}")
        memory = self.require(memory_id)
        fields: dict[str, Any] = {"embedding_state": state}
        if model_id:
            fields["embedding_ref"] = model_id
        self._write(
            "memory.update",
            {"id": memory_id, "fields": fields, "change": "embedding-state", "now": iso_now()},
        )

    # -- learning helpers -------------------------------------------------
    def record_learning_event(
        self,
        *,
        topic: str,
        outcome: str,
        goal_id: str | None = None,
        attempts: int = 1,
        mistakes: Sequence[str] | None = None,
        duration_seconds: int | None = None,
    ) -> str:
        if outcome not in ("passed", "failed", "skipped", "in_progress"):
            raise ValidationError(f"unknown learning outcome {outcome!r}")
        event_id = new_id("lrn_")
        now = iso_now()
        with self.store.write_tx() as tx:
            tx.execute(
                "INSERT INTO learning_events(id, goal_id, topic, outcome, attempts, mistakes,"
                " duration_seconds, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    goal_id,
                    topic,
                    outcome,
                    attempts,
                    json_text(list(mistakes or [])),
                    duration_seconds,
                    now,
                ),
            )
        self.trace(
            "learning",
            "learning.event",
            payload={"topic": topic, "outcome": outcome, "attempts": attempts},
        )
        return event_id

    def learner_profile(self, learner_id: str = "default") -> dict[str, Any]:
        """Summarise progress without permanently labelling the learner.

        A single failure never produces a "weak" label: the profile reports
        observations with counts, and ``needs_practice`` requires repeated
        failures *and* recent evidence.
        """
        rows = self.store.query(
            "SELECT topic, outcome, attempts, mistakes, created_at FROM learning_events ORDER BY created_at"
        )
        per_topic: dict[str, dict[str, Any]] = {}
        for row in rows:
            topic = row["topic"]
            entry = per_topic.setdefault(
                topic, {"passed": 0, "failed": 0, "skipped": 0, "in_progress": 0, "last": None, "mistakes": []}
            )
            entry[row["outcome"]] = entry.get(row["outcome"], 0) + 1
            entry["last"] = row["created_at"]
            mistakes = json.loads(row["mistakes"]) if row["mistakes"] else []
            for mistake in mistakes:
                if mistake not in entry["mistakes"]:
                    entry["mistakes"].append(mistake)
        strengths = [
            topic
            for topic, e in per_topic.items()
            if e["passed"] >= 2 and e["passed"] > e["failed"]
        ]
        needs_practice = [
            topic
            for topic, e in per_topic.items()
            if e["failed"] >= 2 and e["failed"] >= e["passed"]
        ]
        stable = [
            topic
            for topic, e in per_topic.items()
            if e["passed"] >= 3 and e["failed"] == 0
        ]
        unresolved = self.list(kinds=["learning"], scope="learner", scope_id=learner_id, limit=100)
        return {
            "learner_id": learner_id,
            "topics": per_topic,
            "strengths": sorted(strengths),
            "needs_practice": sorted(needs_practice),
            "stable": sorted(stable),
            "unresolved_concepts": [
                m.title for m in unresolved if m.category == "unresolved_concept"
            ],
            "notes": (
                "Labels are observations with counts, not permanent assessments. "
                "A single failed attempt never creates a weakness label."
            ),
        }

    # -- retention --------------------------------------------------------
    def apply_retention(self, *, now: datetime | None = None, archival_retention_days: int = 365) -> dict[str, int]:
        current = now or datetime.now(timezone.utc)
        now_iso = iso_from_ts(current.timestamp())
        expired_active = 0
        expired_archival = 0
        with self.store.write_tx() as tx:
            rows = tx.query(
                "SELECT id, expires_at FROM memories WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ?",
                (now_iso,),
            )
            for row in rows:
                tx.execute("UPDATE memories SET status='expired', updated_at=? WHERE id=?", (now_iso, row["id"]))
                expired_active += 1
            cutoff = iso_from_ts((current - timedelta(days=archival_retention_days)).timestamp())
            rows = tx.query(
                "SELECT id FROM memories WHERE kind='archival' AND status='active' AND created_at < ?", (cutoff,)
            )
            for row in rows:
                tx.execute("UPDATE memories SET status='expired', updated_at=? WHERE id=?", (now_iso, row["id"]))
                expired_archival += 1
        if expired_active or expired_archival:
            self.trace(
                "memory",
                "memory.retention_applied",
                level="summary",
                payload={"expired_active": expired_active, "expired_archival": expired_archival},
            )
        return {"expired_active": expired_active, "expired_archival": expired_archival}

    def purge_deleted(self, *, older_than_days: int = 30, now: datetime | None = None) -> int:
        current = now or datetime.now(timezone.utc)
        cutoff = iso_from_ts((current - timedelta(days=older_than_days)).timestamp())
        rows = self.store.query("SELECT id FROM memories WHERE status='deleted' AND deleted_at < ?", (cutoff,))
        for row in rows:
            self._write(
                "memory.delete",
                {"id": row["id"], "hard": True, "now": iso_from_ts(current.timestamp()), "checksum": None},
            )
        return len(rows)

    # -- policy / stats ---------------------------------------------------
    @staticmethod
    def policy() -> dict[str, Any]:
        return {
            "active": {
                "purpose": "current task state: goal, constraints, pending steps, tool state",
                "scope": ["conversation", "task"],
                "injected": True,
                "lifetime": "TTL (default 240 minutes) or until the task ends",
                "requires": ["conversation_id or task_id"],
            },
            "permanent": {
                "purpose": "user-approved durable preferences and facts",
                "scope": ["global"],
                "injected": True,
                "lifetime": "until the user edits or deletes it",
                "requires": ["category in preference/fact/instruction/constraint", "no credentials"],
            },
            "archival": {
                "purpose": "historical reference, never assumed current",
                "scope": ["global", "project", "conversation"],
                "injected": False,
                "lifetime": "retention policy (default 365 days) then expired",
                "requires": ["provenance"],
            },
            "project": {
                "purpose": "project goals, decisions, requirements, known issues, commands",
                "scope": ["project"],
                "injected": True,
                "lifetime": "lives with the project",
                "requires": ["project_id"],
            },
            "solution": {
                "purpose": "reusable technical solutions with evidence",
                "scope": ["global", "project"],
                "injected": True,
                "lifetime": "retired when disproven",
                "requires": ["details.problem", "details.solution", "verification"],
            },
            "learning": {
                "purpose": "learner progress, mistakes, strengths, unresolved concepts",
                "scope": ["learner"],
                "injected": True,
                "lifetime": "decays; never a permanent label",
                "requires": ["details.topic"],
            },
        }

    def stats(self) -> dict[str, Any]:
        counts = {}
        for kind in KINDS:
            counts[kind] = int(
                self.store.scalar(
                    "SELECT COUNT(*) FROM memories WHERE kind=? AND status='active' AND deleted_at IS NULL", (kind,)
                )
                or 0
            )
        return {
            "by_kind": counts,
            "total_active": int(
                self.store.scalar("SELECT COUNT(*) FROM memories WHERE status='active' AND deleted_at IS NULL") or 0
            ),
            "deleted": int(self.store.scalar("SELECT COUNT(*) FROM memories WHERE status='deleted'") or 0),
            "sources": self.table_count("memory_sources"),
            "retrievals": self.table_count("memory_retrievals"),
            "history_entries": self.table_count("memory_history"),
            "embedding_states": {
                str(row["embedding_state"]): row["n"]
                for row in self.store.query(
                    "SELECT embedding_state, COUNT(*) AS n FROM memories WHERE deleted_at IS NULL GROUP BY embedding_state"
                )
            },
        }


def _strip_like(value: str) -> str:
    return value.replace("\\", "").replace("%", "").replace("_", "")


def _is_expired(expires_at: str, now: datetime) -> bool:
    try:
        return parse_iso(expires_at) < now
    except ValueError:  # pragma: no cover - defensive
        return False


__all__ = [
    "MemoryManager",
    "Memory",
    "SearchHit",
    "SearchOutcome",
    "RetrievalResult",
    "KINDS",
    "SCOPES",
    "CATEGORIES",
    "VERIFICATION_STATES",
    "INJECTABLE",
    "NEVER_INJECTED",
]
