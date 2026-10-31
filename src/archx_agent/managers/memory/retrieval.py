"""Retrieval operations for memory governance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.timeutil import iso_from_ts, iso_now
from archx_agent.managers.memory.constants import NEVER_INJECTED, INJECTABLE
from archx_agent.managers.memory.records import Memory, RetrievalResult
from archx_agent.managers.memory.ranking import _is_expired


class MemoryManagerRetrievalMixin:
    """Retrieval responsibility for MemoryManager."""

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
        kinds_allowed = [
            k for k in base_kinds if include_archival or k not in NEVER_INJECTED
        ]
        current = now or datetime.now(timezone.utc)
        candidates: list[tuple[int, Memory, str]] = []
        priority = {
            "active": 0,
            "permanent": 1,
            "project": 2,
            "solution": 3,
            "learning": 4,
            "archival": 9,
        }

        def gather(memories: Iterable[Memory], reason: str) -> None:
            for memory in memories:
                if memory.kind not in kinds_allowed:
                    continue
                if memory.status != "active" or memory.deleted_at is not None:
                    continue
                if memory.expires_at and _is_expired(memory.expires_at, current):
                    continue
                if memory.kind == "solution" and memory.verification not in (
                    "verified",
                    "reported",
                ):
                    continue
                candidates.append((priority.get(memory.kind, 5), memory, reason))

        if conversation_id:
            gather(
                self.list(
                    kinds=["active"],
                    scope="conversation",
                    scope_id=conversation_id,
                    limit=50,
                ),
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
            gather(
                [h.memory for h in solution_hits.hits],
                "verified solution matched the request",
            )
        if learner_id:
            gather(
                self.list(
                    kinds=["learning"], scope="learner", scope_id=learner_id, limit=20
                ),
                "learning progress",
            )
        if include_archival:
            gather(
                self.list(kinds=["archival"], limit=10),
                "archival (explicitly requested)",
            )

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
            outcome = self.search(
                query, kinds=kinds_allowed, limit=5, recency_boost=False
            )
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
                                (
                                    m["reason"]
                                    for m in manifest_included
                                    if m["memory_id"] == memory.id
                                ),
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

    def set_embedding_state(
        self, memory_id: str, state: str, *, model_id: str | None = None
    ) -> None:
        if state not in ("embedded", "awaiting", "failed"):
            raise ValidationError(f"unknown embedding state {state!r}")
        self.require(memory_id)
        fields: dict[str, Any] = {"embedding_state": state}
        if model_id:
            fields["embedding_ref"] = model_id
        self._write(
            "memory.update",
            {
                "id": memory_id,
                "fields": fields,
                "change": "embedding-state",
                "now": iso_now(),
            },
        )
