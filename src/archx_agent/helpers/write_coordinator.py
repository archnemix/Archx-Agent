"""Serialised, journalled writes with exactly-once semantics.

Why a coordinator instead of ad-hoc transactions?
------------------------------------------------
SQLite tolerates one writer at a time. With several threads, an event store, a
scheduler and background jobs all writing, "database is locked" becomes a
user-visible failure. The coordinator owns the write path:

* a single writer thread (so no lock storms),
* a durable journal row per operation, committed **in the same transaction**
  as the data, plus an ``applied_writes`` marker -> replay never double-applies,
* bounded queue with explicit ``PENDING`` backpressure instead of silent drops,
* ``COMMITTED`` is only reported after ``COMMIT`` returns.

Two-phase operations
--------------------
``submit(kind, payload)`` is atomic (journal + data in one transaction). For
long operations that must survive a crash mid-way, callers use
``begin_durable(kind, payload)`` which commits the *intent*, then
``complete_durable(op_id)`` which runs the handler and records
``applied_writes``. A crash between the two is repaired by :meth:`replay`.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .exceptions import ArchxError, StorageError, WriteBackpressureError
from .jsonio import json_text
from .sqlite_store import Migration, SqliteStore, Tx
from .timeutil import iso_now, new_id
from .result import WriteOutcome, WriteReceipt

Handler = Callable[[Tx, dict[str, Any]], Any]

JOURNAL_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="write-journal",
        statements=(
            "CREATE TABLE IF NOT EXISTS write_journal ("
            " op_id TEXT PRIMARY KEY,"
            " kind TEXT NOT NULL,"
            " seq INTEGER NOT NULL,"
            " state TEXT NOT NULL,"
            " payload TEXT NOT NULL,"
            " result TEXT,"
            " error TEXT,"
            " attempts INTEGER NOT NULL DEFAULT 1,"
            " created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS idx_write_journal_state ON write_journal(state)",
            "CREATE TABLE IF NOT EXISTS applied_writes ("
            " op_id TEXT PRIMARY KEY,"
            " kind TEXT NOT NULL,"
            " applied_at TEXT NOT NULL)",
        ),
    ),
)


@dataclass
class _Job:
    op_id: str
    kind: str
    payload: dict[str, Any]
    done: threading.Event = field(default_factory=threading.Event)
    receipt: WriteReceipt | None = None
    two_phase: bool = False


@dataclass
class CoordinatorStats:
    submitted: int = 0
    committed: int = 0
    duplicates: int = 0
    failed: int = 0
    pending_returns: int = 0
    max_queue_depth: int = 0
    replayed: int = 0


class WriteCoordinator:
    """One per database file. Created once at composition time."""

    def __init__(
        self,
        store: SqliteStore,
        *,
        name: str = "main",
        max_queue: int = 1024,
        busy_retries: int = 3,
        autocreate_schema: bool = True,
        start: bool = True,
    ) -> None:
        self.store = store
        self.name = name
        self.max_queue = max_queue
        self.busy_retries = busy_retries
        self._handlers: dict[str, Handler] = {}
        self._queue: queue.Queue[_Job | None] = queue.Queue(maxsize=max_queue)
        self._thread: threading.Thread | None = None
        self._closing = threading.Event()
        self._seq_lock = threading.Lock()
        self._seq = 0
        self._write_lock = threading.Lock()
        self.stats = CoordinatorStats()
        if autocreate_schema:
            self.ensure_schema(store)
        if start:
            self.start()

    @staticmethod
    def ensure_schema(store: SqliteStore) -> None:
        """Create journal tables.

        The journal does not participate in the application's
        ``schema_migrations`` numbering (that table belongs to the domain
        schema); the DDL here is idempotent so it is safe from any process.
        """
        if store.table_exists("write_journal") and store.table_exists("applied_writes"):
            return
        try:
            with store.write_tx() as tx:
                for migration in JOURNAL_MIGRATIONS:
                    for stmt in migration.statements:
                        tx.execute(stmt)
        except StorageError:
            # A concurrent process may have won the race; only complain if the
            # tables still do not exist.
            if not (store.table_exists("write_journal") and store.table_exists("applied_writes")):
                raise

    # -- registration ----------------------------------------------------
    def register(self, kind: str, handler: Handler) -> None:
        """Register the handler for a write kind.

        Kind names are persisted in the journal; renaming one requires a
        deliberate migration.
        """
        if not kind or not kind.replace("_", "").replace(".", "").isalnum():
            raise StorageError(f"invalid write kind: {kind!r}")
        if kind in self._handlers and self._handlers[kind] is not handler:
            raise StorageError(f"write kind already registered: {kind}")
        self._handlers[kind] = handler

    def has_kind(self, kind: str) -> bool:
        return kind in self._handlers

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._closing.clear()
        self._thread = threading.Thread(target=self._run, name=f"archx-writer-{self.name}", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Drain the queue, then stop the writer thread."""
        self._closing.set()
        try:
            self._queue.put(None, timeout=timeout)
        except queue.Full:  # pragma: no cover - only under extreme load
            pass
        if self._thread:
            self._thread.join(timeout)
        self.store.checkpoint()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -- submission ------------------------------------------------------
    def submit(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        op_id: str | None = None,
        wait: bool = True,
        timeout: float | None = 30.0,
        two_phase: bool = False,
    ) -> WriteReceipt:
        if kind not in self._handlers:
            raise StorageError(f"no handler registered for write kind {kind!r}")
        op = op_id or new_id("op_")
        if not self.running:
            # Synchronous fallback keeps CLI/testing use working without threads.
            return self._execute_inline(kind, payload, op, two_phase=two_phase)
        job = _Job(op_id=op, kind=kind, payload=payload, two_phase=two_phase)
        self.stats.submitted += 1
        try:
            self._queue.put(job, timeout=timeout if timeout is not None else 30.0)
        except queue.Full:
            self.stats.pending_returns += 1
            return WriteReceipt(
                outcome=WriteOutcome.PENDING,
                op_id=op,
                kind=kind,
                error=WriteBackpressureError(
                    f"write queue full ({self.max_queue}); request not accepted", kind=kind, op_id=op
                ),
            )
        self.stats.max_queue_depth = max(self.stats.max_queue_depth, self._queue.qsize())
        if not wait:
            return WriteReceipt(outcome=WriteOutcome.PENDING, op_id=op, kind=kind)
        if not job.done.wait(timeout):
            self.stats.pending_returns += 1
            return WriteReceipt(
                outcome=WriteOutcome.PENDING,
                op_id=op,
                kind=kind,
                error=WriteBackpressureError(f"write {kind} did not commit within {timeout}s", op_id=op),
            )
        assert job.receipt is not None
        return job.receipt

    def submit_many(self, items: list[tuple[str, dict[str, Any]]], *, timeout: float = 60.0) -> list[WriteReceipt]:
        receipts: list[WriteReceipt] = []
        for kind, payload in items:
            receipts.append(self.submit(kind, payload, timeout=timeout))
        return receipts

    def flush(self, timeout: float = 30.0) -> bool:
        """Block until the queue is empty (best effort)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.empty() and not self._busy:
                return True
            time.sleep(0.005)
        return self._queue.empty()

    @property
    def _busy(self) -> bool:
        return bool(self._current_job)

    _current_job: _Job | None = None

    def _execute_inline(self, kind: str, payload: dict[str, Any], op: str, *, two_phase: bool) -> WriteReceipt:
        job = _Job(op_id=op, kind=kind, payload=payload, two_phase=two_phase)
        receipt = self._process(job)
        self._account(receipt)
        return receipt

    # -- worker ----------------------------------------------------------
    def _run(self) -> None:
        while True:
            try:
                job = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._closing.is_set():
                    return
                continue
            if job is None:
                return
            self._current_job = job
            try:
                receipt = self._process(job)
            except Exception as exc:  # noqa: BLE001 - must not kill the writer
                receipt = WriteReceipt(
                    outcome=WriteOutcome.FAILED, op_id=job.op_id, kind=job.kind, error=exc
                )
            finally:
                self._current_job = None
            job.receipt = receipt
            job.done.set()
            self._account(receipt)
            if self._closing.is_set() and self._queue.empty():
                return

    def _account(self, receipt: WriteReceipt) -> None:
        if receipt.outcome is WriteOutcome.COMMITTED:
            self.stats.committed += 1
        elif receipt.outcome is WriteOutcome.DUPLICATE:
            self.stats.duplicates += 1
        elif receipt.outcome is WriteOutcome.FAILED:
            self.stats.failed += 1

    def _next_seq(self, tx: Tx) -> int:
        value = tx.scalar("SELECT COALESCE(MAX(seq), 0) + 1 FROM write_journal")
        return int(value or 1)

    def _process(self, job: _Job) -> WriteReceipt:
        handler = self._handlers[job.kind]
        for attempt in range(self.busy_retries):
            try:
                return self._process_once(job, handler)
            except _Retry as retry:
                if attempt == self.busy_retries - 1:
                    return WriteReceipt(
                        outcome=WriteOutcome.FAILED, op_id=job.op_id, kind=job.kind, error=retry.error
                    )
                time.sleep(0.02 * (attempt + 1))
            except ArchxError as exc:
                return WriteReceipt(outcome=WriteOutcome.FAILED, op_id=job.op_id, kind=job.kind, error=exc)
            except Exception as exc:  # noqa: BLE001
                return WriteReceipt(outcome=WriteOutcome.FAILED, op_id=job.op_id, kind=job.kind, error=exc)
        raise AssertionError("unreachable")  # pragma: no cover

    def _process_once(self, job: _Job, handler: Handler) -> WriteReceipt:
        payload_text = json_text(job.payload)
        with self._write_lock:
            # Fast path: already committed under this op id.
            existing = self.store.query_one(
                "SELECT state, result, kind FROM write_journal WHERE op_id = ?", (job.op_id,)
            )
            if existing and existing["state"] == "committed":
                return WriteReceipt(
                    outcome=WriteOutcome.DUPLICATE,
                    op_id=job.op_id,
                    kind=job.kind,
                    value=_decode(existing["result"]),
                    replayed=False,
                )
            if job.two_phase and not existing:
                with self.store.write_tx() as tx:
                    tx.execute(
                        "INSERT INTO write_journal(op_id, kind, seq, state, payload, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (
                            job.op_id,
                            job.kind,
                            self._next_seq(tx),
                            "intent",
                            payload_text,
                            iso_now(),
                            iso_now(),
                        ),
                    )
            with self.store.write_tx() as tx:
                if not job.two_phase:
                    tx.execute(
                        "INSERT OR IGNORE INTO write_journal(op_id, kind, seq, state, payload, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (
                            job.op_id,
                            job.kind,
                            self._next_seq(tx),
                            "pending",
                            payload_text,
                            iso_now(),
                            iso_now(),
                        ),
                    )
                result = handler(tx, job.payload)
                tx.execute(
                    "INSERT OR IGNORE INTO applied_writes(op_id, kind, applied_at) VALUES (?,?,?)",
                    (job.op_id, job.kind, iso_now()),
                )
                tx.execute(
                    "UPDATE write_journal SET state='committed', result=?, updated_at=? WHERE op_id=?",
                    (json_text(result) if result is not None else None, iso_now(), job.op_id),
                )
            # Only here, after COMMIT returned, may we report success.
            return WriteReceipt(outcome=WriteOutcome.COMMITTED, op_id=job.op_id, kind=job.kind, value=result)

    # -- durable two-phase ----------------------------------------------
    def begin_durable(self, kind: str, payload: dict[str, Any], *, op_id: str | None = None) -> str:
        if kind not in self._handlers:
            raise StorageError(f"no handler registered for write kind {kind!r}")
        op = op_id or new_id("op_")
        with self._write_lock, self.store.write_tx() as tx:
            tx.execute(
                "INSERT INTO write_journal(op_id, kind, seq, state, payload, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (op, kind, self._next_seq(tx), "intent", json_text(payload), iso_now(), iso_now()),
            )
        return op

    def complete_durable(self, op_id: str) -> WriteReceipt:
        row = self.store.query_one("SELECT kind, payload, state FROM write_journal WHERE op_id=?", (op_id,))
        if row is None:
            raise StorageError(f"unknown durable operation {op_id}")
        job = _Job(op_id=op_id, kind=row["kind"], payload=json.loads(row["payload"]), two_phase=True)
        return self._process(job)

    # -- recovery --------------------------------------------------------
    def replay(self) -> int:
        """Re-apply intent rows that never completed (crash between phases)."""
        rows = self.store.query(
            "SELECT j.op_id, j.kind, j.payload FROM write_journal j"
            " LEFT JOIN applied_writes a ON a.op_id = j.op_id"
            " WHERE j.state IN ('intent','pending') AND a.op_id IS NULL ORDER BY j.seq"
        )
        replayed = 0
        for row in rows:
            if row["kind"] not in self._handlers:
                continue
            job = _Job(op_id=row["op_id"], kind=row["kind"], payload=json.loads(row["payload"]), two_phase=True)
            receipt = self._process(job)
            if receipt.outcome.is_success:
                replayed += 1
        self.stats.replayed += replayed
        return replayed

    def journal(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.query(
            "SELECT op_id, kind, seq, state, attempts, created_at, updated_at FROM write_journal"
            " ORDER BY seq DESC LIMIT ?",
            (limit,),
        )

    def applied_count(self) -> int:
        return int(self.store.scalar("SELECT COUNT(*) FROM applied_writes") or 0)


class _Retry(Exception):
    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error = error


def _decode(value: Any) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):  # pragma: no cover - defensive
        return value


__all__ = ["WriteCoordinator", "CoordinatorStats", "JOURNAL_MIGRATIONS"]
