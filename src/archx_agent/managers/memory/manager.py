"""Composition and shared configuration for memory governance."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.tokens import Tokenizer, default_tokenizer
from archx_agent.managers.base import BaseManager
from archx_agent.managers.memory.constants import MEMORY_TABLES, KINDS
from archx_agent.managers.memory.writes import MemoryManagerWritesMixin
from archx_agent.managers.memory.creation import MemoryManagerCreationMixin
from archx_agent.managers.memory.queries import MemoryManagerQueriesMixin
from archx_agent.managers.memory.lifecycle import MemoryManagerLifecycleMixin
from archx_agent.managers.memory.retrieval import MemoryManagerRetrievalMixin
from archx_agent.managers.memory.learning import MemoryManagerLearningMixin


class MemoryManager(
    MemoryManagerWritesMixin,
    MemoryManagerCreationMixin,
    MemoryManagerQueriesMixin,
    MemoryManagerLifecycleMixin,
    MemoryManagerRetrievalMixin,
    MemoryManagerLearningMixin,
    BaseManager,
):
    """Compose memory governance around shared collaborators."""

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
                "requires": [
                    "category in preference/fact/instruction/constraint",
                    "no credentials",
                ],
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
                    "SELECT COUNT(*) FROM memories WHERE kind=? AND status='active' AND deleted_at IS NULL",
                    (kind,),
                )
                or 0
            )
        return {
            "by_kind": counts,
            "total_active": int(
                self.store.scalar(
                    "SELECT COUNT(*) FROM memories WHERE status='active' AND deleted_at IS NULL"
                )
                or 0
            ),
            "deleted": int(
                self.store.scalar(
                    "SELECT COUNT(*) FROM memories WHERE status='deleted'"
                )
                or 0
            ),
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
