"""Read and search operations for memory governance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import parse_iso
from archx_agent.managers.memory.constants import KINDS
from archx_agent.managers.memory.records import (
    Memory,
    SearchHit,
    SearchOutcome,
    _row_to_memory,
)
from archx_agent.managers.memory.ranking import (
    tokens_of,
    jaccard,
    similarity,
    _strip_like,
)


class MemoryManagerQueriesMixin:
    """Queries responsibility for MemoryManager."""

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
        for key in (
            "scope",
            "scope_id",
            "project_id",
            "conversation_id",
            "task_id",
            "category",
            "status",
        ):
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
            score, reason = self._score(
                memory, q_tokens, query, tags, now if recency_boost else None
            )
            if query and score <= 0:
                continue
            hits.append(SearchHit(memory=memory, score=score, reason=reason))
        mode = "keyword"
        degraded = False
        degraded_reason: str | None = None
        if (
            query
            and self.embedding_index is not None
            and getattr(self.embedding_index, "available", False)
        ):
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
                        query_terms,
                        tokens_of(f"{hit.memory.title} {hit.memory.content}"),
                    )
                    title_bonus = (
                        1.0 if query.lower() in hit.memory.title.lower() else 0.0
                    )
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
                    m.embedding_state == "embedded"
                    for m in self.list(limit=1, status=None)
                )
                if degraded:
                    degraded_reason = "semantic (embedding) search is not available for this corpus; results are keyword-only"
        elif query:
            degraded = True
            degraded_reason = "no embedding index is configured; semantic search is unavailable and results are keyword-only"
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
        clauses, params = self._filters(
            kinds=kinds, scope=scope, scope_id=scope_id, status="active"
        )
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.store.query(
            f"SELECT * FROM memories{where} ORDER BY created_at DESC LIMIT 500", params
        )
        scored = []
        for row in rows:
            memory = _row_to_memory(row)
            score = similarity(q_tokens, tokens_of(f"{memory.title} {memory.content}"))
            if score > 0.2:
                scored.append(
                    SearchHit(
                        memory=memory, score=score, reason=f"token-jaccard={score:.2f}"
                    )
                )
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
                age_days = max(
                    0.0, (now - parse_iso(memory.created_at)).total_seconds() / 86400
                )
                score += 2.0 / (1 + age_days / 30)  # decays over months, not hours
                reasons.append(f"age_days={age_days:.1f}")
            except ValueError:  # pragma: no cover - defensive
                pass
        score += min(memory.access_count, 10) * 0.05
        return score, ", ".join(reasons) or "matched"
