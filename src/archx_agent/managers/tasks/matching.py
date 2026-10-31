"""Lexical matching for task history."""

from __future__ import annotations


def _terms(query: str) -> list[str]:
    """Lower-cased search terms, longest first, capped so a paragraph cannot explode."""
    words = [word.strip(".,;:!?()[]{}'\"").lower() for word in (query or "").split()]
    terms = [word for word in words if len(word) >= 2]
    return sorted(set(terms), key=len, reverse=True)[:8]
