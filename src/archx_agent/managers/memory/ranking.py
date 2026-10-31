"""Ranking operations for memory governance."""

from __future__ import annotations

import re
from datetime import datetime

from archx_agent.helpers.timeutil import parse_iso
from archx_agent.managers.memory.constants import _STOPWORDS, _WORD_RE


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def tokens_of(text: str) -> set[str]:
    return {
        w.lower() for w in _WORD_RE.findall(text or "") if w.lower() not in _STOPWORDS
    }


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(a: set[str], b: set[str]) -> float:
    """Similarity used for duplicate detection.

    ``max(jaccard, containment)`` so that a short memory and a longer memory
    that fully contains it are still recognised as duplicates - short texts
    make plain Jaccard too lenient.
    """
    if not a or not b:
        return 0.0
    containment = len(a & b) / min(len(a), len(b))
    return max(jaccard(a, b), containment)


def _strip_like(value: str) -> str:
    return value.replace("\\", "").replace("%", "").replace("_", "")


def _is_expired(expires_at: str, now: datetime) -> bool:
    try:
        return parse_iso(expires_at) < now
    except ValueError:  # pragma: no cover - defensive
        return False
