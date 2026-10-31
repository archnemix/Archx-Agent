"""Lexical matching for workflow definitions."""

from __future__ import annotations


def _terms(query: str) -> list[str]:
    words = [word.strip(".,;:!?()[]{}'\"").lower() for word in (query or "").split()]
    terms = [word for word in words if len(word) >= 2]
    return sorted(set(terms), key=len, reverse=True)[:8]
