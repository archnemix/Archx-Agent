"""One search across everything the workspace already stores.

There is no search index and no second copy of the data. Each source is asked the
question using the manager that owns it, the answers are normalised to a single
:class:`SearchHit` shape, and the merged list is ranked by how much of the query each
hit actually contains.

That design costs recall on very large corpora (there is no inverted index over
messages) and it is deliberate: an index is a second copy of user data that can go
stale, and this app already has six memory systems and an embedding index whose job it
is to be clever. Unified search's job is to be *findable* and *honest*.

Honesty rules:

* a source that was not searched is listed in ``skipped`` with the reason, never
  silently omitted;
* a source that answered with less than it could have (keyword-only memory search
  because no embedding provider is configured) is listed in ``degraded``;
* files are only searched inside the configured tool roots, with a file-count and
  size cap, and binary files are skipped by name and by content sniff;
* scoring is explainable: coverage of the query terms plus a phrase bonus plus a
  title bonus. Nothing is ranked by a secret model.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from archx_agent.helpers.exceptions import ValidationError

SEARCH_KINDS = (
    "conversation",
    "memory",
    "task",
    "workflow",
    "project",
    "artifact",
    "file",
    "tool",
)

#: Higher sorts earlier when two hits score the same.
KIND_WEIGHT = {
    "memory": 6,
    "conversation": 5,
    "task": 4,
    "workflow": 3,
    "artifact": 3,
    "file": 2,
    "project": 1,
    "tool": 1,
}

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".idea", ".vscode", "site-packages",
}
TEXT_SNIFF_BYTES = 4096


@dataclass
class SearchHit:
    kind: str
    id: str
    title: str
    snippet: str
    score: float
    ref: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "snippet": self.snippet,
            "score": round(self.score, 4),
            "ref": self.ref,
            "meta": dict(self.meta),
        }


@dataclass
class SearchReport:
    query: str
    hits: list[SearchHit]
    counts: dict[str, int]
    skipped: dict[str, str] = field(default_factory=dict)
    degraded: list[str] = field(default_factory=list)
    scanned: dict[str, int] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "hits": [hit.to_dict() for hit in self.hits],
            "counts": dict(self.counts),
            "skipped": dict(self.skipped),
            "degraded": list(self.degraded),
            "scanned": dict(self.scanned),
            "elapsed_ms": self.elapsed_ms,
            "total": len(self.hits),
        }


def _terms(query: str) -> list[str]:
    words = [word.strip(".,;:!?()[]{}'\"`").lower() for word in (query or "").split()]
    terms = [word for word in words if len(word) >= 2]
    return sorted(set(terms), key=len, reverse=True)[:8]


def score_text(query: str, text: str, *, title: str | None = None) -> float:
    """Coverage of the query in ``title + text``, plus phrase and title bonuses.

    Matches are case-insensitive and the title counts as content: a memory titled
    "Database locking" whose body says "SQLite" is still about databases. Coverage is the
    fraction of query terms present (so a hit with every term scores at least 1.0); an
    exact phrase adds 0.5 and any term in the title adds 0.75, so "database locks" as a
    phrase outranks a document that contains both words chapters apart.
    """
    terms = _terms(query)
    lowered = (text or "").lower()
    title_text = (title or "").lower()
    haystack = f"{title_text}\n{lowered}" if title_text else lowered
    if not terms or not haystack.strip():
        return 0.0
    coverage = sum(1 for term in terms if term in haystack) / len(terms)
    if coverage == 0:
        return 0.0
    score = coverage
    phrase = (query or "").strip().lower()
    if len(phrase) >= 3 and phrase in haystack:
        score += 0.5
    if title_text and any(term in title_text for term in terms):
        score += 0.75
    return score


def _snippet(text: str, query: str, *, width: int = 180) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    lowered = text.lower()
    position = -1
    for term in _terms(query):
        position = lowered.find(term)
        if position >= 0:
            break
    if position < 0:
        return text[:width] + ("..." if len(text) > width else "")
    start = max(0, position - width // 3)
    end = min(len(text), start + width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def _looks_textual(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            head = handle.read(TEXT_SNIFF_BYTES)
    except OSError:
        return False
    if b"\x00" in head:
        return False
    return True


class SearchService:
    """Federated search over conversations, memory, tasks, workflows and files."""

    def __init__(self, workspace) -> None:
        self.ws = workspace

    # -- config ------------------------------------------------------------
    def _cfg(self, key: str, default: Any) -> Any:
        try:
            return self.ws.config.get(key)
        except Exception:  # noqa: BLE001
            return default

    # -- entry point -------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        kinds: Sequence[str] | None = None,
        limit: int | None = None,
        per_source: int | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        include_files: bool | None = None,
    ) -> SearchReport:
        started = time.perf_counter()
        query = (query or "").strip()
        if len(query) < 2:
            raise ValidationError("a search needs at least two characters")
        wanted = self._wanted_kinds(kinds)
        limit = int(limit) if limit else int(self._cfg("search.default_limit", 10))
        per_source = int(per_source) if per_source else int(self._cfg("search.per_source", 10))
        hits: list[SearchHit] = []
        counts: dict[str, int] = {}
        skipped: dict[str, str] = {}
        degraded: list[str] = []
        scanned: dict[str, int] = {}
        files_on = bool(self._cfg("search.include_files", True)) if include_files is None else include_files

        runners = {
            "conversation": self._conversations,
            "memory": self._memory,
            "task": self._tasks,
            "workflow": self._workflows,
            "project": self._projects,
            "artifact": self._artifacts,
            "tool": self._tools,
            "file": self._files,
        }
        for kind in SEARCH_KINDS:
            if kind not in wanted:
                continue
            if kind == "file" and not files_on:
                skipped["file"] = "file content search is disabled (search.include_files=false)"
                continue
            found, note, consumed = runners[kind](
                query, per_source,
                {"project_id": project_id, "conversation_id": conversation_id},
            )
            if note:
                if note.get("degraded"):
                    degraded.append(f"{kind}: {note['reason']}")
                else:
                    skipped[kind] = note["reason"]
            if found:
                hits.extend(found)
                counts[kind] = len(found)
            if consumed is not None:
                scanned[kind] = consumed
        hits.sort(key=lambda hit: (-hit.score, -KIND_WEIGHT.get(hit.kind, 0), hit.title.lower()))
        return SearchReport(
            query=query,
            hits=hits[: int(max(1, limit))],
            counts=counts,
            skipped=skipped,
            degraded=degraded,
            scanned=scanned,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def _wanted_kinds(self, kinds: Sequence[str] | None) -> set[str]:
        if not kinds:
            return set(SEARCH_KINDS)
        wanted: set[str] = set()
        for kind in kinds:
            value = (kind or "").strip()
            if value not in SEARCH_KINDS:
                raise ValidationError(
                    f"unknown search kind {kind!r} (known: {', '.join(SEARCH_KINDS)})"
                )
            wanted.add(value)
        return wanted

    # -- sources -----------------------------------------------------------
    def _conversations(self, query: str, per_source: int, scope: dict[str, Any]):
        manager = self.ws.conversations
        if manager is None:
            return [], {"degraded": False, "reason": "conversations are unavailable"}, None
        rows = manager.search(query, limit=per_source)
        if scope.get("conversation_id"):
            rows = [row for row in rows if row["conversation_id"] == scope["conversation_id"]]
        hits = [
            SearchHit(
                kind="conversation",
                id=row["conversation_id"],
                title=row.get("title") or "(untitled conversation)",
                snippet=_snippet(row.get("excerpt") or "", query),
                score=score_text(query, row.get("excerpt") or "", title=row.get("title")),
                ref=f"archx-agent conv show {row['conversation_id']}",
                meta={"matched": row.get("matched"), "updated_at": row.get("updated_at")},
            )
            for row in rows
        ]
        return hits, None, len(rows)

    def _memory(self, query: str, per_source: int, scope: dict[str, Any]):
        manager = self.ws.memory
        if manager is None:
            return [], {"degraded": False, "reason": "memory is unavailable"}, None
        try:
            outcome = manager.search(
                query,
                limit=per_source,
                project_id=scope.get("project_id"),
                conversation_id=scope.get("conversation_id"),
            )
        except Exception as exc:  # noqa: BLE001 - a broken source must not break search
            return [], {"degraded": True, "reason": f"memory search failed: {exc}"}, None
        hits = [
            SearchHit(
                kind="memory",
                id=hit.memory.id,
                title=hit.memory.title,
                snippet=_snippet(hit.memory.content, query),
                score=score_text(query, hit.memory.content, title=hit.memory.title) + min(0.5, hit.score / 10),
                ref=f"archx-agent memory show {hit.memory.id}",
                meta={
                    "memory_kind": hit.memory.kind,
                    "category": hit.memory.category,
                    "scope": hit.memory.scope,
                    "mode": outcome.mode,
                },
            )
            for hit in outcome.hits
        ]
        note = None
        if outcome.degraded:
            note = {
                "degraded": True,
                "reason": outcome.degraded_reason or "memory search ran keyword-only",
            }
        return hits, note, len(outcome.hits)

    def _tasks(self, query: str, per_source: int, scope: dict[str, Any]):
        manager = self.ws.tasks
        if manager is None:
            return [], {"degraded": False, "reason": "task history is unavailable"}, None
        rows = manager.search(query, limit=per_source)
        hits = [
            SearchHit(
                kind="task",
                id=task.id,
                title=f"{task.type}: {task.title}",
                snippet=_snippet(task.title, query),
                score=score_text(query, f"{task.type} {task.title}", title=task.title),
                ref=f"archx-agent tasks show {task.id}",
                meta={"status": task.status, "type": task.type, "created_at": task.created_at},
            )
            for task in rows
        ]
        return hits, None, len(rows)

    def _workflows(self, query: str, per_source: int, scope: dict[str, Any]):
        manager = self.ws.workflows
        if manager is None:
            return [], {"degraded": False, "reason": "workflows are unavailable"}, None
        rows = manager.search(query, limit=per_source)
        hits = [
            SearchHit(
                kind="workflow",
                id=workflow.id,
                title=workflow.name,
                snippet=_snippet(workflow.goal or workflow.name, query),
                score=score_text(query, f"{workflow.name} {workflow.goal}", title=workflow.name),
                ref=f"archx-agent agent show {workflow.id}",
                meta={"status": workflow.status, "mode": workflow.mode},
            )
            for workflow in rows
        ]
        return hits, None, len(rows)

    def _projects(self, query: str, per_source: int, scope: dict[str, Any]):
        manager = self.ws.projects
        if manager is None:
            return [], {"degraded": False, "reason": "projects are unavailable"}, None
        hits = []
        for project in manager.list(limit=200):
            text = f"{project.name} {project.description or ''} {project.slug}"
            score = score_text(query, text, title=project.name)
            if score <= 0:
                continue
            hits.append(
                SearchHit(
                    kind="project",
                    id=project.id,
                    title=project.name,
                    snippet=_snippet(project.description or project.name, query),
                    score=score,
                    ref=f"archx-agent projects show {project.id}",
                    meta={"slug": project.slug},
                )
            )
        hits.sort(key=lambda hit: -hit.score)
        return hits[:per_source], None, len(hits)

    def _artifacts(self, query: str, per_source: int, scope: dict[str, Any]):
        manager = self.ws.tasks
        if manager is None or not hasattr(manager, "artifacts"):
            return [], {"degraded": False, "reason": "artifacts are unavailable"}, None
        hits = []
        for artifact in manager.artifacts(limit=200):
            text = f"{artifact.name} {artifact.path} {artifact.kind}"
            score = score_text(query, text, title=artifact.name)
            if score <= 0:
                continue
            hits.append(
                SearchHit(
                    kind="artifact",
                    id=artifact.id,
                    title=artifact.name,
                    snippet=artifact.path,
                    score=score,
                    ref=f"archx-agent tasks artifacts {artifact.task_id}" if artifact.task_id
                    else "archx-agent tasks list",
                    meta={
                        "path": artifact.path,
                        "checksum": artifact.checksum,
                        "size": artifact.size,
                        "task_id": artifact.task_id,
                    },
                )
            )
        hits.sort(key=lambda hit: -hit.score)
        return hits[:per_source], None, len(hits)

    def _tools(self, query: str, per_source: int, scope: dict[str, Any]):
        manager = self.ws.tools
        if manager is None:
            return [], {"degraded": False, "reason": "the tool registry is unavailable"}, None
        hits = []
        for spec in manager.specs():
            text = f"{spec.name} {spec.summary}"
            score = score_text(query, text, title=spec.name)
            if score <= 0:
                continue
            hits.append(
                SearchHit(
                    kind="tool",
                    id=spec.name,
                    title=spec.name,
                    snippet=spec.summary,
                    score=score,
                    ref=f"archx-agent tools describe {spec.name}",
                    meta={
                        "capability": spec.capability,
                        "risk": spec.risk,
                        "origin": spec.origin,
                    },
                )
            )
        hits.sort(key=lambda hit: -hit.score)
        return hits[:per_source], None, len(hits)

    def _files(self, query: str, per_source: int, scope: dict[str, Any]):
        roots = []
        try:
            roots = [Path(root) for root in (self.ws.tool_roots() or []) if Path(root).is_dir()]
        except Exception:  # noqa: BLE001
            roots = []
        if not roots:
            return [], {"degraded": False, "reason": "no tool roots are configured"}, None
        max_files = int(self._cfg("search.max_files", 400))
        max_bytes = int(self._cfg("search.max_file_bytes", 262144))
        terms = _terms(query)
        hits: list[SearchHit] = []
        visited = 0
        truncated = False
        for root in roots:
            for directory, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    name for name in sorted(dirnames)
                    if name not in SKIP_DIRS and not name.startswith(".")
                ]
                for name in sorted(filenames):
                    if visited >= max_files:
                        truncated = True
                        break
                    path = Path(directory) / name
                    visited += 1
                    try:
                        if not path.is_file() or path.stat().st_size > max_bytes:
                            continue
                    except OSError:
                        continue
                    if not _looks_textual(path):
                        continue
                    try:
                        text = path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    lowered = text.lower()
                    if not any(term in lowered for term in terms):
                        continue
                    score = score_text(query, text, title=name)
                    line_number = 0
                    for index, line in enumerate(text.splitlines(), start=1):
                        if any(term in line.lower() for term in terms):
                            line_number = index
                            break
                    hits.append(
                        SearchHit(
                            kind="file",
                            id=str(path),
                            title=os.path.relpath(str(path), str(root)),
                            snippet=_snippet(text, query),
                            score=score,
                            ref=f"file://{path}",
                            meta={
                                "path": str(path),
                                "line": line_number or None,
                                "root": str(root),
                                "size": path.stat().st_size,
                            },
                        )
                    )
                if truncated:
                    break
            if truncated:
                break
        hits.sort(key=lambda hit: -hit.score)
        note = None
        if truncated:
            note = {
                "degraded": True,
                "reason": f"file search stopped after {max_files} files (search.max_files)",
            }
        return hits[:per_source], note, visited


__all__ = [
    "KIND_WEIGHT",
    "SEARCH_KINDS",
    "SearchHit",
    "SearchReport",
    "SearchService",
    "score_text",
]
