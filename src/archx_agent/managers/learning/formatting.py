"""Feature-specific formatting for learning records."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from archx_agent.helpers.timeutil import iso_from_ts, iso_now, parse_iso


def _json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _norm(text: str) -> str:
    """Whitespace-collapsed, case-folded, punctuation-insensitive comparison form."""
    out = []
    for char in (text or "").strip().lower():
        if char.isalnum() or char.isspace():
            out.append(char)
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def due_in(days: float, *, start: str | None = None) -> str:
    """An ISO timestamp ``days`` from ``start`` (or now) - the schedule's own arithmetic."""
    moment = parse_iso(start) if start else parse_iso(iso_now())
    return iso_from_ts((moment + timedelta(days=days)).timestamp())
