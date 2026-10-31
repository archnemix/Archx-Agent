"""Input validation and decoding for task history."""

from __future__ import annotations

import json
from typing import Any

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.managers.tasks.constants import TASK_TYPES


def _validate_type(kind: str) -> str:
    value = (kind or "").strip()
    if value not in TASK_TYPES:
        raise ValidationError(
            f"unknown task type {kind!r} (known: {', '.join(TASK_TYPES)})"
        )
    return value


def _title(text: str | None, fallback: str) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        cleaned = fallback
    return cleaned[:200]


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):  # pragma: no cover - defensive
        return default
