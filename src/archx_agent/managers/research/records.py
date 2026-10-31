"""ResearchManager records, constants and pure validation helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

RESEARCH_TABLES = ("research_runs", "research_sources")

MODES = ("local", "web", "mixed")

STATUSES = ("planning", "gathering", "reading", "synthesizing", "completed", "incomplete", "failed", "cancelled")

TERMINAL = frozenset({"completed", "incomplete", "failed", "cancelled"})

PLANNERS = ("model", "rules", "user")

SOURCE_KINDS = ("file", "memory", "conversation", "task", "workflow", "url")

SOURCE_STATUSES = ("fetched", "failed", "skipped")

STANCES = ("supports", "contradicts", "background", "mixed", "unknown")

CREDIBILITY = ("primary", "secondary", "internal", "unknown")

@dataclass
class ResearchSource:
    id: int
    run_id: str
    url: str
    title: str | None = None
    publisher: str | None = None
    retrieved_at: str = ""
    excerpt: str | None = None
    subsection: str | None = None
    limitations: str | None = None
    stance: str = "unknown"
    kind: str = "url"
    ref: str | None = None
    status: str = "fetched"
    error: str | None = None
    checksum: str | None = None
    bytes: int | None = None
    relevance: float | None = None
    credibility: str = "unknown"
    claims: list[dict[str, Any]] = field(default_factory=list)
    subquestion: int | None = None

    @property
    def usable(self) -> bool:
        return self.status == "fetched" and bool((self.excerpt or "").strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "kind": self.kind,
            "ref": self.ref or self.url,
            "url": self.url,
            "title": self.title,
            "publisher": self.publisher,
            "retrieved_at": self.retrieved_at,
            "subsection": self.subsection,
            "status": self.status,
            "error": self.error,
            "excerpt": self.excerpt,
            "limitations": self.limitations,
            "stance": self.stance,
            "credibility": self.credibility,
            "relevance": self.relevance,
            "checksum": self.checksum,
            "bytes": self.bytes,
            "claims": list(self.claims),
            "subquestion": self.subquestion,
            "usable": self.usable,
        }

@dataclass
class ResearchRun:
    id: str
    question: str
    status: str
    created_at: str
    completed_at: str | None = None
    mode: str = "local"
    plan: list[dict[str, Any]] = field(default_factory=list)
    planned_by: str = "rules"
    coverage: float = 0.0
    evidence_count: int = 0
    report: str | None = None
    report_path: str | None = None
    report_format: str = "markdown"
    limitations: list[str] = field(default_factory=list)
    error: str | None = None
    model_id: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None
    updated_at: str | None = None
    closed_at: str | None = None
    closed_note: str | None = None

    @property
    def terminal(self) -> bool:
        """The runner has nothing left to do. Not the same as the user being done."""
        return self.status in TERMINAL

    @property
    def closed(self) -> bool:
        """The user marked this question done. Only `close()` sets it."""
        return bool(self.closed_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "status": self.status,
            "mode": self.mode,
            "plan": list(self.plan),
            "planned_by": self.planned_by,
            "subquestions": [item.get("question") for item in self.plan],
            "coverage": round(float(self.coverage or 0.0), 4),
            "evidence_count": int(self.evidence_count or 0),
            "report": self.report,
            "report_path": self.report_path,
            "report_format": self.report_format,
            "limitations": list(self.limitations),
            "error": self.error,
            "model_id": self.model_id,
            "settings": dict(self.settings),
            "task_id": self.task_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "updated_at": self.updated_at,
            "closed": self.closed,
            "closed_at": self.closed_at,
            "closed_note": self.closed_note,
        }

def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default

def _run_from_row(row: Mapping[str, Any]) -> ResearchRun:
    return ResearchRun(
        id=row["id"],
        question=row["question"],
        status=row["status"],
        created_at=row["created_at"],
        completed_at=row.get("completed_at"),
        mode=row.get("mode") or "local",
        plan=_json(row.get("plan"), []),
        planned_by=row.get("planned_by") or "rules",
        coverage=float(row.get("coverage") or 0.0),
        evidence_count=int(row.get("evidence_count") or 0),
        report=row.get("report"),
        report_path=row.get("report_path"),
        report_format=row.get("report_format") or "markdown",
        limitations=_json(row.get("limitations"), []),
        error=row.get("error"),
        model_id=row.get("model_id"),
        settings=_json(row.get("settings"), {}),
        task_id=row.get("task_id"),
        updated_at=row.get("updated_at"),
        closed_at=row.get("closed_at"),
        closed_note=row.get("closed_note"),
    )

def _source_from_row(row: Mapping[str, Any]) -> ResearchSource:
    return ResearchSource(
        id=int(row["id"]),
        run_id=row["run_id"],
        url=row["url"],
        title=row.get("title"),
        publisher=row.get("publisher"),
        retrieved_at=row["retrieved_at"],
        excerpt=row.get("excerpt"),
        subsection=row.get("subsection"),
        limitations=row.get("limitations"),
        stance=row.get("stance") or "unknown",
        kind=row.get("kind") or "url",
        ref=row.get("ref"),
        status=row.get("status") or "fetched",
        error=row.get("error"),
        checksum=row.get("checksum"),
        bytes=row.get("bytes"),
        relevance=row.get("relevance"),
        credibility=row.get("credibility") or "unknown",
        claims=_json(row.get("claims"), []),
        subquestion=row.get("subquestion"),
    )
