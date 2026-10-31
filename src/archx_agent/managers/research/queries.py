"""ResearchManager: queries operations."""

from __future__ import annotations

from typing import Any
from archx_agent.helpers.exceptions import NotFoundError, ValidationError

from .records import ResearchSource, ResearchRun, _run_from_row, _source_from_row

class ResearchManagerQueriesMixin:
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

    def list(
        self, *, limit: int = 20, status: str | None = None, closed: bool | None = None
    ) -> list[ResearchRun]:
        wheres: list[str] = []
        params: list[Any] = []
        if status:
            wheres.append("status = ?")
            params.append(status)
        if closed is True:
            wheres.append("closed_at IS NOT NULL")
        elif closed is False:
            wheres.append("closed_at IS NULL")
        clause = (" WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(limit)
        rows = self.store.query(
            "SELECT * FROM research_runs" + clause + " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            tuple(params),
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
        closed = int(
            self.store.scalar("SELECT COUNT(*) FROM research_runs WHERE closed_at IS NOT NULL") or 0
        )
        return {
            "total": total,
            "by_status": by_status,
            "sources": sources,
            "runs": total,
            "closed": closed,
            "open": total - closed,
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
