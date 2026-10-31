"""Creation operations for memory governance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from archx_agent.helpers import redaction
from archx_agent.helpers.exceptions import DuplicateError, ValidationError
from archx_agent.helpers.jsonio import sha256_text
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_from_ts, new_id
from archx_agent.managers.memory.constants import (
    KINDS,
    SCOPES,
    CATEGORIES,
    VERIFICATION_STATES,
    MAX_TITLE,
    MAX_CONTENT,
)
from archx_agent.managers.memory.records import Memory
from archx_agent.managers.memory.ranking import _normalize


class MemoryManagerCreationMixin:
    """Creation responsibility for MemoryManager."""

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
        self._validate(
            kind,
            title,
            content,
            category,
            verification,
            details,
            allow_sensitive=allow_sensitive,
        )
        scope, scope_id = self._resolve_scope(
            kind, scope, scope_id, project_id, conversation_id, task_id
        )
        current = now or datetime.now(timezone.utc)
        created = iso_from_ts(current.timestamp())
        if kind == "active" and expires_at is None and status == "active":
            expires_at = iso_from_ts(
                (current + timedelta(minutes=self.active_ttl_minutes)).timestamp()
            )
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
                f"{title} {content}",
                kinds=(kind,),
                scope=scope,
                scope_id=scope_id,
                limit=3,
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
            raise ValidationError(
                f"unknown memory kind {kind!r} (expected one of {list(KINDS)})"
            )
        if not (title or "").strip():
            raise ValidationError("memory title must not be empty")
        if len(title) > MAX_TITLE:
            raise ValidationError(
                f"memory title must be {MAX_TITLE} characters or fewer"
            )
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("memory content must not be empty")
        if len(content) > MAX_CONTENT:
            raise ValidationError(
                f"memory content must be {MAX_CONTENT} characters or fewer"
            )
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
            raise ValidationError(
                f"unknown memory scope {scope!r} (expected one of {list(SCOPES)})"
            )
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
                raise ValidationError(
                    "conversation-scoped memory requires conversation_id"
                )
        elif scope == "task":
            scope_id = scope_id or task_id
            if not scope_id:
                raise ValidationError("task-scoped memory requires task_id")
        elif scope == "learner" and not scope_id:
            scope_id = "default"
        if kind == "active" and scope not in ("conversation", "task"):
            raise ValidationError(
                "active memory must be scoped to a conversation or a task"
            )
        if kind == "project" and scope != "project":
            raise ValidationError("project memory must use project scope")
        return scope, scope_id

    def _checksum(
        self, kind: str, scope: str, scope_id: str | None, title: str, content: str
    ) -> str:
        return sha256_text(
            f"{kind}\x1f{scope}\x1f{scope_id or ''}\x1f{_normalize(title)}\x1f{_normalize(content)}"
        )
