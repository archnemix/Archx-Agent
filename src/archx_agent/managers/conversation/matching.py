"""ConversationManager matching."""

from __future__ import annotations


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _excerpt(content: str, query: str, *, width: int = 120) -> str:
    lower = content.lower()
    idx = lower.find(query.lower())
    if idx < 0:
        return content[:width]
    start = max(0, idx - width // 3)
    end = min(len(content), start + width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    return f"{prefix}{content[start:end]}{suffix}"
