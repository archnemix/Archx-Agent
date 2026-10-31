"""Input validation and decoding for durable jobs."""

from __future__ import annotations

import json
from typing import Any

from archx_agent.helpers.exceptions import ValidationError


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return default


def _int(value: Any, name: str, *, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{name} must be an integer, got {value!r}")
    if not lo <= value <= hi:
        raise ValidationError(f"{name} must be between {lo} and {hi}, got {value}")
    return value
