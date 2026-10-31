"""LocalToolRuntime output."""

from __future__ import annotations


def _clip(raw: bytes | str, limit: int) -> tuple[str, bool]:
    if isinstance(raw, str):
        text = raw
        truncated = len(text.encode("utf-8")) > limit
        if truncated:
            text = text.encode("utf-8")[:limit].decode("utf-8", errors="replace")
        return text, truncated
    truncated = len(raw) > limit
    return raw[:limit].decode("utf-8", errors="replace"), truncated
