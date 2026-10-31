"""SDK signature and response compatibility for vendor SDK transport."""

from __future__ import annotations

import inspect
from typing import Any


def _accepts(callable_obj: Any, name: str) -> bool:
    """Does this SDK call take ``name``?

    Vendors move parameters between releases (``anthropic`` 2.x dropped ``temperature`` from
    ``messages.create``; OpenAI grew ``max_completion_tokens`` beside ``max_tokens``). Passing a
    parameter a client does not accept is a TypeError instead of a request, and dropping one it
    wants is a silently different temperature - so ask, and send what is accepted.
    """
    try:
        parameters = inspect.signature(callable_obj).parameters
    except (
        TypeError,
        ValueError,
    ):  # builtins and C extensions do not expose a signature
        return True
    if name in parameters:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())


def _supported(callable_obj: Any, candidates: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in candidates.items() if _accepts(callable_obj, key)
    }


def _finish(value: Any) -> str:
    """Normalise a vendor finish/stop reason to Archx's three states."""
    text = str(getattr(value, "value", value) or "").lower()
    if not text or text in {"none", "stop", "end_turn", "stop_sequence", "eos"}:
        return "stop"
    if "max" in text or "length" in text:
        return "length"
    if (
        "safety" in text
        or "block" in text
        or "content_filter" in text
        or "refusal" in text
    ):
        return "safety"
    if "tool" in text or "function" in text:
        return "tool_calls"
    return "stop"
