"""GUI HTTP values, route metadata, validation and error-to-status mapping."""

from __future__ import annotations


import json


import re


from dataclasses import dataclass, field


from pathlib import Path


from typing import Any, Callable, Iterable


from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ArchxError,
    AuthDeniedError,
    ConflictError,
    ConsentRequiredError,
    ContextOverflowError,
    DuplicateError,
    LocalRuntimeFailureError,
    MalformedOutputError,
    ModelNotFoundError,
    ModelUnavailableError,
    NetworkFailureError,
    NotFoundError,
    PermissionDeniedError,
    PrivacyUnknownError,
    ProviderOutageError,
    QuotaExhaustedError,
    RateLimitedError,
    StorageBusyError,
    ToolNotFoundError,
    ToolTimeoutError,
    UnsupportedCapabilityError,
    ValidationError,
)


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from archx_agent.interfaces.gui.server import GuiApi

ASSETS = Path(__file__).with_name("assets")


COOKIE_NAME = "archx_gui"


CSRF_HEADER = "x-archx-request"


CSRF_VALUE = "gui"


TOKEN_PARAM = "token"


_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # The GUI does no network I/O of its own beyond this origin, loads no font or script from
    # anywhere else, and may be framed (the desktop preview frames it). There is no
    # frame-ancestors restriction for that reason, and no X-Frame-Options at all.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors *"
    ),
}


_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
}


class ApiError(Exception):
    """A failure with an HTTP status and a code the UI can act on."""

    def __init__(
        self, status: int, code: str, message: str, *, data: Any = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.data = data


_STATUS_FOR_ERROR: tuple[tuple[type, int, str], ...] = (
    (ValidationError, 400, "validation"),
    (ModelNotFoundError, 404, "model_not_found"),
    (ToolNotFoundError, 404, "tool_not_found"),
    (NotFoundError, 404, "not_found"),
    (DuplicateError, 409, "conflict"),
    (ConflictError, 409, "conflict"),
    (ConsentRequiredError, 403, "consent_required"),
    (PrivacyUnknownError, 403, "privacy_unknown"),
    (ApprovalRequiredError, 403, "approval_required"),
    (AuthDeniedError, 403, "auth_denied"),
    (PermissionDeniedError, 403, "permission_denied"),
    (QuotaExhaustedError, 402, "quota_exhausted"),
    (RateLimitedError, 429, "rate_limited"),
    (ProviderOutageError, 503, "provider_outage"),
    (NetworkFailureError, 502, "network_failure"),
    (ModelUnavailableError, 409, "model_unavailable"),
    (UnsupportedCapabilityError, 422, "unsupported_capability"),
    (LocalRuntimeFailureError, 503, "runtime_failure"),
    (MalformedOutputError, 502, "malformed_output"),
    (ContextOverflowError, 413, "context_overflow"),
    (StorageBusyError, 503, "storage_busy"),
    (ToolTimeoutError, 504, "tool_timeout"),
)


def error_for(exc: BaseException) -> ApiError:
    """Map a domain error to an HTTP status, without leaking a traceback."""
    for kind, status, code in _STATUS_FOR_ERROR:
        if isinstance(exc, kind):
            return ApiError(status, code, getattr(exc, "message", str(exc)))
    if isinstance(exc, ArchxError):
        return ApiError(500, "internal", getattr(exc, "message", str(exc)))
    return ApiError(500, "internal", f"{type(exc).__name__}: {exc}")


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    token: str | None = None
    via_cookie: bool = False
    remote: str = "127.0.0.1"
    token_in_query: bool = False

    def q(self, name: str, default: str | None = None) -> str | None:
        values = self.query.get(name) or []
        return values[0] if values else default

    def q_int(self, name: str, default: int, *, lo: int = 1, hi: int = 200) -> int:
        raw = self.q(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise ApiError(400, "validation", f"{name} must be an integer") from exc
        if value < lo or value > hi:
            raise ApiError(400, "validation", f"{name} must be between {lo} and {hi}")
        return value

    def q_bool(self, name: str, default: bool = False) -> bool:
        raw = self.q(name)
        if raw is None or raw == "":
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def payload(self) -> dict[str, Any]:
        if self.body is None:
            return {}
        if not isinstance(self.body, dict):
            raise ApiError(400, "validation", "the request body must be a JSON object")
        return self.body

    def field(self, name: str, *, required: bool = False, default: Any = None) -> Any:
        value = self.payload().get(name, default)
        if required and (
            value is None or (isinstance(value, str) and not value.strip())
        ):
            raise ApiError(400, "validation", f"{name} is required")
        return value

    def text(
        self, name: str, *, required: bool = False, default: str | None = None
    ) -> str | None:
        """A string field, and only a string.

        ``str(request.field(...))`` accepts anything: a dict became its Python repr, which then
        reached a model and the database as if a user had typed it. A client sending the wrong
        type is a 400, not a coercion.
        """
        value = self.field(name, required=required, default=default)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ApiError(400, "validation", f"{name} must be a string")
        value = value.strip()
        if required and not value:
            raise ApiError(400, "validation", f"{name} is required")
        return value

    def identifier(self, name: str) -> str | None:
        """An id field: a string or nothing. Ids are never numbers, lists or objects."""
        value = self.field(name)
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ApiError(400, "validation", f"{name} must be a string")
        return value.strip() or None


@dataclass
class Response:
    status: int = 200
    payload: Any = None
    body: bytes | None = None
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)

    def encode(self) -> bytes:
        if self.body is not None:
            return self.body
        return json.dumps(self.payload, default=str).encode("utf-8")


@dataclass
class SSEStream:
    """A response with no length: frames are written as they are produced.

    Server-sent events, because a chat reply arrives over time and the browser has to see each
    piece as it comes. No ``Content-Length`` means the connection is closed to end the stream,
    so the handler must also send ``Connection: close``.
    """

    frames: Iterable[str]
    content_type: str = "text/event-stream; charset=utf-8"


@dataclass
class Route:
    method: str
    pattern: re.Pattern[str]
    handler: Callable[["GuiApi", Request, re.Match[str]], Any]
    doc: str


def route(method: str, path: str, doc: str) -> Callable[[Callable], Callable]:
    """Register a handler. ``path`` uses ``{name}`` captures and is anchored."""

    pattern = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path) + "$")

    def wrap(fn: Callable[[GuiApi, Request, re.Match[str]], Any]) -> Callable:
        fn._route = Route(method.upper(), pattern, fn, doc)  # type: ignore[attr-defined]
        return fn

    return wrap


def _positive_int(
    request: Request, name: str, default: int | None = None
) -> int | None:
    """A payload number, or a 400. A string where a count belongs must not become one."""
    raw = request.payload().get(name)
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ApiError(400, "validation", f"{name} must be a positive integer")
    return raw
