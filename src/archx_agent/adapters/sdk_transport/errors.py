"""Vendor error classification for vendor SDK transport."""

from __future__ import annotations

import re

from archx_agent.helpers.exceptions import (
    AuthDeniedError,
    InvalidRequestError,
    ModelNotFoundError,
    NetworkFailureError,
    ProviderError,
    ProviderOutageError,
    QuotaExhaustedError,
    RateLimitedError,
)
from archx_agent.helpers.redaction import redact


_QUOTA_WORDS = (
    "quota",
    "billing",
    "credit",
    "insufficient",
    "payment",
    "plan limit",
    "exceeded your current",
)

_STATUS_IN_TEXT = re.compile(
    r"(?i)(?:\bstatus\b|\bhttp\b|\bcode\b)[^0-9]{0,4}([45]\d\d)|^\s*([45]\d\d)\b"
)


def _status_of(exc: BaseException) -> int | None:
    """The HTTP status behind a vendor exception, however that vendor reports it.

    Clients disagree here: OpenAI and Anthropic set ``status_code``, `google-genai` raises a
    ``ClientError`` whose text starts with ``401 None.``, and `mistralai` wraps the status in a
    sentence (``API error occurred: Status 401``). Guessing from the class name alone threw away
    the one fact that distinguishes "bad key" from "server is down", so the text is read too.
    """
    for attribute in ("status_code", "status", "http_status", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    response = getattr(exc, "response", None)
    for attribute in ("status_code", "status"):
        code = getattr(response, attribute, None)
        if isinstance(code, int) and 100 <= code <= 599:
            return code
    match = _STATUS_IN_TEXT.search(str(exc) or "")
    if match:
        return int(match.group(1) or match.group(2))
    return None


def classify_sdk_error(
    exc: BaseException, *, key: str = "", provider: str = ""
) -> ProviderError:
    """Map a vendor SDK exception onto the domain taxonomy.

    Vendors differ in class names and in whether they carry a status code, so both are
    consulted; when they disagree the name wins (it is the more specific statement).
    """
    name = type(exc).__name__
    status = _status_of(exc)
    message = str(exc) or name
    if key:
        message = message.replace(key, "[REDACTED]")
    message = redact(message)
    lower = f"{name} {message}".lower()
    detail = {"sdk_error": name, "status": status}

    if status in (401, 403) or any(
        word in lower
        for word in (
            "authentication",
            "permissiondenied",
            "unauthorized",
            "invalid api key",
            "api key not valid",
        )
    ):
        return AuthDeniedError(
            f"authentication failed: {message}", provider=provider, **detail
        )
    if "notfound" in lower or status == 404:
        return ModelNotFoundError(
            f"model not found: {message}", provider=provider, **detail
        )
    if "ratelimit" in lower or status == 429:
        # Same trap as the raw Gemini client: a 429 can be a burst limit or a spent plan, and
        # telling a user to buy capacity over a burst limit costs them money.
        if any(word in lower for word in _QUOTA_WORDS):
            return QuotaExhaustedError(
                f"entitlement problem: {message}", provider=provider, **detail
            )
        return RateLimitedError(f"rate limited: {message}", provider=provider, **detail)
    if (
        any(
            word in lower
            for word in (
                "internal server",
                "overloaded",
                "serviceunavailable",
                "servererror",
            )
        )
        or (status or 0) >= 500
    ):
        return ProviderOutageError(
            f"provider unavailable: {message}", provider=provider, **detail
        )
    if any(word in lower for word in ("connection", "timeout", "timed out", "network")):
        return NetworkFailureError(
            f"could not reach the provider: {message}", provider=provider, **detail
        )
    if (
        any(
            word in lower
            for word in (
                "badrequest",
                "invalidrequest",
                "unprocessable",
                "invalidargument",
            )
        )
        or status == 400
    ):
        return InvalidRequestError(
            f"the provider rejected the request: {message}", provider=provider, **detail
        )
    return ProviderError(
        f"the provider call failed: {message}", provider=provider, **detail
    )
