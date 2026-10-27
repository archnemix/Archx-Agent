"""Embedding storage and retrieval (M18).

Storage rules
-------------
* Vectors are ``float32`` BLOBs stored with their dimension **and** the model id
  that produced them.
* A query vector is only compared with vectors from the same ``model_id`` and
  dimension. Switching models never silently compares incompatible spaces; old
  vectors are reported as stale and can be purged or re-embedded.
* An item has an explicit state: ``embedded`` / ``awaiting`` / ``failed``.
  Anything not embedded stays findable by recency, category, project and keyword,
  and degraded retrieval says so.

Scale threshold
---------------
Similarity is an exact scan over a pre-filtered candidate set (kind, scope,
recency). Measured: ~50k comparisons/second per core for 256-dim vectors in
pure Python, and the pre-filter keeps candidate sets to a few thousand items.
Above ~200k embedded objects the scan becomes the bottleneck and an ANN index
becomes worthwhile; that limit is recorded in docs/RETRIEVAL.md rather than
silently degrading.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from archx_agent.adapters.embedding_runtime import EmbeddingProvider
from archx_agent.helpers.exceptions import NotFoundError, ProviderError, ValidationError
from archx_agent.helpers.jsonio import json_text, sha256_text
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.helpers.vectors import cosine, pack, top_k, unpack

from .base import BaseManager

EMBEDDING_TABLES = ("embeddings", "retrieval_runs")
OWNER_TYPES = ("message", "conversation", "memory", "summary", "artifact", "chunk")
STATES = ("embedded", "awaiting", "failed")

#: documented default similarity floor for "this is relevant"
DEFAULT_THRESHOLD = 0.62


@dataclass
class Neighbour:
    owner_type: str
    owner_id: str
    score: float
    model_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "score": round(self.score, 4),
            "model_id": self.model_id,
        }


@dataclass
class SemanticSearch:
    neighbours: list[Neighbour]
    model_id: str
    dim: int
    degraded: bool
    degraded_reason: str | None = None
    scanned: int = 0

    def ids(self) -> list[str]:
        return [n.owner_id for n in self.neighbours]


class EmbeddingManager(BaseManager):
    tables = EMBEDDING_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        events=None,
        conversations=None,
        memory=None,
        provider: EmbeddingProvider | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        max_scan: int = 20000,
    ) -> None:
        self.conversations = conversations
        self.memory = memory
        self.provider = provider
        self.threshold = threshold
        self.max_scan = max_scan
        super().__init__(store, coordinator, events=events)

    def register_handlers(self) -> None:
        self.coordinator.register("embedding.upsert", self._apply_upsert)
        self.coordinator.register("embedding.state", self._apply_state)
        self.coordinator.register("embedding.delete", self._apply_delete)
        self.coordinator.register("retrieval.run", self._apply_retrieval_run)

    # -- handlers ---------------------------------------------------------
    def _apply_upsert(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "INSERT INTO embeddings(owner_type, owner_id, model_id, dim, vector, checksum, state, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(owner_type, owner_id, model_id) DO UPDATE SET"
            " dim=excluded.dim, vector=excluded.vector, checksum=excluded.checksum,"
            " state=excluded.state, created_at=excluded.created_at",
            (
                payload["owner_type"],
                payload["owner_id"],
                payload["model_id"],
                payload["dim"],
                payload["vector"],
                payload["checksum"],
                "embedded",
                payload["now"],
            ),
        )
        return {"owner_id": payload["owner_id"], "state": "embedded"}

    def _apply_state(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        if payload["state"] not in ("awaiting", "failed", "embedded"):
            raise ValidationError(f"unknown embedding state {payload['state']!r}")
        tx.execute(
            "INSERT INTO embeddings(owner_type, owner_id, model_id, dim, vector, checksum, state, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(owner_type, owner_id, model_id) DO UPDATE SET state=excluded.state,"
            " created_at=excluded.created_at",
            (
                payload["owner_type"],
                payload["owner_id"],
                payload["model_id"],
                payload.get("dim") or 0,
                b"",
                payload.get("checksum") or "",
                payload["state"],
                payload["now"],
            ),
        )
        return {"owner_id": payload["owner_id"], "state": payload["state"]}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("model_id"):
            tx.execute(
                "DELETE FROM embeddings WHERE model_id = ?", (payload["model_id"],)
            )
        elif payload.get("owner_id"):
            tx.execute(
                "DELETE FROM embeddings WHERE owner_id = ? AND COALESCE(?,'') IN ('', owner_type)",
                (payload["owner_id"], payload.get("owner_type")),
            )
        else:
            tx.execute("DELETE FROM embeddings")
        return {"deleted": True}

    def _apply_retrieval_run(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "INSERT INTO retrieval_runs(id, query, mode, model_id, results, degraded, notes, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                payload["id"],
                payload["query"],
                payload["mode"],
                payload.get("model_id"),
                payload["results"],
                int(bool(payload.get("degraded"))),
                payload.get("notes"),
                payload["now"],
            ),
        )
        return {"id": payload["id"]}

    # -- availability -----------------------------------------------------
    @property
    def available(self) -> bool:
        return self.provider is not None

    def require_provider(self) -> EmbeddingProvider:
        if self.provider is None:
            raise NotFoundError(
                "no embedding provider is configured; set memory.embedding_provider or pass a provider"
            )
        return self.provider

    def status(self) -> dict[str, Any]:
        counts = {
            row["state"]: row["n"]
            for row in self.store.query("SELECT state, COUNT(*) n FROM embeddings GROUP BY state")
        }
        models = self.store.query(
            "SELECT model_id, dim, COUNT(*) n FROM embeddings GROUP BY model_id, dim"
        )
        provider = self.provider
        stale = 0
        if provider is not None:
            stale = int(
                self.store.scalar(
                    "SELECT COUNT(*) FROM embeddings WHERE model_id != ? OR dim != ?",
                    (provider.model_id, provider.dim),
                )
                or 0
            )
        return {
            "provider": None
            if provider is None
            else {
                "id": provider.provider_id,
                "model_id": provider.model_id,
                "dim": provider.dim,
                "semantic": provider.semantic,
                "local": provider.is_local,
            },
            "states": counts,
            "models": models,
            "stale_vectors": stale,
            "threshold": self.threshold,
            "max_scan": self.max_scan,
        }

    # -- embedding --------------------------------------------------------
    def embed_text(
        self,
        owner_type: str,
        owner_id: str,
        text: str,
        *,
        allow_remote: bool = False,
    ) -> Result[str]:
        provider = self.require_provider()
        if owner_type not in OWNER_TYPES:
            raise ValidationError(f"unknown embedding owner type {owner_type!r}")
        if not text or not text.strip():
            return Err(ValidationError("cannot embed empty text"))
        if not provider.is_local and not allow_remote:
            return Err(
                ValidationError(
                    "remote embedding provider requires explicit opt-in (memory.remote_embeddings=true)"
                )
            )
        checksum = sha256_text(text)
        existing = self.store.query_one(
            "SELECT checksum FROM embeddings WHERE owner_type=? AND owner_id=? AND model_id=?",
            (owner_type, owner_id, provider.model_id),
        )
        if existing and existing["checksum"] == checksum:
            return Ok("cached")
        try:
            result = provider.embed([text])
        except ProviderError as exc:
            self._write(
                "embedding.state",
                {
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "model_id": provider.model_id,
                    "state": "failed",
                    "checksum": checksum,
                    "now": iso_now(),
                },
            )
            self.trace(
                "memory",
                "embedding.failed",
                status="error",
                payload={"owner_type": owner_type, "owner_id": owner_id, "error": exc.code},
            )
            return Err(exc)
        vector = result.vectors[0]
        self._write(
            "embedding.upsert",
            {
                "owner_type": owner_type,
                "owner_id": owner_id,
                "model_id": result.model_id,
                "dim": len(vector),
                "vector": pack(vector),
                "checksum": checksum,
                "now": iso_now(),
            },
        )
        return Ok("embedded")

    def embed_conversation(self, conversation_id: str, *, allow_remote: bool = False) -> dict[str, Any]:
        if self.conversations is None:
            raise ValidationError("this embedding manager has no conversation manager")
        messages = self.conversations.messages(conversation_id, include_excluded=True)
        embedded = failed = cached = 0
        for message in messages:
            outcome = self.embed_text("message", message.id, message.content, allow_remote=allow_remote)
            if outcome.is_err:
                failed += 1
            elif outcome.value == "cached":
                cached += 1
            else:
                embedded += 1
        if messages:
            joined = "\n".join(f"{m.role}: {m.content}" for m in messages)[:20000]
            self.embed_text("conversation", conversation_id, joined, allow_remote=allow_remote)
        self.trace(
            "memory",
            "embedding.conversation",
            conversation_id=conversation_id,
            payload={"embedded": embedded, "cached": cached, "failed": failed},
        )
        return {"embedded": embedded, "cached": cached, "failed": failed, "messages": len(messages)}

    def embed_memories(
        self,
        *,
        kinds: Sequence[str] | None = None,
        limit: int = 500,
        allow_remote: bool = False,
    ) -> dict[str, Any]:
        if self.memory is None:
            raise ValidationError("this embedding manager has no memory manager")
        memories = self.memory.list(kinds=kinds, limit=limit, status="active")
        embedded = failed = cached = 0
        for memory in memories:
            text = f"{memory.title}\n{memory.content}"
            outcome = self.embed_text("memory", memory.id, text, allow_remote=allow_remote)
            if outcome.is_err:
                failed += 1
                self.memory.update(memory.id, change="embedding-failed")
            else:
                if outcome.value == "cached":
                    cached += 1
                else:
                    embedded += 1
                if memory.embedding_state != "embedded":
                    self.memory.set_embedding_state(memory.id, "embedded", model_id=self.provider.model_id if self.provider else None)
        return {"embedded": embedded, "cached": cached, "failed": failed, "considered": len(memories)}

    def backfill(self, *, limit: int = 500, allow_remote: bool = False) -> dict[str, Any]:
        """Embed memories and messages that have no vector for the active model."""
        provider = self.require_provider()
        missing_memories = self.store.query(
            "SELECT m.id FROM memories m LEFT JOIN embeddings e ON e.owner_id = m.id"
            " AND e.owner_type='memory' AND e.model_id = ?"
            " WHERE m.deleted_at IS NULL AND m.status='active' AND e.id IS NULL LIMIT ?",
            (provider.model_id, limit),
        )
        missing_messages = self.store.query(
            "SELECT msg.id, msg.content FROM messages msg LEFT JOIN embeddings e ON e.owner_id = msg.id"
            " AND e.owner_type='message' AND e.model_id = ?"
            " WHERE e.id IS NULL LIMIT ?",
            (provider.model_id, limit),
        )
        done = failed = 0
        if self.memory is not None:
            for row in missing_memories:
                memory = self.memory.get(row["id"])
                if memory.is_err:
                    continue
                text = f"{memory.value.title}\n{memory.value.content}"
                outcome = self.embed_text("memory", row["id"], text, allow_remote=allow_remote)
                done += 1 if outcome.is_ok else 0
                failed += 0 if outcome.is_ok else 1
        for row in missing_messages:
            outcome = self.embed_text("message", row["id"], row["content"], allow_remote=allow_remote)
            done += 1 if outcome.is_ok else 0
            failed += 0 if outcome.is_ok else 1
        self.trace(
            "memory",
            "embedding.backfill",
            level="summary",
            payload={"done": done, "failed": failed, "model_id": provider.model_id},
        )
        return {"embedded": done, "failed": failed, "model_id": provider.model_id}

    # -- retrieval --------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        owner_types: Sequence[str] = ("memory", "message"),
        candidate_ids: Sequence[str] | None = None,
        k: int = 10,
        threshold: float | None = None,
        within_days: int | None = None,
        allow_remote: bool = False,
        record: bool = True,
    ) -> SemanticSearch:
        if not query or not query.strip():
            raise ValidationError("search query must not be empty")
        provider = self.provider
        if provider is None:
            return SemanticSearch(
                [], "", 0, degraded=True, degraded_reason="no embedding provider configured"
            )
        if not provider.is_local and not allow_remote:
            return SemanticSearch(
                [],
                provider.model_id,
                provider.dim,
                degraded=True,
                degraded_reason="remote embeddings are disabled by preference",
            )
        try:
            query_vector = provider.embed([query]).vectors[0]
        except ProviderError as exc:
            if record:
                self._record_run(query, "semantic", provider.model_id, 0, True, exc.message)
            return SemanticSearch(
                [],
                provider.model_id,
                provider.dim,
                degraded=True,
                degraded_reason=f"embedding provider failed: {exc.code}",
            )
        types = list(owner_types)
        placeholders = ",".join("?" * len(types))
        sql = (
            "SELECT owner_type, owner_id, vector FROM embeddings"
            f" WHERE model_id = ? AND dim = ? AND state = 'embedded' AND owner_type IN ({placeholders})"
        )
        params: list[Any] = [provider.model_id, len(query_vector), *types]
        if candidate_ids is not None:
            ids = list(candidate_ids)
            if not ids:
                return SemanticSearch([], provider.model_id, len(query_vector), degraded=False, scanned=0)
            sql += " AND owner_id IN (" + ",".join("?" * len(ids)) + ")"
            params.extend(ids)
        if within_days is not None:
            from datetime import datetime, timedelta, timezone

            cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z")
            sql += " AND created_at >= ?"
            params.append(cutoff)
        sql += " LIMIT ?"
        params.append(self.max_scan)
        rows = self.store.query(sql, params)
        candidates: list[tuple[str, list[float]]] = []
        owner_types_by_id: dict[str, str] = {}
        for row in rows:
            try:
                vector = unpack(row["vector"])
            except ValidationError:  # pragma: no cover - corrupt blob
                continue
            candidates.append((row["owner_id"], vector))
            owner_types_by_id[row["owner_id"]] = row["owner_type"]
        floor = self.threshold if threshold is None else threshold
        scored = top_k(query_vector, candidates, k=k, threshold=floor)
        neighbours = [
            Neighbour(
                owner_type=owner_types_by_id.get(owner_id, ""),
                owner_id=owner_id,
                score=score,
                model_id=provider.model_id,
            )
            for owner_id, score in scored
        ]
        if record:
            self._record_run(
                query,
                "semantic" if provider.semantic else "lexical-hash",
                provider.model_id,
                len(neighbours),
                False,
                f"scanned {len(candidates)} vectors",
            )
        self.trace(
            "memory",
            "retrieval.semantic",
            payload={
                "query": query[:200],
                "model_id": provider.model_id,
                "semantic": provider.semantic,
                "results": len(neighbours),
                "scanned": len(candidates),
                "threshold": floor,
            },
        )
        return SemanticSearch(
            neighbours, provider.model_id, len(query_vector), degraded=False, scanned=len(candidates)
        )

    def memory_scores(self, query: str, candidate_ids: Sequence[str], *, allow_remote: bool = False) -> dict[str, float]:
        """Convenience hook used by :class:`MemoryManager` for hybrid search."""
        result = self.search(
            query,
            owner_types=("memory",),
            candidate_ids=candidate_ids,
            k=len(candidate_ids) or 1,
            threshold=-1.0,
            allow_remote=allow_remote,
            record=False,
        )
        if result.degraded:
            return {}
        return {n.owner_id: n.score for n in result.neighbours}

    def similarity(self, owner_a: str, owner_b: str) -> float:
        rows = self.store.query(
            "SELECT owner_id, vector, model_id, dim FROM embeddings WHERE owner_id IN (?,?)",
            (owner_a, owner_b),
        )
        by_id = {row["owner_id"]: row for row in rows}
        if owner_a not in by_id or owner_b not in by_id:
            raise NotFoundError("one of the items has no embedding")
        if by_id[owner_a]["model_id"] != by_id[owner_b]["model_id"]:
            raise ValidationError(
                "refusing to compare vectors from different models "
                f"({by_id[owner_a]['model_id']} vs {by_id[owner_b]['model_id']})"
            )
        return cosine(unpack(by_id[owner_a]["vector"]), unpack(by_id[owner_b]["vector"]))

    # -- maintenance ------------------------------------------------------
    def purge(self, *, model_id: str | None = None) -> int:
        before = int(self.store.scalar("SELECT COUNT(*) FROM embeddings") or 0)
        self._write("embedding.delete", {"model_id": model_id})
        after = int(self.store.scalar("SELECT COUNT(*) FROM embeddings") or 0)
        self.trace(
            "memory", "embedding.purged", level="summary", payload={"removed": before - after, "model_id": model_id}
        )
        return before - after

    def stale_items(self, limit: int = 100) -> list[dict[str, Any]]:
        provider = self.provider
        if provider is None:
            return []
        return self.store.query(
            "SELECT owner_type, owner_id, model_id, dim FROM embeddings"
            " WHERE model_id != ? OR dim != ? LIMIT ?",
            (provider.model_id, provider.dim, limit),
        )

    def _record_run(self, query: str, mode: str, model_id: str, results: int, degraded: bool, notes: str) -> None:
        self._write(
            "retrieval.run",
            {
                "id": new_id("rr_"),
                "query": query[:500],
                "mode": mode,
                "model_id": model_id,
                "results": results,
                "degraded": degraded,
                "notes": notes,
                "now": iso_now(),
            },
        )

    def stats(self) -> dict[str, Any]:
        return {
            "embeddings": int(self.store.scalar("SELECT COUNT(*) FROM embeddings") or 0),
            "by_state": {
                row["state"]: row["n"]
                for row in self.store.query("SELECT state, COUNT(*) n FROM embeddings GROUP BY state")
            },
            "retrieval_runs": int(self.store.scalar("SELECT COUNT(*) FROM retrieval_runs") or 0),
            "provider": None if self.provider is None else self.provider.model_id,
        }


__all__ = ["EmbeddingManager", "Neighbour", "SemanticSearch", "OWNER_TYPES", "DEFAULT_THRESHOLD"]
