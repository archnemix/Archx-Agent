"""Retrieval evaluation (M18).

A defined test set of queries with graded relevance, run through the same
managers the application uses, producing standard metrics so quality claims can
be checked rather than asserted:

* precision@k, recall@k
* MRR (mean reciprocal rank of the first relevant hit)
* nDCG@k with exponential gain

Modes compared: ``keyword`` (no embeddings), ``semantic`` (vectors only) and
``hybrid`` (keyword + semantic blend, what the application uses when embeddings
are available).

The evaluation never mutates user data: it writes into its own scratch
workspace, which the caller owns.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.jsonio import read_json


@dataclass
class RetrievalCase:
    query: str
    relevant: dict[str, int]  # item id -> relevance grade (1..3)
    note: str | None = None


@dataclass
class RetrievalDataset:
    name: str
    corpus: list[dict[str, Any]]
    cases: list[RetrievalCase]
    description: str = ""

    @property
    def size(self) -> dict[str, int]:
        return {"corpus": len(self.corpus), "queries": len(self.cases)}

    def validate(self) -> None:
        if not self.corpus:
            raise ValidationError("retrieval dataset has an empty corpus")
        if not self.cases:
            raise ValidationError("retrieval dataset has no queries")
        ids = {item["id"] for item in self.corpus}
        if len(ids) != len(self.corpus):
            raise ValidationError("retrieval dataset corpus ids must be unique")
        for item in self.corpus:
            if not item.get("text"):
                raise ValidationError(f"corpus item {item.get('id')!r} has no text")
        for case in self.cases:
            unknown = set(case.relevant) - ids
            if unknown:
                raise ValidationError(f"query {case.query!r} references unknown ids: {sorted(unknown)}")
            if not case.relevant:
                raise ValidationError(f"query {case.query!r} has no relevant ids")


def load_dataset(path: str) -> RetrievalDataset:
    data = read_json(path)
    if data is None:
        raise ValidationError(f"retrieval dataset not found: {path}")
    return dataset_from_dict(data)


def dataset_from_dict(data: dict[str, Any]) -> RetrievalDataset:
    dataset = RetrievalDataset(
        name=data.get("name", "unnamed"),
        description=data.get("description", ""),
        corpus=list(data.get("corpus") or []),
        cases=[
            RetrievalCase(
                query=case["query"],
                relevant={str(k): int(v) for k, v in (case.get("relevant") or {}).items()},
                note=case.get("note"),
            )
            for case in (data.get("queries") or [])
        ],
    )
    dataset.validate()
    return dataset


@dataclass
class ModeScore:
    mode: str
    precision: float = 0.0
    recall: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    degraded: bool = False
    notes: list[str] = field(default_factory=list)
    per_query: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "precision@k": round(self.precision, 4),
            "recall@k": round(self.recall, 4),
            "mrr": round(self.mrr, 4),
            "ndcg@k": round(self.ndcg, 4),
            "degraded": self.degraded,
            "notes": self.notes,
            "per_query": self.per_query,
        }


def precision_at_k(ranked: Sequence[str], relevant: dict[str, int], k: int) -> float:
    if k <= 0:
        return 0.0
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for item in top if item in relevant) / len(top)


def recall_at_k(ranked: Sequence[str], relevant: dict[str, int], k: int) -> float:
    if not relevant:
        return 0.0
    return sum(1 for item in ranked[:k] if item in relevant) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: dict[str, int]) -> float:
    for index, item in enumerate(ranked, start=1):
        if item in relevant:
            return 1.0 / index
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: dict[str, int], k: int) -> float:
    def gain(grade: int) -> float:
        return (2**grade) - 1

    dcg = 0.0
    for index, item in enumerate(ranked[:k], start=1):
        grade = relevant.get(item, 0)
        dcg += gain(grade) / math.log2(index + 1)
    ideal = sorted(relevant.values(), reverse=True)[:k]
    idcg = sum(gain(grade) / math.log2(index + 1) for index, grade in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


def evaluate_mode(
    mode: str,
    dataset: RetrievalDataset,
    retrieve,
    *,
    k: int = 5,
) -> ModeScore:
    """``retrieve(query, k) -> (ids, degraded, note)``."""
    score = ModeScore(mode=mode)
    precisions: list[float] = []
    recalls: list[float] = []
    rrs: list[float] = []
    ndcgs: list[float] = []
    any_degraded = False
    for case in dataset.cases:
        ids, degraded, note = retrieve(case.query, k)
        any_degraded = any_degraded or degraded
        if note and note not in score.notes:
            score.notes.append(note)
        precisions.append(precision_at_k(ids, case.relevant, k))
        recalls.append(recall_at_k(ids, case.relevant, k))
        rrs.append(reciprocal_rank(ids, case.relevant))
        ndcgs.append(ndcg_at_k(ids, case.relevant, k))
        score.per_query.append(
            {
                "query": case.query,
                "returned": list(ids[:k]),
                "relevant": sorted(case.relevant),
                "precision": round(precisions[-1], 3),
                "recall": round(recalls[-1], 3),
                "rr": round(rrs[-1], 3),
                "ndcg": round(ndcgs[-1], 3),
            }
        )
    n = len(dataset.cases)
    score.precision = sum(precisions) / n
    score.recall = sum(recalls) / n
    score.mrr = sum(rrs) / n
    score.ndcg = sum(ndcgs) / n
    score.degraded = any_degraded
    return score


def run_evaluation(
    dataset: RetrievalDataset,
    *,
    memory,
    embeddings=None,
    k: int = 5,
) -> dict[str, Any]:
    """Load the corpus into the (scratch) memory manager, then score each mode."""
    dataset.validate()
    id_map: dict[str, str] = {}
    for item in dataset.corpus:
        kind = item.get("kind", "permanent")
        details = None
        verification = None
        if kind == "solution":
            details = {
                "problem": item.get("problem", item["text"][:80]),
                "solution": item.get("solution", item["text"]),
                "evidence": item.get("evidence", ["evaluation corpus"]),
            }
            verification = item.get("verification", "verified")
        scope = item.get("scope")
        scope_id = item.get("scope_id")
        if kind == "project":
            scope, scope_id = "project", scope_id or "eval-scratch-project"
        result = memory.add(
            kind,
            item.get("title") or item["text"][:60],
            item["text"],
            category=item.get("category", "fact" if kind == "permanent" else "solution"),
            scope=scope,
            scope_id=scope_id,
            tags=item.get("tags") or [],
            details=details,
            verification=verification,
            allow_duplicate=True,
            check_similarity=False,
        )
        if result.is_err:
            raise ValidationError(f"cannot load corpus item {item['id']}: {result.error}")
        id_map[item["id"]] = result.value.id
    reverse_map = {v: k for k, v in id_map.items()}

    if embeddings is not None and embeddings.available:
        embeddings.embed_memories(limit=len(dataset.corpus) + 10)

    def translate(ids: Iterable[str]) -> list[str]:
        return [reverse_map[i] for i in ids if i in reverse_map]

    def keyword_mode(query: str, limit: int):
        """Pure keyword ranking: the embedding index is detached for this mode."""
        saved = memory.embedding_index
        memory.embedding_index = None
        try:
            outcome = memory.search(query, limit=limit, recency_boost=False)
            # Not a degradation: this is a deliberate baseline, reported as such.
            return translate(m.id for m in outcome.items), False, "keyword-only baseline (vectors deliberately unused)"
        finally:
            memory.embedding_index = saved

    def semantic_mode(query: str, limit: int):
        if embeddings is None or not embeddings.available:
            return [], True, "no embedding provider configured"
        found = embeddings.search(
            query,
            owner_types=("memory",),
            k=limit,
            candidate_ids=list(id_map.values()),
            threshold=0.0,  # ranking mode: return the top-k rather than gating on relevance
            record=False,
        )
        return translate(found.ids()), found.degraded, found.degraded_reason

    def hybrid_mode(query: str, limit: int):
        outcome = memory.search(query, limit=limit, recency_boost=False)
        return translate(m.id for m in outcome.items), outcome.degraded, outcome.degraded_reason

    modes = [
        evaluate_mode("keyword", dataset, keyword_mode, k=k),
        evaluate_mode("semantic", dataset, semantic_mode, k=k),
        evaluate_mode("hybrid", dataset, hybrid_mode, k=k),
    ]
    return {
        "dataset": dataset.name,
        "description": dataset.description,
        "size": dataset.size,
        "k": k,
        "modes": [m.to_dict() for m in modes],
        "best_mode": max(modes, key=lambda m: (m.ndcg, m.mrr)).mode,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Retrieval evaluation: {report['dataset']}",
        "",
        report["description"],
        "",
        f"Corpus: {report['size']['corpus']} items, queries: {report['size']['queries']}, k={report['k']}",
        "",
        "| mode | precision@k | recall@k | MRR | nDCG@k | degraded |",
        "|------|-------------|----------|-----|--------|----------|",
    ]
    for mode in report["modes"]:
        lines.append(
            f"| {mode['mode']} | {mode['precision@k']:.3f} | {mode['recall@k']:.3f} | "
            f"{mode['mrr']:.3f} | {mode['ndcg@k']:.3f} | {'yes' if mode['degraded'] else 'no'} |"
        )
    lines.append("")
    notes = sorted({note for mode in report["modes"] for note in mode.get("notes", []) if note})
    if notes:
        lines.append("Notes reported by the implementation:")
        lines.extend(f"- {note}" for note in notes)
        lines.append("")
    lines.append("Per-query detail is included in the JSON report (`--json`).")
    return "\n".join(lines)


__all__ = [
    "RetrievalDataset",
    "RetrievalCase",
    "load_dataset",
    "dataset_from_dict",
    "run_evaluation",
    "evaluate_mode",
    "render_markdown",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
    "ndcg_at_k",
]
