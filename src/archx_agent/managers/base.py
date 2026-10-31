"""Shared manager plumbing.

A manager owns one domain capability, its tables and its write handlers. It
never opens a database connection: it receives the :class:`SqliteStore` (for
reads) and the shared :class:`WriteCoordinator` (for writes) from the
composition root.
"""

from __future__ import annotations

from typing import Any, Protocol

from archx_agent.helpers.events import EventStore
from archx_agent.helpers.sqlite_store import Migration, SqliteStore
from archx_agent.helpers.write_coordinator import WriteCoordinator


class TraceSink(Protocol):
    def record(self, kind: str, name: str, **kwargs: Any) -> str | None: ...


class BaseManager:
    """Base class for domain managers."""

    #: tables this manager owns, used for tests and diagnostics
    tables: tuple[str, ...] = ()

    def __init__(
        self,
        store: SqliteStore,
        coordinator: WriteCoordinator,
        *,
        events: EventStore | TraceSink | None = None,
    ) -> None:
        self.store = store
        self.coordinator = coordinator
        self.events = events
        self.register_handlers()

    # -- subclass hooks ---------------------------------------------------
    def register_handlers(self) -> None:  # pragma: no cover - overridden
        """Register write kinds with the coordinator."""

    # -- helpers ----------------------------------------------------------
    def trace(self, kind: str, name: str, **kwargs: Any) -> str | None:
        if self.events is None:
            return None
        try:
            return self.events.record(kind, name, **kwargs)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - tracing must never break a workflow
            return None

    def _write(self, kind: str, payload: dict[str, Any], *, op_id: str | None = None) -> Any:
        receipt = self.coordinator.submit(kind, payload, op_id=op_id)
        return receipt.require()

    def table_count(self, table: str) -> int:
        return int(self.store.scalar(f'SELECT COUNT(*) FROM "{table}"') or 0)


def migrations_for(*migrations: Migration) -> list[Migration]:
    return list(migrations)


__all__ = ["BaseManager", "TraceSink", "migrations_for"]
