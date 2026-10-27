"""``Result[T]`` and ``WriteOutcome``.

Conventions
-----------
* Data-producing operations return ``Result``.
* Action-only operations return ``None`` (and raise on failure).
* Durable writes return :class:`WriteOutcome` (never "True" - a queued write is
  not a committed write).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Generic, Iterator, TypeVar, Union

T = TypeVar("T")
U = TypeVar("U")
E = TypeVar("E", bound=Exception)


class WriteOutcome(str, Enum):
    """Outcome of a durable write.

    ``COMMITTED`` - the transaction is on disk.
    ``DUPLICATE`` - an operation with the same id was already committed; the
        original result is returned and nothing was written twice.
    ``PENDING`` - accepted but not yet committed (backpressure / timeout).
        This is *not* success.
    ``FAILED`` - the write failed and was not committed.
    """

    COMMITTED = "committed"
    DUPLICATE = "duplicate"
    PENDING = "pending"
    FAILED = "failed"

    @property
    def is_success(self) -> bool:
        return self in (WriteOutcome.COMMITTED, WriteOutcome.DUPLICATE)


_MISSING: object = object()


class Result(Generic[T]):
    """A success-or-failure value. Use :func:`Ok` / :func:`Err` to build one."""

    __slots__ = ("_value", "_error")

    def __init__(self, *, value: object = _MISSING, error: object = _MISSING) -> None:
        if (value is _MISSING) == (error is _MISSING):
            raise ValueError("Result needs exactly one of value/error")
        self._value = value if value is not _MISSING else None
        self._error = error if error is not _MISSING else None

    # -- construction helpers -------------------------------------------
    @classmethod
    def ok(cls, value: T) -> "Result[T]":
        return cls(value=value)

    @classmethod
    def err(cls, error: Exception) -> "Result[T]":
        return cls(error=error)

    # -- state -----------------------------------------------------------
    @property
    def is_ok(self) -> bool:
        return self._error is None

    @property
    def is_err(self) -> bool:
        return self._error is not None

    # -- access ----------------------------------------------------------
    @property
    def value(self) -> T:
        if self._error is not None:
            raise self._error
        return self._value  # type: ignore[return-value]

    @property
    def error(self) -> Exception:
        if self._error is None:
            raise RuntimeError("Result has no error")
        return self._error

    def unwrap(self) -> T:
        return self.value

    def unwrap_or(self, default: T) -> T:
        return self._value if self._error is None else default

    def unwrap_err(self) -> Exception:
        return self.error

    def ok_or_raise(self) -> T:
        if self._error is not None:
            raise self._error
        return self._value  # type: ignore[return-value]

    # -- transformations -------------------------------------------------
    def map(self, fn: Callable[[T], U]) -> "Result[U]":
        if self._error is not None:
            return Result(error=self._error)
        try:
            return Result.ok(fn(self._value))  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - converted into Err deliberately
            return Result.err(exc)

    def map_err(self, fn: Callable[[Exception], Exception]) -> "Result[T]":
        if self._error is None:
            return Result.ok(self._value)  # type: ignore[arg-type]
        return Result.err(fn(self._error))

    def bind(self, fn: "Callable[[T], Result[U]]") -> "Result[U]":
        if self._error is not None:
            return Result(error=self._error)
        try:
            return fn(self._value)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            return Result.err(exc)

    def iter(self) -> Iterator[T]:
        if self._error is None:
            yield self._value  # type: ignore[misc]

    # -- dunders ---------------------------------------------------------
    def __bool__(self) -> bool:
        return self._error is None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Result):
            return NotImplemented
        if self.is_ok and other.is_ok:
            return self._value == other._value
        if self.is_err and other.is_err:
            return type(self._error) is type(other._error) and str(self._error) == str(other._error)
        return False

    def __repr__(self) -> str:
        if self._error is not None:
            return f"Err({self._error!r})"
        return f"Ok({self._value!r})"


def Ok(value: T) -> Result[T]:  # noqa: N802 - factory style
    return Result.ok(value)


def Err(error: Exception) -> Result[T]:  # noqa: N802
    return Result.err(error)


@dataclass(frozen=True)
class WriteReceipt(Generic[T]):
    """Receipt returned by :class:`~archx_agent.helpers.write_coordinator.WriteCoordinator`."""

    outcome: WriteOutcome
    op_id: str
    kind: str
    value: T | None = None
    error: Exception | None = None
    replayed: bool = False

    @property
    def committed(self) -> bool:
        return self.outcome is WriteOutcome.COMMITTED

    @property
    def duplicate(self) -> bool:
        return self.outcome is WriteOutcome.DUPLICATE

    def require(self) -> T:
        if self.error is not None:
            raise self.error
        if not self.outcome.is_success:
            from .exceptions import StorageError

            raise StorageError(f"write {self.kind} not committed (outcome={self.outcome.value})", op_id=self.op_id)
        return self.value  # type: ignore[return-value]


__all__ = ["Result", "Ok", "Err", "WriteOutcome", "WriteReceipt"]
