"""Structured event + trace store.

Design decisions (see THINKING.md):
* Ordering uses an ``AUTOINCREMENT`` sequence, never the wall clock. Two events
  in the same millisecond still have a defined order.
* Events live in their own database file so tracing can never corrupt or block
  the primary database.
* Payloads are redacted **before** they are written, and again on export.
* We never store private chain-of-thought: the schema has fields for goals,
  decisions, evidence and results, not free-form "thinking".
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import redaction
from .exceptions import ValidationError
from .jsonio import atomic_write_text, json_text
from .paths import ensure_directory
from .result import WriteOutcome
from .sqlite_store import Migration, SqliteStore
from .timeutil import iso_now
from .write_coordinator import WriteCoordinator

LEVELS = {"summary": 1, "detailed": 2, "diagnostic": 3}

KINDS = {
    "conversation",
    "message",
    "model_call",
    "context",
    "memory",
    "tool_call",
    "permission",
    "artifact",
    "test_result",
    "file_change",
    "task",
    "agent_run",
    "subagent",
    "report",
    "error",
    "system",
    "storage",
    "provider",
    "scheduler",
    "job",
    "mcp",
    "extension",
    "experiment",
    "training",
    "dataset",
    "remote",
    "automation",
    "game",
    "media",
    "voice",
    "learning",
    "research",
    "project",
    "backup",
    "import_export",
}

EVENT_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="events",
        statements=(
            "CREATE TABLE IF NOT EXISTS events ("
            " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
            " event_id TEXT NOT NULL UNIQUE,"
            " ts TEXT NOT NULL,"
            " level TEXT NOT NULL,"
            " kind TEXT NOT NULL,"
            " name TEXT NOT NULL,"
            " status TEXT NOT NULL DEFAULT 'ok',"
            " conversation_id TEXT,"
            " message_id TEXT,"
            " task_id TEXT,"
            " run_id TEXT,"
            " parent_id TEXT,"
            " tool_call_id TEXT,"
            " project_id TEXT,"
            " duration_ms REAL,"
            " payload TEXT,"
            " error TEXT)",
            "CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, seq)",
            "CREATE INDEX IF NOT EXISTS idx_events_conv ON events(conversation_id, seq)",
            "CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq)",
            "CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, seq)",
            "CREATE INDEX IF NOT EXISTS idx_events_parent ON events(parent_id)",
            "CREATE INDEX IF NOT EXISTS idx_events_status ON events(status, seq)",
            "CREATE TABLE IF NOT EXISTS trace_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        ),
    ),
)


@dataclass
class EventRecord:
    seq: int
    event_id: str
    ts: str
    level: str
    kind: str
    name: str
    status: str
    conversation_id: str | None = None
    message_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    parent_id: str | None = None
    tool_call_id: str | None = None
    project_id: str | None = None
    duration_ms: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "event_id": self.event_id,
            "ts": self.ts,
            "level": self.level,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "parent_id": self.parent_id,
            "tool_call_id": self.tool_call_id,
            "project_id": self.project_id,
            "duration_ms": self.duration_ms,
            "payload": self.payload,
            "error": self.error,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "EventRecord":
        payload = row.get("payload")
        return cls(
            seq=row["seq"],
            event_id=row["event_id"],
            ts=row["ts"],
            level=row["level"],
            kind=row["kind"],
            name=row["name"],
            status=row["status"],
            conversation_id=row.get("conversation_id"),
            message_id=row.get("message_id"),
            task_id=row.get("task_id"),
            run_id=row.get("run_id"),
            parent_id=row.get("parent_id"),
            tool_call_id=row.get("tool_call_id"),
            project_id=row.get("project_id"),
            duration_ms=row.get("duration_ms"),
            payload=json.loads(payload) if payload else {},
            error=row.get("error"),
        )


class EventStore:
    """Append-only trace store with filters, causal tree and retention."""

    def __init__(self, path: str | os.PathLike[str], *, capture_level: str = "detailed", coordinator: WriteCoordinator | None = None) -> None:
        self.path = Path(path).expanduser()
        ensure_directory(self.path.parent)
        self.store = SqliteStore(self.path)
        self.store.migrate(EVENT_MIGRATIONS)
        self.capture_level = capture_level
        self._owns_coordinator = coordinator is None
        self.coordinator = coordinator or WriteCoordinator(self.store, name="events")
        if not self.coordinator.has_kind("event.append"):
            self.coordinator.register("event.append", self._apply_event)
        self._pending: int = 0

    # -- write -----------------------------------------------------------
    def _apply_event(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "INSERT INTO events(event_id, ts, level, kind, name, status, conversation_id, message_id,"
            " task_id, run_id, parent_id, tool_call_id, project_id, duration_ms, payload, error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload["event_id"],
                payload["ts"],
                payload["level"],
                payload["kind"],
                payload["name"],
                payload["status"],
                payload.get("conversation_id"),
                payload.get("message_id"),
                payload.get("task_id"),
                payload.get("run_id"),
                payload.get("parent_id"),
                payload.get("tool_call_id"),
                payload.get("project_id"),
                payload.get("duration_ms"),
                json_text(payload.get("payload") or {}),
                payload.get("error"),
            ),
        )
        return {"event_id": payload["event_id"]}

    def record(
        self,
        kind: str,
        name: str,
        *,
        level: str = "detailed",
        status: str = "ok",
        conversation_id: str | None = None,
        message_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        parent_id: str | None = None,
        tool_call_id: str | None = None,
        project_id: str | None = None,
        duration_ms: float | None = None,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
        op_id: str | None = None,
    ) -> str | None:
        """Record an event. Returns the event id, or ``None`` when filtered."""
        if kind not in KINDS and not kind.startswith("x_"):
            raise ValidationError(f"unknown event kind {kind!r}")
        if level not in LEVELS:
            raise ValidationError(f"unknown capture level {level!r} (expected one of {sorted(LEVELS)})")
        if LEVELS[level] > LEVELS[self.capture_level] and status == "ok":
            return None
        safe_payload = redaction.redact(payload or {})
        event_id = payload.get("event_id") if payload and isinstance(payload.get("event_id"), str) else None
        if event_id is None:
            from .timeutil import new_id

            event_id = new_id("ev_")
        record = {
            "event_id": event_id,
            "ts": iso_now(),
            "level": level,
            "kind": kind,
            "name": name,
            "status": status,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "task_id": task_id,
            "run_id": run_id,
            "parent_id": parent_id,
            "tool_call_id": tool_call_id,
            "project_id": project_id,
            "duration_ms": duration_ms,
            "payload": safe_payload,
            "error": redaction.redact_text(error) if error else None,
        }
        receipt = self.coordinator.submit("event.append", record, op_id=op_id)
        if receipt.outcome is WriteOutcome.FAILED:
            # Tracing is best effort: never break the user's workflow because a
            # trace write failed, but do surface it on stderr via the caller.
            return None
        return event_id

    def flush(self, timeout: float = 10.0) -> bool:
        return self.coordinator.flush(timeout)

    def close(self) -> None:
        if self._owns_coordinator:
            self.coordinator.stop()
        self.store.close()

    # -- read ------------------------------------------------------------
    def count(self) -> int:
        return int(self.store.scalar("SELECT COUNT(*) FROM events") or 0)

    def query(
        self,
        *,
        kind: str | Iterable[str] | None = None,
        name: str | None = None,
        status: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        project_id: str | None = None,
        min_level: str | None = None,
        since_seq: int | None = None,
        limit: int = 100,
        offset: int = 0,
        newest_first: bool = False,
    ) -> list[EventRecord]:
        sql, params = self._build_filter_query(
            kind=kind,
            name=name,
            status=status,
            conversation_id=conversation_id,
            task_id=task_id,
            run_id=run_id,
            project_id=project_id,
            min_level=min_level,
            since_seq=since_seq,
            newest_first=newest_first,
        )
        sql += " LIMIT ? OFFSET ?"
        params.extend([max(1, int(limit)), max(0, int(offset))])
        return [EventRecord.from_row(r) for r in self.store.query(sql, params)]

    def _build_filter_query(self, **kw: Any) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        kind = kw["kind"]
        if kind is not None:
            kinds = [kind] if isinstance(kind, str) else list(kind)
            clauses.append("kind IN (" + ",".join("?" * len(kinds)) + ")")
            params.extend(kinds)
        for key, column in (
            ("name", "name"),
            ("status", "status"),
            ("conversation_id", "conversation_id"),
            ("task_id", "task_id"),
            ("run_id", "run_id"),
            ("project_id", "project_id"),
        ):
            if kw[key] is not None:
                clauses.append(f"{column} = ?")
                params.append(kw[key])
        if kw["min_level"] is not None:
            allowed = [name for name, rank in LEVELS.items() if rank >= LEVELS[kw["min_level"]]]
            clauses.append("level IN (" + ",".join("?" * len(allowed)) + ")")
            params.extend(allowed)
        if kw["since_seq"] is not None:
            clauses.append("seq > ?")
            params.append(int(kw["since_seq"]))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order = "DESC" if kw["newest_first"] else "ASC"
        return f"SELECT * FROM events{where} ORDER BY seq {order}", params

    def get(self, event_id: str) -> EventRecord | None:
        row = self.store.query_one("SELECT * FROM events WHERE event_id = ?", (event_id,))
        return EventRecord.from_row(row) if row else None

    def children(self, parent_id: str) -> list[EventRecord]:
        rows = self.store.query("SELECT * FROM events WHERE parent_id = ? ORDER BY seq", (parent_id,))
        return [EventRecord.from_row(r) for r in rows]

    def trace_tree(self, root_event_id: str, *, max_nodes: int = 500) -> dict[str, Any]:
        root = self.get(root_event_id)
        if root is None:
            raise ValidationError(f"no such event: {root_event_id}")
        seen: set[str] = set()
        nodes = 0

        def build(rec: EventRecord) -> dict[str, Any]:
            nonlocal nodes
            seen.add(rec.event_id)
            nodes += 1
            kids: list[dict[str, Any]] = []
            if nodes < max_nodes:
                for child in self.children(rec.event_id):
                    if child.event_id in seen:
                        continue
                    kids.append(build(child))
            return {"event": rec.to_dict(), "children": kids}

        return build(root)

    def recent_errors(self, limit: int = 20) -> list[EventRecord]:
        rows = self.store.query(
            "SELECT * FROM events WHERE status IN ('error','denied','failed') ORDER BY seq DESC LIMIT ?", (limit,)
        )
        return [EventRecord.from_row(r) for r in rows]

    def summaries(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT kind, status, COUNT(*) AS n, MIN(seq) AS first_seq, MAX(seq) AS last_seq"
            " FROM events GROUP BY kind, status ORDER BY n DESC LIMIT ?",
            (limit,),
        )
        return rows

    # -- retention / export ----------------------------------------------
    def apply_retention(self, *, max_age_days: int | None = None, max_events: int | None = None) -> int:
        """Delete old events. Error/denied events are kept longer (2x age)."""
        removed = 0
        with self.store.write_tx() as tx:
            if max_age_days is not None:
                from datetime import datetime, timedelta, timezone

                cutoff_ok = (
                    datetime.now(timezone.utc) - timedelta(days=max_age_days)
                ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                cutoff_err = (
                    datetime.now(timezone.utc) - timedelta(days=max_age_days * 2)
                ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                removed += tx.execute(
                    "DELETE FROM events WHERE ts < ? AND status IN ('ok','info')", (cutoff_ok,)
                )
                removed += tx.execute("DELETE FROM events WHERE ts < ?", (cutoff_err,))
            if max_events is not None:
                cutoff_seq = tx.scalar(
                    "SELECT seq FROM events ORDER BY seq DESC LIMIT 1 OFFSET ?", (max_events,)
                )
                if cutoff_seq is not None:
                    removed += tx.execute(
                        "DELETE FROM events WHERE seq <= ? AND status IN ('ok','info')", (cutoff_seq,)
                    )
        return removed

    def export_jsonl(self, path: str | os.PathLike[str], **filters: Any) -> Path:
        """Export with a second redaction pass over the serialised lines."""
        records = self.query(limit=filters.pop("limit", 100000), **filters)
        lines = []
        for rec in records:
            data = redaction.redact(rec.to_dict())
            lines.append(redaction.redact_text(json_text(data, indent=None)))
        target = Path(path).expanduser()
        atomic_write_text(target, "\n".join(lines) + ("\n" if lines else ""))
        return target


__all__ = ["EventStore", "EventRecord", "LEVELS", "KINDS", "EVENT_MIGRATIONS"]
