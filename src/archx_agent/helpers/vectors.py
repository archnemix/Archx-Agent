"""Float32 vector packing and similarity.

Vectors are stored as ``float32`` BLOBs with their dimension recorded next to
them. A vector is only comparable with vectors produced by the *same* model id
and dimension - comparing across models silently produces nonsense, so callers
must pass the model identity explicitly.
"""

from __future__ import annotations

import math
import struct
from array import array
from typing import Iterable, Sequence

from .exceptions import ValidationError

FLOAT32 = "f"
_STRUCT = struct.Struct("<f")


def pack(vector: Sequence[float]) -> bytes:
    """Pack a vector into little-endian float32 bytes."""
    if not vector:
        raise ValidationError("cannot pack an empty vector")
    values = array(FLOAT32, [float(v) for v in vector])
    if struct.pack("=f", 1.5) != _STRUCT.pack(1.5):  # pragma: no cover - big endian hosts
        values.byteswap()
    return values.tobytes()


def unpack(blob: bytes) -> list[float]:
    if not blob:
        raise ValidationError("cannot unpack an empty blob")
    if len(blob) % 4 != 0:
        raise ValidationError(f"vector blob length {len(blob)} is not a multiple of 4")
    values = array(FLOAT32)
    values.frombytes(blob)
    if struct.pack("=f", 1.5) != _STRUCT.pack(1.5):  # pragma: no cover - big endian hosts
        values.byteswap()
    return list(values)


def dimension(blob: bytes) -> int:
    return len(blob) // 4


def normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return [0.0 for _ in vector]
    return [v / norm for v in vector]


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValidationError(f"vector dimension mismatch: {len(a)} vs {len(b)}")
    return sum(x * y for x, y in zip(a, b))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValidationError(f"vector dimension mismatch: {len(a)} vs {len(b)}")
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot(a, b) / (na * nb)


def top_k(
    query: Sequence[float],
    candidates: Iterable[tuple[str, Sequence[float]]],
    *,
    k: int = 10,
    threshold: float | None = None,
) -> list[tuple[str, float]]:
    """Scan-and-score with an optional similarity floor.

    Brute force is deliberate: it is predictable, needs no index build, and is
    fast enough for the documented scale threshold (see ``docs/RETRIEVAL.md``).
    """
    scored: list[tuple[str, float]] = []
    for item_id, vector in candidates:
        if len(vector) != len(query):
            continue  # vectors from a different model are not comparable
        score = cosine(query, vector)
        if threshold is None or score >= threshold:
            scored.append((item_id, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored[: max(0, k)]


def byte_size(dim: int) -> int:
    return dim * 4


__all__ = ["pack", "unpack", "dimension", "normalize", "dot", "cosine", "top_k", "byte_size"]
