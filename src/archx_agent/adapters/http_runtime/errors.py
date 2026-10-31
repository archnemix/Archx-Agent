"""HttpChatRuntime errors."""

from __future__ import annotations

import json
from typing import Any

from archx_agent.helpers.exceptions import (
    AuthDeniedError,
    EntitlementError,
    InvalidRequestError,
    ModelNotFoundError,
    ProviderError,
    ProviderOutageError,
    QuotaExhaustedError,
    RateLimitedError,
    ResourceExhaustedError,
    UnsupportedOperationError,
)
from archx_agent.adapters.http_runtime.error_payloads import _extract_error_message


class HttpChatRuntimeErrorsMixin:
    """Errors responsibility for HttpChatRuntime."""

    def _classify_http(
        self, status: int, payload: dict[str, Any] | str, url: str
    ) -> ProviderError:
        message = _extract_error_message(payload) or f"HTTP {status}"
        lower = str(message).lower()
        model = self.spec.model if self.spec else None
        common = {
            "provider": self.provider,
            "model": model or "",
            "status": status,
            "endpoint": url,
        }
        if status in (401, 403):
            return AuthDeniedError(f"authentication failed: {message}", **common)
        if status == 404:
            if "model" in lower:
                return ModelNotFoundError(f"model not found: {message}", **common)
            return InvalidRequestError(f"endpoint not found: {message}", **common)
        if status == 429:
            if any(
                word in json.dumps(payload).lower()
                for word in ("quota", "exceeded your current", "billing")
            ):
                return QuotaExhaustedError(f"quota exhausted: {message}", **common)
            return RateLimitedError(f"rate limited: {message}", **common)
        if status in (500, 502, 503, 504):
            return ProviderOutageError(f"provider unavailable: {message}", **common)
        if status == 402 or "insufficient" in lower or "billing" in lower:
            return EntitlementError(f"entitlement problem: {message}", **common)
        if status in (413, 507):
            return ResourceExhaustedError(f"resource limit: {message}", **common)
        if status == 422 or status == 400:
            if "context" in lower and ("length" in lower or "window" in lower):
                return InvalidRequestError(
                    f"context length exceeded: {message}", **common
                )
            return InvalidRequestError(f"invalid request: {message}", **common)
        if status == 405:
            return UnsupportedOperationError(
                f"operation not supported by this endpoint: {message}", **common
            )
        return ProviderError(f"HTTP {status}: {message}", **common)
