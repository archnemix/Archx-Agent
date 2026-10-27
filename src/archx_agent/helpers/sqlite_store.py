"""The **only** module allowed to import ``sqlite3``.

Everything else receives a :class:`Tx` (transaction wrapper) or a
:class:`SqliteStore` and never touches the driver directly. That single choke
point is what makes the crash/recovery and migration behaviour testable.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from .exceptions import SchemaVersionError, StorageBusyError, StorageCorruptError, StorageError
from .paths import ensure_directory

SUPPORTED_SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 10_000
_LOCK_RETRIES = 6


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise StorageError(f"migration version must be positive (got {self.version})")


class Tx:
    """Thin, driver-free transaction handle handed to write handlers."""

    __slots__ = ("_conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
        """Run a statement. Returns the new rowid for INSERT, else affected rows."""
        cur = self._conn.execute(sql, params)
        head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        if head in {"INSERT", "REPLACE"}:
            return int(cur.lastrowid) if cur.lastrowid is not None else cur.rowcount
        return int(cur.rowcount)

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        cur = self._conn.executemany(sql, rows)
        return cur.rowcount

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[dict[str, Any]]:
        cur = self._conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
        cur = self._conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def scalar(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any:
        cur = self._conn.execute(sql, params)
        row = cur.fetchone()
        return None if row is None else row[0]


def _is_locked(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


class SqliteStore:
    """A SQLite database file with connections, migrations and helpers."""

    def __init__(self, path: str | os.PathLike[str], *, wal: bool = True) -> None:
        self.path = Path(path).expanduser()
        ensure_directory(self.path.parent)
        self._wal = wal
        self._local = threading.local()
        self._all_conns: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

    # -- connections -----------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(str(self.path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        except sqlite3.Error as exc:  # pragma: no cover - hard failure
            raise StorageError(f"cannot open database {self.path}: {exc}") from exc
        conn.row_factory = sqlite3.Row
        # pragma: no cover - pragma failures are environment-specific
        with contextlib.suppress(sqlite3.Error):
            if self._wal:
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA trusted_schema=OFF")
        with self._lock:
            self._all_conns.append(conn)
        return conn

    def thread_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    @contextlib.contextmanager
    def read(self) -> Iterator[Tx]:
        try:
            yield Tx(self.thread_conn())
        except sqlite3.DatabaseError as exc:
            raise _wrap_db_error(exc, self.path) from exc

    @contextlib.contextmanager
    def write_tx(self, *, immediate: bool = True) -> Iterator[Tx]:
        """Serialised write transaction with bounded retries on lock contention."""
        conn = self.thread_conn()
        last: sqlite3.OperationalError | None = None
        for attempt in range(_LOCK_RETRIES):
            try:
                conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            except sqlite3.OperationalError as exc:
                if _is_locked(exc):
                    last = exc
                    time.sleep(min(0.05 * (2**attempt), 1.0) * (0.5 + os.urandom(1)[0] / 255))
                    continue
                raise StorageError(f"begin failed: {exc}") from exc
            try:
                tx = Tx(conn)
                yield tx
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                raise
            else:
                try:
                    conn.execute("COMMIT")
                except sqlite3.OperationalError as exc:
                    with contextlib.suppress(sqlite3.Error):
                        conn.execute("ROLLBACK")
                    if _is_locked(exc):
                        last = exc
                        time.sleep(0.05 * (2**attempt))
                        continue
                    raise StorageError(f"commit failed: {exc}") from exc
                return
        raise StorageBusyError(f"database busy after {_LOCK_RETRIES} attempts", path=str(self.path))

    # -- convenience -----------------------------------------------------
    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[dict[str, Any]]:
        try:
            with self.read() as tx:
                return tx.query(sql, params)
        except sqlite3.DatabaseError as exc:
            raise _wrap_db_error(exc, self.path) from exc

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
        try:
            with self.read() as tx:
                return tx.query_one(sql, params)
        except sqlite3.DatabaseError as exc:
            raise _wrap_db_error(exc, self.path) from exc

    def scalar(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any:
        try:
            with self.read() as tx:
                return tx.scalar(sql, params)
        except sqlite3.DatabaseError as exc:
            raise _wrap_db_error(exc, self.path) from exc

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
        with self.write_tx() as tx:
            return tx.execute(sql, params)

    def table_exists(self, name: str) -> bool:
        row = self.query_one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
        return row is not None

    # -- schema ----------------------------------------------------------
    def schema_version(self) -> int:
        if not self.table_exists("schema_migrations"):
            return 0
        return int(self.scalar("SELECT COALESCE(MAX(version), 0) FROM schema_migrations") or 0)

    def migrate(self, migrations: Sequence[Migration], *, before_upgrade: Callable[[], Any] | None = None) -> int:
        """Apply pending migrations in order. Returns the resulting version."""
        current = self.schema_version()
        supported = max((m.version for m in migrations), default=SUPPORTED_SCHEMA_VERSION)
        if current > supported:
            raise SchemaVersionError(
                f"database schema version {current} is newer than this build supports "
                f"({supported}); upgrade Archx Agent instead of downgrading data",
                path=str(self.path),
            )
        pending = [m for m in sorted(migrations, key=lambda m: m.version) if m.version > current]
        if not pending:
            return current
        if current > 0 and before_upgrade is not None:
            before_upgrade()
        with self.write_tx() as tx:
            tx.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
        for migration in pending:
            try:
                with self.write_tx() as tx:
                    for stmt in migration.statements:
                        tx.execute(stmt)
                    tx.execute(
                        "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?,?,?)",
                        (migration.version, migration.name, _now()),
                    )
            except sqlite3.Error as exc:
                raise StorageError(
                    f"migration {migration.version} ({migration.name}) failed: {exc}", path=str(self.path)
                ) from exc
        return self.schema_version()

    # -- health ----------------------------------------------------------
    def integrity_check(self) -> list[str]:
        try:
            rows = self.query("PRAGMA integrity_check")
        except sqlite3.DatabaseError as exc:
            raise StorageCorruptError(f"integrity check failed: {exc}", path=str(self.path)) from exc
        return [str(list(r.values())[0]) for r in rows]

    def foreign_key_check(self) -> list[dict[str, Any]]:
        return self.query("PRAGMA foreign_key_check")

    def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            name = row["name"]
            if name.startswith("sqlite_"):
                continue
            try:
                counts[name] = int(self.scalar(f'SELECT COUNT(*) FROM "{name}"') or 0)
            except StorageError:  # pragma: no cover - virtual tables
                counts[name] = -1
        return counts

    def backup_to(self, destination: str | os.PathLike[str]) -> Path:
        dest = Path(destination).expanduser()
        ensure_directory(dest.parent)
        src = self.thread_conn()
        target_conn = sqlite3.connect(str(dest))
        try:
            with target_conn:
                src.backup(target_conn)
        except sqlite3.Error as exc:
            raise StorageError(f"backup failed: {exc}", path=str(dest)) from exc
        finally:
            target_conn.close()
        return dest

    def vacuum(self) -> None:
        self.thread_conn().execute("VACUUM")

    def checkpoint(self) -> None:
        with contextlib.suppress(sqlite3.Error):
            self.thread_conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self) -> None:
        with self._lock:
            conns = list(self._all_conns)
            self._all_conns.clear()
        for conn in conns:
            with contextlib.suppress(sqlite3.Error):
                conn.close()
        if hasattr(self._local, "conn"):
            del self._local.conn

    # -- testing / fault injection --------------------------------------
    def inject_corruption(self, *, table: str = "sqlite_master") -> None:  # pragma: no cover - test helper
        """Corrupt the file on disk (used by storage recovery tests)."""
        self.close()
        with open(self.path, "r+b") as fh:
            fh.seek(0)
            fh.write(b"\xff" * 400)


_CORRUPT_MARKERS = ("not a database", "malformed", "file is encrypted", "database disk image is malformed")


def _wrap_db_error(exc: sqlite3.Error, path: Path, *, prefix: str = "") -> StorageError:
    message = str(exc)
    lower = message.lower()
    label = f"{prefix}: " if prefix else ""
    if any(marker in lower for marker in _CORRUPT_MARKERS):
        return StorageCorruptError(
            f"{label}{path} is not a valid Archx database ({message}); restore a backup",
            path=str(path),
        )
    if "locked" in lower or "busy" in lower:
        return StorageBusyError(f"{label}{path} is locked by another process ({message})", path=str(path))
    return StorageError(f"{label}database error in {path}: {message}", path=str(path))


def _now() -> str:
    from .timeutil import iso_now

    return iso_now()


def open_store(path: str | os.PathLike[str], migrations: Sequence[Migration] = ()) -> SqliteStore:
    store = SqliteStore(path)
    if migrations:
        store.migrate(migrations)
    else:
        store.query("SELECT 1")
    return store


__all__ = ["SqliteStore", "Tx", "Migration", "open_store", "SUPPORTED_SCHEMA_VERSION"]
