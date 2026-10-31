"""HttpChatRuntime error payloads."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _safe_body(exc: urllib.error.HTTPError) -> dict[str, Any] | str:
    try:
        raw = exc.read()
    except Exception:  # noqa: BLE001
        return ""
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return raw.decode("utf-8", "replace")[:1000]


def _extract_error_message(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or error)
        if isinstance(error, str):
            return error
        if payload.get("message"):
            return str(payload["message"])
        return json.dumps(payload)[:300]
    return str(payload)[:300]
