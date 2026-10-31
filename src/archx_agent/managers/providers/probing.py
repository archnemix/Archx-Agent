"""Provider endpoint probes for provider metadata."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from archx_agent.helpers.urls import is_loopback_url as is_loopback_url
from archx_agent.managers.providers.records import Provider


def probe_provider(provider: Provider, *, timeout: float = 4.0) -> dict[str, Any]:
    """Reachability/auth probe. Returns a status dict; never raises for network errors."""
    if not provider.base_url:
        return {
            "status": "unreachable",
            "latency_ms": None,
            "detail": "no base_url configured",
            "models_seen": None,
        }
    url = provider.base_url.rstrip("/")
    path = "/models"
    if provider.api_style == "anthropic":
        path = "/v1/models"
    elif provider.api_style == "gemini":
        path = "/v1beta/models"
    target = url + path
    headers = {"Accept": "application/json", "User-Agent": "archx-agent/probe"}
    if provider.auth_ref:
        try:
            from archx_agent.helpers.config import resolve_secret

            value = resolve_secret(provider.auth_ref)
            if provider.api_style == "anthropic":
                headers["x-api-key"] = value
                headers["anthropic-version"] = "2023-06-01"
            elif provider.api_style == "gemini":
                headers["x-goog-api-key"] = value
            else:
                headers["Authorization"] = f"Bearer {value}"
        except Exception as exc:  # noqa: BLE001 - a missing secret is a check result
            return {
                "status": "auth_failed",
                "latency_ms": None,
                "detail": f"cannot resolve secret: {exc}",
                "models_seen": None,
            }
    started = time.monotonic()
    try:
        request = urllib.request.Request(target, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - http(s) validated
            body = response.read(200_000).decode("utf-8", "replace")
            latency = (time.monotonic() - started) * 1000.0
            models = _count_models(body)
            return {
                "status": "reachable",
                "latency_ms": round(latency, 1),
                "detail": f"HTTP {response.status}",
                "models_seen": models,
            }
    except urllib.error.HTTPError as exc:
        latency = (time.monotonic() - started) * 1000.0
        status = "reachable"
        if exc.code in (401, 403):
            status = "auth_failed"
        elif exc.code == 404:
            status = "model_missing"
        elif exc.code == 429:
            status = "rate_limited"
        elif exc.code >= 500:
            status = "unreachable"
        return {
            "status": status,
            "latency_ms": round(latency, 1),
            "detail": f"HTTP {exc.code}",
            "models_seen": None,
        }
    except (
        urllib.error.URLError,
        socket.timeout,
        TimeoutError,
        ConnectionError,
        OSError,
    ) as exc:
        latency = (time.monotonic() - started) * 1000.0
        reason = getattr(exc, "reason", exc)
        return {
            "status": "unreachable",
            "latency_ms": round(latency, 1),
            "detail": f"{type(exc).__name__}: {reason}",
            "models_seen": None,
        }


def _count_models(body: str) -> int | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    for key in ("data", "models"):
        if isinstance(payload.get(key), list):
            return len(payload[key])
    return None
