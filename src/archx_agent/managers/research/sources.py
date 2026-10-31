"""ResearchManager: sources operations."""

from __future__ import annotations

from typing import Any, Mapping, Sequence
from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.timeutil import iso_now

from .records import SOURCE_KINDS, SOURCE_STATUSES, STANCES, CREDIBILITY, ResearchSource

class ResearchManagerSourcesMixin:
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
