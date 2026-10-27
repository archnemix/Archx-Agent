"""Research runs: a question, a plan, the evidence that was actually read, and a report.

A research run is deliberately *not* a chat that happens to mention sources. It is a record
with four separate things, each of which can be wrong and each of which is therefore stored:

``plan``
    the subquestions the run decided to answer, and whether a model or a rule produced them.
``sources``
    every document the run looked at - including the ones it could not read. A source that
    failed is a row with ``status = 'failed'`` and an error, not an omission.
``coverage``
    the fraction of subquestions that ended up with at least one usable source. A report
    with 0 coverage is possible and the report says so.
``report``
    the text that was produced, kept in the row *and* written to a file, so a moved file
    never means a lost report.

The table was reserved in v8; v18 added the columns this milestone needed. The same rule as
everywhere else applies: one store, one writer, journaled writes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

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

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

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


class ResearchManager(BaseManager):
    """Rows for research runs and their sources. No planning, no fetching, no prose."""

    tables = RESEARCH_TABLES

    def __init__(self, store, coordinator, *, events=None, config=None) -> None:
        self.config = config
        super().__init__(store, coordinator, events=events)

    def register_handlers(self) -> None:
        self.coordinator.register("research.create", self._apply_create)
        self.coordinator.register("research.update", self._apply_update)
        self.coordinator.register("research.source", self._apply_source)
        self.coordinator.register("research.delete", self._apply_delete)

    # -- write handlers ---------------------------------------------------
    def _apply_create(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run = payload["run"]
        tx.execute(
            "INSERT INTO research_runs(id, status, question, subquestions, report_path,"
            " report_format, created_at, completed_at, limitations, task_id, mode, plan,"
            " planned_by, coverage, evidence_count, report, error, model_id, settings,"
            " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run["id"], run["status"], run["question"],
                json_text(run.get("subquestions") or []),
                run.get("report_path"), run.get("report_format") or "markdown",
                run["created_at"], run.get("completed_at"),
                json_text(run.get("limitations") or []), run.get("task_id"),
                run.get("mode") or "local", json_text(run.get("plan") or []),
                run.get("planned_by") or "rules", float(run.get("coverage") or 0.0),
                int(run.get("evidence_count") or 0), run.get("report"), run.get("error"),
                run.get("model_id"), json_text(run.get("settings") or {}),
                run.get("updated_at") or run["created_at"],
            ),
        )
        return {"id": run["id"]}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = payload["id"]
        fields = payload["fields"]
        if not fields:
            return {"id": run_id, "updated": 0}
        columns = ", ".join(f"{name} = ?" for name in fields)
        tx.execute(
            f"UPDATE research_runs SET {columns} WHERE id = ?",
            (*fields.values(), run_id),
        )
        return {"id": run_id, "updated": 1}

    def _apply_source(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        source = payload["source"]
        tx.execute(
            "INSERT INTO research_sources(run_id, url, title, publisher, retrieved_at, excerpt,"
            " subsection, limitations, stance, kind, ref, status, error, checksum, bytes,"
            " relevance, credibility, claims, subquestion)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                source["run_id"], source["url"], source.get("title"),
                source.get("publisher"), source["retrieved_at"], source.get("excerpt"),
                source.get("subsection"), source.get("limitations"),
                source.get("stance") or "unknown", source.get("kind") or "url",
                source.get("ref"), source.get("status") or "fetched", source.get("error"),
                source.get("checksum"), source.get("bytes"), source.get("relevance"),
                source.get("credibility") or "unknown",
                json_text(source.get("claims") or []), source.get("subquestion"),
            ),
        )
        row = tx.query("SELECT last_insert_rowid() AS id")
        return {"id": int(row[0]["id"]) if row else None}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = payload["id"]
        tx.execute("DELETE FROM research_sources WHERE run_id = ?", (run_id,))
        tx.execute("DELETE FROM research_runs WHERE id = ?", (run_id,))
        return {"id": run_id, "deleted": 1}

    # -- reads ------------------------------------------------------------
    def _cfg(self, key: str, default: Any) -> Any:
        config = getattr(self, "config", None)
        if config is None:
            return default
        try:
            return config.get(key)
        except Exception:  # noqa: BLE001 - a missing key must not break a read
            return default

    def get(self, run_id: str) -> ResearchRun:
        rows = self.store.query("SELECT * FROM research_runs WHERE id = ?", (run_id,))
        if not rows:
            raise NotFoundError(f"no research run {run_id!r}")
        return _run_from_row(rows[0])

    def list(self, *, limit: int = 20, status: str | None = None) -> list[ResearchRun]:
        clause = " WHERE status = ?" if status else ""
        params: tuple[Any, ...] = (status, limit) if status else (limit,)
        rows = self.store.query(
            "SELECT * FROM research_runs" + clause + " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            params,
        )
        return [_run_from_row(row) for row in rows]

    def sources(self, run_id: str) -> list[ResearchSource]:
        rows = self.store.query(
            "SELECT * FROM research_sources WHERE run_id = ? ORDER BY id", (run_id,)
        )
        return [_source_from_row(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for row in self.store.query(
            "SELECT status, COUNT(*) AS n FROM research_runs GROUP BY status", ()
        ):
            by_status[str(row["status"])] = int(row["n"])
        total = int(self.store.scalar("SELECT COUNT(*) FROM research_runs") or 0)
        sources = int(self.store.scalar("SELECT COUNT(*) FROM research_sources") or 0)
        return {
            "total": total,
            "by_status": by_status,
            "sources": sources,
            "runs": total,
        }

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Titles and questions, for `research list` and any future unified source."""
        terms = [word for word in str(query or "").lower().split() if len(word) >= 2]
        if not terms:
            raise ValidationError("a research search needs at least two characters")
        rows = self.store.query(
            "SELECT * FROM research_runs ORDER BY created_at DESC, rowid DESC LIMIT 500", ()
        )
        hits: list[dict[str, Any]] = []
        for row in rows:
            haystack = f"{row['question']} {row.get('report') or ''}".lower()
            if all(term in haystack for term in terms):
                hits.append(_run_from_row(row).to_dict())
        return hits[: max(1, int(limit))]

    # -- writes -----------------------------------------------------------
    def create(
        self,
        question: str,
        *,
        mode: str = "local",
        plan: Sequence[Mapping[str, Any]] | None = None,
        planned_by: str = "rules",
        report_format: str = "markdown",
        model_id: str | None = None,
        settings: Mapping[str, Any] | None = None,
        task_id: str | None = None,
        status: str = "planning",
    ) -> ResearchRun:
        question = (question or "").strip()
        if len(question) < 4:
            raise ValidationError("a research question needs at least four characters")
        if mode not in MODES:
            raise ValidationError(f"mode must be one of {', '.join(MODES)}")
        if planned_by not in PLANNERS:
            raise ValidationError(f"planned_by must be one of {', '.join(PLANNERS)}")
        if status not in STATUSES:
            raise ValidationError(f"unknown research status {status!r}")
        run_id = new_id("rs_")
        now = iso_now()
        plan_list = [dict(item) for item in (plan or [])]
        self._write(
            "research.create",
            {
                "run": {
                    "id": run_id,
                    "question": question,
                    "status": status,
                    "mode": mode,
                    "plan": plan_list,
                    "subquestions": [item.get("question") for item in plan_list],
                    "planned_by": planned_by,
                    "report_format": report_format,
                    "model_id": model_id,
                    "settings": dict(settings or {}),
                    "task_id": task_id,
                    "created_at": now,
                    "updated_at": now,
                }
            },
        )
        self.trace(
            "research", "research.created", status="ok",
            payload={"run_id": run_id, "mode": mode, "planned_by": planned_by,
                     "subquestions": len(plan_list)},
        )
        return self.get(run_id)

    def update(self, run_id: str, **fields: Any) -> ResearchRun:
        run = self.get(run_id)
        if run.terminal:
            raise ConflictError(f"research run {run_id} is already {run.status}")
        allowed = {
            "status", "plan", "subquestions", "planned_by", "coverage", "evidence_count",
            "report", "report_path", "report_format", "limitations", "error", "model_id",
            "settings", "task_id", "completed_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValidationError(f"cannot update {', '.join(sorted(unknown))}")
        changes: dict[str, Any] = {}
        for name, value in fields.items():
            if name in {"plan", "subquestions", "limitations", "settings"}:
                changes[name] = json_text(value if value is not None else [])
            elif name == "coverage":
                changes[name] = float(value or 0.0)
            elif name == "evidence_count":
                changes[name] = int(value or 0)
            elif name == "status":
                if value not in STATUSES:
                    raise ValidationError(f"unknown research status {value!r}")
                changes[name] = value
            else:
                changes[name] = value
        changes["updated_at"] = iso_now()
        self._write("research.update", {"id": run_id, "fields": changes})
        return self.get(run_id)

    def finish(
        self,
        run_id: str,
        *,
        status: str = "completed",
        report: str | None = None,
        report_path: str | None = None,
        coverage: float | None = None,
        evidence_count: int | None = None,
        limitations: Sequence[str] | None = None,
        error: str | None = None,
    ) -> ResearchRun:
        if status not in TERMINAL:
            raise ValidationError(f"{status!r} is not a terminal research status")
        run = self.get(run_id)
        if run.terminal:
            raise ConflictError(f"research run {run_id} is already {run.status}")
        fields: dict[str, Any] = {
            "status": status,
            "completed_at": iso_now(),
            "report": report if report is not None else run.report,
            "report_path": report_path if report_path is not None else run.report_path,
            "coverage": coverage if coverage is not None else run.coverage,
            "evidence_count": evidence_count if evidence_count is not None else run.evidence_count,
            "limitations": list(limitations if limitations is not None else run.limitations),
            "error": error,
        }
        jsonish = {"limitations"}
        changes: dict[str, Any] = {}
        for name, value in fields.items():
            changes[name] = json_text(value) if name in jsonish else value
        changes["updated_at"] = iso_now()
        self._write("research.update", {"id": run_id, "fields": changes})
        self.trace(
            "research", "research.finished", status="ok" if status == "completed" else "warn",
            payload={"run_id": run_id, "status": status,
                     "coverage": float(coverage or 0.0),
                     "evidence": int(evidence_count or 0)},
        )
        return self.get(run_id)

    def delete(self, run_id: str) -> dict[str, Any]:
        """Delete a run and its sources. Traces and the task record are left alone."""
        self.get(run_id)
        result = self._write("research.delete", {"id": run_id})
        self.trace("research", "research.deleted", status="ok", payload={"run_id": run_id})
        return result

    def add_source(
        self,
        run_id: str,
        *,
        url: str,
        kind: str,
        title: str | None = None,
        publisher: str | None = None,
        excerpt: str | None = None,
        ref: str | None = None,
        status: str = "fetched",
        error: str | None = None,
        checksum: str | None = None,
        bytes_: int | None = None,
        relevance: float | None = None,
        credibility: str = "unknown",
        stance: str = "unknown",
        claims: Sequence[Mapping[str, Any]] | None = None,
        subquestion: int | None = None,
        subsection: str | None = None,
        limitations: str | None = None,
    ) -> ResearchSource:
        self.get(run_id)  # a source must belong to a run that exists
        if kind not in SOURCE_KINDS:
            raise ValidationError(f"source kind must be one of {', '.join(SOURCE_KINDS)}")
        if status not in SOURCE_STATUSES:
            raise ValidationError(f"source status must be one of {', '.join(SOURCE_STATUSES)}")
        if not (url or "").strip():
            raise ValidationError("a source needs a URL or reference")
        payload = {
            "run_id": run_id,
            "url": url.strip(),
            "kind": kind,
            "title": title,
            "publisher": publisher,
            "retrieved_at": iso_now(),
            "excerpt": excerpt,
            "ref": ref or url,
            "status": status,
            "error": error,
            "checksum": checksum,
            "bytes": int(bytes_) if bytes_ is not None else None,
            "relevance": float(relevance) if relevance is not None else None,
            "credibility": credibility if credibility in CREDIBILITY else "unknown",
            "stance": stance if stance in STANCES else "unknown",
            "claims": [dict(item) for item in (claims or [])],
            "subquestion": subquestion,
            "subsection": subsection,
            "limitations": limitations,
        }
        result = self._write("research.source", {"source": payload})
        source_id = result.get("id")
        self.trace(
            "research", "research.source", status="ok" if status == "fetched" else "warn",
            payload={"run_id": run_id, "source_id": source_id, "kind": kind,
                     "ref": payload["ref"], "status": status},
        )
        for source in self.sources(run_id):
            if source.id == source_id:
                return source
        raise NotFoundError("the source row disappeared")  # pragma: no cover


__all__ = [
    "CREDIBILITY",
    "MODES",
    "PLANNERS",
    "RESEARCH_TABLES",
    "ResearchManager",
    "ResearchRun",
    "ResearchSource",
    "SOURCE_KINDS",
    "SOURCE_STATUSES",
    "STANCES",
    "STATUSES",
    "TERMINAL",
]
