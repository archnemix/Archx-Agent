"""Provider identifier normalization for provider metadata."""

from __future__ import annotations

from archx_agent.helpers.urls import is_loopback_url as is_loopback_url


def _slug(value: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in "-_" else "-" for ch in (value or "").lower()
    ).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:64] or "provider"
