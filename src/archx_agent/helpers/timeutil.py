"""Time-ordered identifiers and clocks.

Ordering rule: never order by timestamp when a sequence exists. This module
provides the sequence primitives; the database supplies monotonic sequence
columns (``seq INTEGER``) for ordering.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32 (no i/l/o/u)
_last_ms = -1
_counter = 0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_from_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def new_id(prefix: str = "") -> str:
    """Lexicographically sortable UUIDv7-style identifier.

    Monotonic within a process even when the wall clock steps backwards, which
    makes ids usable as an ordering tiebreaker (still not the primary order).
    """
    global _last_ms, _counter
    ms = int(time.time() * 1000)
    if ms <= _last_ms:
        ms = _last_ms
        _counter += 1
    else:
        _counter = 0
        _last_ms = ms
    packed = _encode(ms, 12) + _encode(_counter, 8) + os.urandom(8).hex()
    return f"{prefix}{packed}" if prefix else packed


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))


def short_id(length: int = 8) -> str:
    return uuid.uuid4().hex[:length]


class Stopwatch:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self._start) * 1000, 3)

    def reset(self) -> None:
        self._start = time.perf_counter()

    def __enter__(self) -> "Stopwatch":
        self.reset()
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = self.elapsed_ms()


__all__ = ["utc_now", "iso_now", "iso_from_ts", "parse_iso", "new_id", "short_id", "Stopwatch"]
