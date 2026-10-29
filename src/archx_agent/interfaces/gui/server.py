"""The local web GUI (M29).

The GUI is a *client of the application layer*, served from this process. It is not a
second application: every control in it calls the same managers, the same chat service,
the same permission centre and the same research runner as the CLI. Nothing here decides
anything the CLI would not decide, and nothing here is a placeholder.

Two boundaries matter more than the HTML:

**Reachability.** The server binds loopback by default. ``--allow-remote`` exists for a
container, a preview or a phone on the same network, and it is a deliberate act: the token
is then the only thing standing between a stranger and your data.

**Authentication.** A random token is minted per process and printed with the URL. It can be
presented as ``?token=``, ``Authorization: Bearer``, ``X-Archx-Token``, or exchanged for an
HttpOnly ``SameSite=Strict`` cookie at ``POST /api/session``. Cookie-authenticated writes
must also carry ``X-Archx-Request: gui``; a cross-site page cannot set a custom header
without a CORS preflight, and this server never answers one.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import json
import re
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import parse_qs, unquote, urlsplit

from archx_agent import __version__
from archx_agent.application import games as games_module
from archx_agent.application.learning import HintBeforeAttempt, NothingToStudy
from archx_agent.application.researcher import ResearchBlocked
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
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now
from archx_agent.adapters.sdk_transport import SDKS, sdk_available
from archx_agent.managers.providers import is_loopback_url
from archx_agent.managers.training import METHODS

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

    def __init__(self, status: int, code: str, message: str, *, data: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.data = data


#: Most specific first: the first matching class wins, so `DuplicateError` must appear before
#: `ConflictError` and `ToolNotFoundError` before the generic provider mapping.
#:
#: The provider rows matter more than they look. `ModelNotFoundError`, `AuthDeniedError` and the
#: rest inherit from `ProviderError`, not `NotFoundError`, so before this every one of them
#: became a 500 - a missing model was reported as the GUI's own internal failure. A missing model
#: is a 404, a refused key a 403, a spent quota a 402, an outage a 503.
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


# --------------------------------------------------------------------------
# request / response
# --------------------------------------------------------------------------
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
        if required and (value is None or (isinstance(value, str) and not value.strip())):
            raise ApiError(400, "validation", f"{name} is required")
        return value

    def text(self, name: str, *, required: bool = False, default: str | None = None) -> str | None:
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


# --------------------------------------------------------------------------
# the API
# --------------------------------------------------------------------------
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


class GuiApi:
    """Every GUI operation, with no sockets involved (so it is testable and reusable)."""

    def __init__(
        self,
        workspace,
        *,
        token: str | None = None,
        token_ttl_minutes: int = 720,
        allow_remote: bool = False,
        max_body_bytes: int = 1_048_576,
        max_auth_failures: int = 20,
    ) -> None:
        self.ws = workspace
        self.token = token or secrets.token_urlsafe(24)
        self.token_ttl_minutes = max(1, int(token_ttl_minutes))
        self.allow_remote = bool(allow_remote)
        self.max_body_bytes = max(1024, int(max_body_bytes))
        self.max_auth_failures = max(3, int(max_auth_failures))
        self.started_at = time.time()
        self.requests = 0
        self.auth_failures = 0
        self._opener: Any = None
        self._auth_window: list[float] = []
        self._lock = threading.Lock()

    # -- routes ---------------------------------------------------------
    def routes(self) -> list[Route]:
        found: list[Route] = []
        for name in dir(self):
            attr = getattr(self, name, None)
            definition = getattr(attr, "_route", None)
            if isinstance(definition, Route):
                found.append(definition)
        return sorted(found, key=lambda r: (r.pattern.pattern, r.method))

    # -- auth -----------------------------------------------------------
    def _cookie_value(self) -> str:
        """The cookie is derived from the token, so a leaked cookie is a leaked token.

        Deriving it means the browser never stores the token itself, and restarting the
        server invalidates every cookie (a new token is minted).
        """
        return hmac.new(self.token.encode(), b"archx-gui-session", hashlib.sha256).hexdigest()

    def open_session(self, token: str) -> Response:
        if not self._token_ok(token):
            self._record_auth_failure()
            raise ApiError(401, "unauthorized", "that token is not this session's token")
        cookie = (
            f"{COOKIE_NAME}={self._cookie_value()}; Path=/; HttpOnly; SameSite=Strict; "
            f"Max-Age={self.token_ttl_minutes * 60}"
        )
        return Response(
            payload={"ok": True, "expires_in": self.token_ttl_minutes * 60},
            headers={"Set-Cookie": cookie},
        )

    def _token_ok(self, candidate: str | None) -> bool:
        if not candidate:
            return False
        return hmac.compare_digest(candidate, self.token)

    def _record_auth_failure(self) -> None:
        now = time.time()
        with self._lock:
            self.auth_failures += 1
            self._auth_window = [stamp for stamp in self._auth_window if now - stamp < 60.0]
            self._auth_window.append(now)
            if len(self._auth_window) > self.max_auth_failures:
                raise ApiError(429, "too_many_attempts", "too many bad tokens; wait a minute")

    def _authenticate(self, request: Request) -> None:
        """Accept the token (header, bearer, query) or the cookie this server issued."""
        handle = request.headers.get("authorization", "")
        if handle.lower().startswith("bearer ") and self._token_ok(handle[7:].strip()):
            return
        if self._token_ok(request.headers.get("x-archx-token")):
            return
        if request.token is not None and self._token_ok(request.token):
            return
        cookie = SimpleCookie()
        try:
            cookie.load(request.headers.get("cookie", ""))
        except Exception:  # noqa: BLE001 - a malformed cookie is simply unauthenticated
            cookie = SimpleCookie()
        morsel = cookie.get(COOKIE_NAME)
        if morsel is not None and hmac.compare_digest(morsel.value, self._cookie_value()):
            request.via_cookie = True
            return
        self._record_auth_failure()
        raise ApiError(401, "unauthorized", "this GUI needs its access token")

    # -- dispatch -------------------------------------------------------
    def dispatch(self, request: Request) -> Response | SSEStream:
        with self._lock:
            self.requests += 1
        try:
            if request.method == "OPTIONS":
                raise ApiError(405, "no_cors", "this server does not answer CORS preflights")
            if request.path == "/api/health":
                # The one endpoint that answers without a token, so a monitor can ask if the
                # process is alive. It reports nothing but liveness, and it answers GET only -
                # a DELETE that returns a health payload is a routing accident, not a feature.
                # Refused before the CSRF check: there is no write here to protect, so the
                # honest answer is "this path does not take that verb", not "you forgot a
                # header". `HEAD` arrives as GET (the body is suppressed on the way out).
                if request.method != "GET":
                    raise ApiError(405, "method_not_allowed", "health answers GET")
                return Response(payload={"ok": True, "data": self.health()})
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                self._require_csrf(request)
            if request.path == "/api/session" and request.method == "POST":
                token = str(request.payload().get("token", ""))
                return self.open_session(token)
            self._authenticate(request)
            for definition in self.routes():
                if definition.method != request.method:
                    continue
                match = definition.pattern.match(request.path)
                if match is None:
                    continue
                result = definition.handler(self, request, match)
                if isinstance(result, (Response, SSEStream)):
                    return result
                if isinstance(result, (bytes, str)):
                    return Response(payload=result)
                return Response(payload={"ok": True, "data": result})
            raise ApiError(404, "no_route", f"no route for {request.method} {request.path}")
        except ApiError as exc:
            return self._error_response(exc)
        except BaseException as exc:  # noqa: BLE001 - every failure becomes JSON
            return self._error_response(error_for(exc))

    def _error_response(self, exc: ApiError) -> Response:
        return Response(
            status=exc.status,
            payload={
                "ok": False,
                "error": {"code": exc.code, "message": exc.message, "data": exc.data},
            },
        )

    @staticmethod
    def _require_csrf(request: Request) -> None:
        """On a cookie-authenticated write, demand a header a cross-site page cannot set."""
        header = request.headers.get(CSRF_HEADER, "")
        if header == CSRF_VALUE:
            return
        # A caller presenting the token itself (curl, the acceptance script) is not a
        # browser and cannot be tricked into a cross-site request by a page it visits.
        if request.headers.get("x-archx-token") or request.headers.get("authorization"):
            return
        # A request carrying no credential at all cannot be riding a session cookie, so CSRF
        # is the wrong refusal: there is nothing to forge yet. Fall through and let
        # authentication answer "you have not identified yourself", which is what happened.
        cookie = SimpleCookie()
        try:
            cookie.load(request.headers.get("cookie", ""))
        except Exception:  # noqa: BLE001 - a malformed cookie is simply not a credential
            cookie = SimpleCookie()
        if cookie.get(COOKIE_NAME) is None:
            return
        raise ApiError(
            403,
            "csrf",
            f"a write needs the {CSRF_HEADER}: {CSRF_VALUE} header",
        )

    # -- meta -----------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return {
            "app": "archx-agent",
            "version": __version__,
            "started_at": iso_now(),
            "uptime_seconds": round(time.time() - self.started_at, 3),
            "requests": self.requests,
            "auth": "token",
            "csrf_header": f"{CSRF_HEADER}: {CSRF_VALUE}",
        }

    @route("GET", "/api/status", "One screen: what this home holds, and what is blocked.")
    def get_status(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        info = self.ws.info()
        jobs = self.ws.jobs.stats() if self.ws.jobs is not None else {}
        approvals = self.ws.permissions.pending() if self.ws.permissions is not None else []
        models = self.ws.models.list()
        usable = [m for m in models if self.ws.runtime_availability(m)[0]]
        research = self.ws.research.stats() if self.ws.research is not None else {}
        return {
            **info,
            "version": __version__,
            "jobs": jobs,
            "approvals_pending": len(approvals),
            "models_total": len(models),
            "models_usable": len(usable),
            "research": research,
            "play": self.ws.play_mode.stats(),
            "media": self.ws.voice.stats(),
            "datasets": self.ws.data.stats(),
            "training": self.ws.trainer.stats(),
            "simulated_allowed": self.ws.allow_test_double,
            "net_fetch_granted": self._net_fetch_granted(),
        }

    def _net_fetch_granted(self) -> bool:
        if self.ws.permissions is None:
            return False
        return any(
            grant.capability == "net.fetch" and grant.active
            for grant in self.ws.permissions.grants(include_expired=False)
        )

    @route("GET", "/api/models", "The catalogue, with why each model can or cannot run here.")
    def get_models(self, request: Request, match: re.Match[str]) -> list[dict[str, Any]]:
        return [self._model_payload(record) for record in self.ws.models.list()]

    @route("GET", "/api/conversations", "Recent conversations.")
    def get_conversations(self, request: Request, match: re.Match[str]) -> list[dict[str, Any]]:
        limit = request.q_int("limit", 20)
        return [
            {
                "id": record.id,
                "title": record.title,
                "updated_at": record.updated_at,
                "created_at": record.created_at,
                "status": getattr(record, "status", "active"),
                "messages": getattr(record, "message_count", None),
            }
            for record in self.ws.conversations.list_conversations(limit=limit)
        ]

    # -- chat -----------------------------------------------------------
    @route("POST", "/api/chat", "One chat turn, recorded as a task exactly like the CLI's.")
    def post_chat(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        message = request.text("message", required=True) or ""
        if len(message) > 8000:
            raise ApiError(400, "validation", "a message must be at most 8000 characters")
        conversation_id = request.identifier("conversation_id")
        model_id = request.identifier("model_id")
        reply = self.ws.chat.send(message, conversation_id=conversation_id, model_id=model_id)
        payload = reply.to_dict()
        payload["simulated"] = bool(reply.simulated)
        return payload

    @route("POST", "/api/chat/stream", "The same chat turn, streamed as server-sent events.")
    def post_chat_stream(self, request: Request, match: re.Match[str]) -> SSEStream:
        message = request.text("message", required=True) or ""
        if len(message) > 8000:
            raise ApiError(400, "validation", "a message must be at most 8000 characters")
        conversation_id = request.identifier("conversation_id")
        model_id = request.identifier("model_id")
        return SSEStream(self._chat_frames(message, conversation_id, model_id))

    def _chat_frames(self, message: str, conversation_id: str | None, model_id: str | None) -> Iterable[str]:
        """Run the turn on a worker thread and yield what it produces.

        The chat service already accepts a callback per chunk (the CLI's `--stream` uses it), so
        this is plumbing rather than a second implementation: the same task is created, the same
        messages are stored, and the last frame carries the recorded reply.
        """
        import queue

        frames: queue.Queue[tuple[str, Any] | None] = queue.Queue()

        def emit(piece: str) -> None:
            frames.put(("chunk", {"text": piece}))

        def work() -> None:
            try:
                reply = self.ws.chat.send(
                    message,
                    conversation_id=conversation_id,
                    model_id=model_id,
                    stream_callback=emit,
                )
                payload = reply.to_dict()
                payload["simulated"] = bool(reply.simulated)
                frames.put(("done", payload))
            except ArchxError as exc:
                frames.put(("error", {"code": getattr(exc, "code", "error"), "message": exc.message}))
            except Exception as exc:  # noqa: BLE001 - a stream must always end with something
                frames.put(("error", {"code": "internal", "message": str(exc)[:400]}))
            finally:
                frames.put(None)

        threading.Thread(target=work, name="chat-stream", daemon=True).start()
        while True:
            item = frames.get()
            if item is None:
                return
            event, payload = item
            yield f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"

    @route("GET", "/api/conversations/{conversation_id}/messages", "The messages of one conversation.")
    def get_messages(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        conversation_id = unquote(match.group("conversation_id"))
        record = self.ws.conversations.get(conversation_id)
        if record.is_err:
            raise record.error
        messages = self.ws.conversations.messages(conversation_id)
        return {
            "id": conversation_id,
            "title": record.value.title,
            "messages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at,
                }
                for message in messages
            ],
        }

    # -- search ---------------------------------------------------------
    @route("GET", "/api/search", "One search across every source, with its honest notes.")
    def get_search(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        query = (request.q("q") or "").strip()
        if len(query) < 2:
            raise ApiError(400, "validation", "a search needs at least two characters")
        kinds = [value for value in (request.query.get("kind") or []) if value]
        report = self.ws.search.search(
            query,
            kinds=kinds or None,
            limit=request.q_int("limit", 20),
            include_files=request.q_bool("files", True),
        )
        return report.to_dict()

    # -- models ----------------------------------------------------------
    def _model_payload(self, record) -> dict[str, Any]:
        ready, why = self.ws.runtime_availability(record)
        provider = self.ws.provider_for(record)
        return {
            **record.to_dict(),
            "ready": ready,
            "ready_reason": why,
            "provider_id": provider.id if provider is not None else None,
            "gates": self._gates(record),
        }

    def _gates(self, record) -> list[dict[str, Any]]:
        """The ladder a remote model has to climb, and where it currently stands.

        These are the same conditions ``assert_remote_allowed`` enforces before a byte leaves
        the machine, so a refusal is legible in the page instead of mysterious.
        """
        base_url = (record.facts or {}).get("base_url")
        remote = (
            bool(base_url)
            and record.runtime in {"openai-http", "http", "gemini"}
            and not is_loopback_url(base_url)
        )
        if not remote:
            return [{
                "key": "local",
                "label": "endpoint is on this machine",
                "ok": True,
                "detail": "no data leaves the device, so no consent is needed",
            }]
        provider = self.ws.provider_for(record)
        gates = [{
            "key": "consent_policy",
            "label": "cloud routing allowed",
            "ok": not self.ws.config.get("model.local_only"),
            "detail": "model.local_only is true: this build refuses remote endpoints by default",
        }, {
            "key": "provider",
            "label": "endpoint is a registered provider",
            "ok": provider is not None,
            "detail": "register the provider so its privacy terms have somewhere to live",
        }]
        # The last two rungs stay visible even when they cannot be climbed yet: a ladder
        # that grows rows as you go makes the remaining work invisible.
        gates.append({
            "key": "privacy",
            "label": "privacy terms confirmed",
            "ok": bool(provider is not None and provider.privacy_known),
            "detail": (
                provider.blocking_reason() or "what this provider does with the data is recorded"
            ) if provider is not None else "register the provider first",
        })
        gates.append({
            "key": "consent",
            "label": "you recorded consent",
            "ok": bool(provider is not None and provider.consented),
            "detail": (
                provider.blocking_reason() or "consent on file, with a timestamp"
            ) if provider is not None else "register the provider first",
        })
        return gates

    @route("GET", "/api/models/{model_id}", "One model, its readiness and the consent ladder.")
    def get_model(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        record = self.ws.models.require(unquote(match.group("model_id")))
        return self._model_payload(record)

    @route("GET", "/api/sdks", "Which vendor SDKs are installed, and the variable each expects.")
    def get_sdks(self, request: Request, match: re.Match[str]) -> list[dict[str, Any]]:
        out = []
        for key, spec in SDKS.items():
            installed, why = sdk_available(key)
            out.append({
                "key": key,
                "label": spec.label,
                "package": spec.package,
                "env_var": spec.env_var,
                "base_url": spec.default_base_url,
                "installed": installed,
                "detail": why,
            })
        return out

    @route("POST", "/api/models", "Register a model whose key stays in the environment.")
    def post_model(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        body = request.payload()
        name = str(body.get("name") or "").strip()
        model_ref = str(body.get("model") or "").strip()
        if not name or not model_ref:
            raise ApiError(400, "validation", "a model needs a name and a model id")
        transport = str(body.get("transport") or "gemini")
        sdk = None if transport == "gemini" else transport
        if sdk is not None and sdk not in SDKS:
            raise ApiError(
                400, "unknown_sdk",
                f"unknown transport {transport!r} (gemini, or one of {', '.join(sorted(SDKS))})",
            )
        default_ref = f"secret://env/{SDKS[sdk].env_var}" if sdk else "secret://env/GEMINI_API_KEY"
        credential_ref = str(body.get("credential_ref") or default_ref).strip()
        if not credential_ref.startswith("secret://"):
            raise ApiError(
                400,
                "literal_secret",
                "the key itself is never sent to this server: give a secret://env/NAME or "
                "secret://file/PATH reference, and put the key in the environment",
            )
        base_url = str(body.get("base_url") or "").strip() or None
        if sdk is not None:
            try:
                record = self.ws.register_sdk(
                    name,
                    sdk=sdk,
                    model_ref=model_ref,
                    base_url=base_url,
                    credential_ref=credential_ref,
                    context_length=int(body.get("context_length") or 131_072),
                )
            except ArchxError as exc:
                raise ApiError(400, "validation", exc.message) from exc
            return self._model_payload(record)
        record = self.ws.register_gemini(
            name,
            model_ref=model_ref,
            base_url=base_url,
            credential_ref=credential_ref,
            api_version=str(body.get("api_version") or "v1beta"),
            context_length=int(body.get("context_length") or 1_048_576),
        )
        return self._model_payload(record)

    @route("POST", "/api/models/{model_id}/probe", "Measure one capability by calling the model.")
    def post_model_probe(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        record = self.ws.models.require(unquote(match.group("model_id")))
        capability = str(request.payload().get("capability") or "chat")
        try:
            result = self.ws.router.probe(record.id, capability=capability)
        except ArchxError as exc:
            # A failed probe is a measurement too: report it, never pretend it passed.
            raise ApiError(409, "probe_failed", exc.message, data={"model_id": record.id}) from exc
        return {"model_id": record.id, "capability": capability, "result": result}

    @route("POST", "/api/models/{model_id}/provider", "Register this model's endpoint as a provider.")
    def post_model_provider(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        record = self.ws.models.require(unquote(match.group("model_id")))
        if self.ws.providers is None:
            raise ApiError(409, "no_providers", "this workspace has no provider registry")
        existing = self.ws.provider_for(record)
        if existing is not None:
            return existing.to_dict()
        base_url = (record.facts or {}).get("base_url") or ""
        template = "google" if record.runtime == "gemini" else "openai"
        added = self.ws.providers.add(record.provider or template, template=template, base_url=base_url)
        if added.is_err:
            raise added.error
        return added.value.to_dict()

    @route("GET", "/api/providers", "Registered providers and what is known about their data handling.")
    def get_providers(self, request: Request, match: re.Match[str]) -> list[dict[str, Any]]:
        if self.ws.providers is None:
            return []
        return [self._provider_payload(provider) for provider in self.ws.providers.list()]

    @staticmethod
    def _provider_payload(provider) -> dict[str, Any]:
        return {
            **provider.to_dict(),
            "privacy_known": bool(provider.privacy_known),
            "consented": bool(provider.consented),
            "blocking_reason": provider.blocking_reason(),
        }

    @route("POST", "/api/providers/{provider_id}/privacy", "Record what you confirmed about a provider.")
    def post_provider_privacy(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        if self.ws.providers is None:
            raise ApiError(409, "no_providers", "this workspace has no provider registry")
        body = request.payload()
        leaves = body.get("data_leaves_device")
        if not isinstance(leaves, bool):
            raise ApiError(400, "validation", "data_leaves_device must be true or false, answered deliberately")
        result = self.ws.providers.confirm_privacy(
            unquote(match.group("provider_id")),
            data_leaves_device=leaves,
            training_use=str(body.get("training_use") or "unknown"),
            retention=str(body.get("retention") or "unknown"),
            region=str(body.get("region") or "unknown"),
        )
        if result.is_err:
            raise result.error
        return self._provider_payload(result.value)

    @route("POST", "/api/providers/{provider_id}/consent", "Record consent to send data to a provider.")
    def post_provider_consent(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        if self.ws.providers is None:
            raise ApiError(409, "no_providers", "this workspace has no provider registry")
        result = self.ws.providers.consent(
            unquote(match.group("provider_id")),
            note=str(request.payload().get("note") or "consent recorded in the GUI"),
        )
        if result.is_err:
            raise result.error
        return self._provider_payload(result.value)

    @route("POST", "/api/settings/model.local_only", "Turn cloud routing on or off for this home.")
    def post_local_only(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        value = request.payload().get("value")
        if not isinstance(value, bool):
            raise ApiError(400, "validation", "value must be true or false")
        self.ws.config.set("model.local_only", value, source="gui")
        self._persist_config()
        self._record_setting("model.local_only", value)
        return {"key": "model.local_only", "value": self.ws.config.get("model.local_only")}

    def _persist_config(self) -> None:
        """Write the settings file the way `config set` does, so a restart agrees with the page."""
        path = Path(self.ws.config.home) / "config.json"
        settings: dict[str, Any] = {}
        if path.exists():
            try:
                settings = json.loads(path.read_text()).get("settings", {})
            except (OSError, json.JSONDecodeError):
                settings = {}
        settings["model.local_only"] = self.ws.config.get("model.local_only")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json_text({"version": self.ws.config.version, "settings": settings}) + "\n")

    def _record_setting(self, key: str, value: Any) -> None:
        events = getattr(self.ws, "events", None)
        if events is None:
            return
        try:
            events.record("settings", "settings.changed", payload={"key": key, "value": value, "via": "gui"})
        except Exception:  # noqa: BLE001 - an audit failure must not undo the setting
            pass

    # -- memory ---------------------------------------------------------
    @route("GET", "/api/memory", "Stored memories, newest first.")
    def get_memory(self, request: Request, match: re.Match[str]) -> list[dict[str, Any]]:
        kinds = [value for value in (request.query.get("kind") or []) if value]
        items = self.ws.memory.list(kinds=kinds or None, limit=request.q_int("limit", 50))
        return [item.to_dict() for item in items]

    @route("POST", "/api/memory", "Store a memory (the same validation as `memory add`).")
    def post_memory(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        kind = request.text("kind", default="permanent") or "permanent"
        title = request.text("title", required=True) or ""
        content = request.text("content", required=True) or ""
        # ``permanent`` only accepts preference/fact/instruction/constraint; the other
        # kinds accept the wider set. An empty field means "the default for this kind".
        default_category = "fact" if kind == "permanent" else "note"
        category = str(request.payload().get("category") or default_category)
        stored = self.ws.memory.add(
            kind,
            title=title,
            content=content,
            category=category,
            source="user:gui",
        )
        if stored.is_err:
            raise stored.error
        return stored.value.to_dict()

    # -- tasks ----------------------------------------------------------
    @route("GET", "/api/tasks", "Task history.")
    def get_tasks(self, request: Request, match: re.Match[str]) -> list[dict[str, Any]]:
        tasks = self.ws.tasks.list(
            status=request.q("status") or None,
            kind=request.q("kind") or None,
            limit=request.q_int("limit", 30),
        )
        return [task.to_dict() for task in tasks]

    @route("GET", "/api/tasks/{task_id}", "One task: its record, timeline, tools and artifacts.")
    def get_task(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        task_id = unquote(match.group("task_id"))
        task = self.ws.tasks.get(task_id)
        return {
            "task": task.to_dict(),
            "timeline": self.ws.tasks.timeline(task_id),
            "tools": self.ws.tasks.tool_runs(task_id),
            "artifacts": [artifact.to_dict() for artifact in self.ws.tasks.artifacts(task_id)],
        }

    # -- jobs -----------------------------------------------------------
    @route("GET", "/api/jobs", "The queue: what is queued, what ran, what failed.")
    def get_jobs(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        jobs = self.ws.jobs.list(
            status=request.q("status") or None,
            kind=request.q("kind") or None,
            limit=request.q_int("limit", 30),
        )
        return {
            "jobs": [job.to_dict() for job in jobs],
            "stats": self.ws.jobs.stats(),
            "queue": [job.to_dict() for job in self.ws.jobs.queue()],
        }

    @route("POST", "/api/jobs/{job_id}/{action}", "pause, resume, cancel or retry one job.")
    def post_job_action(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        job_id = unquote(match.group("job_id"))
        action = match.group("action")
        handlers = {
            "pause": self.ws.jobs.pause,
            "resume": self.ws.jobs.resume,
            "cancel": self.ws.jobs.cancel,
            "retry": self.ws.jobs.retry,
        }
        handler = handlers.get(action)
        if handler is None:
            raise ApiError(404, "no_route", f"unknown job action {action!r}")
        return handler(job_id).to_dict()

    @route("POST", "/api/jobs/drain", "Run queued jobs now, in this process, up to a limit.")
    def post_jobs_drain(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        max_jobs = int(request.payload().get("max_jobs", 1))
        if max_jobs < 1 or max_jobs > 50:
            raise ApiError(400, "validation", "max_jobs must be between 1 and 50")
        from archx_agent.application.scheduler import JobRunner

        runner = JobRunner(self.ws)
        ran: list[dict[str, Any]] = []
        for _ in range(max_jobs):
            job = runner.run_once()
            if job is None:
                break
            ran.append(job.to_dict())
        return {"ran": ran, "stats": self.ws.jobs.stats()}

    # -- approvals / permissions ---------------------------------------
    @route("GET", "/api/approvals", "Approval requests, pending first.")
    def get_approvals(self, request: Request, match: re.Match[str]) -> list[dict[str, Any]]:
        status = request.q("status") or None
        return [item.to_dict() for item in self.ws.permissions.approvals(status=status)]

    @route("POST", "/api/approvals/{approval_id}/{decision}", "Approve exactly what was asked, or deny it.")
    def post_approval(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        approval_id = unquote(match.group("approval_id"))
        decision = match.group("decision")
        if decision == "approve":
            hours = request.payload().get("hours")
            approval, grant = self.ws.permissions.approve(
                approval_id, by="user:gui", hours=int(hours) if hours else None
            )
            return {"approval": approval.to_dict(), "grant": grant.to_dict()}
        if decision == "deny":
            reason = str(request.payload().get("reason") or "denied in the GUI")
            return {"approval": self.ws.permissions.deny(approval_id, by="user:gui", reason=reason).to_dict()}
        raise ApiError(404, "no_route", f"unknown approval decision {decision!r}")

    @route("GET", "/api/permissions", "Active grants, and every capability Archx knows.")
    def get_permissions(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        grants = [
            grant
            for grant in self.ws.permissions.grants(
                include_revoked=not request.q_bool("active_only", False),
                include_expired=not request.q_bool("active_only", False),
            )
            if grant.active or not request.q_bool("active_only", False)
        ]
        return {
            "grants": [grant.to_dict() for grant in grants],
            "capabilities": self.ws.permissions.capabilities(),
        }

    @route("POST", "/api/permissions/{grant_id}/revoke", "Revoke one grant.")
    def post_revoke(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        grant_id = unquote(match.group("grant_id"))
        reason = str(request.payload().get("reason") or "revoked in the GUI")
        return self.ws.permissions.revoke(grant_id, by="user:gui", reason=reason).to_dict()

    # -- research -------------------------------------------------------
    @route("GET", "/api/research", "Research runs.")
    def get_research(self, request: Request, match: re.Match[str]) -> list[dict[str, Any]]:
        closure = request.q("closed")
        closed = None if closure in (None, "") else str(closure).lower() in {"1", "true", "yes"}
        runs = self.ws.research.list(
            limit=request.q_int("limit", 20),
            status=request.q("status") or None,
            closed=closed,
        )
        return [run.to_dict() for run in runs]

    @route("POST", "/api/research", "Run a research question now, in this process.")
    def post_research(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        question = request.text("question", required=True) or ""
        mode = request.payload().get("mode") or None
        urls = request.payload().get("urls") or []
        if isinstance(urls, str):
            urls = [line.strip() for line in urls.splitlines() if line.strip()]
        if not isinstance(urls, list):
            raise ApiError(400, "validation", "urls must be a list of URLs")
        subquestions = request.payload().get("subquestions") or []
        if isinstance(subquestions, str):
            subquestions = [line.strip() for line in subquestions.splitlines() if line.strip()]
        use_model = request.payload().get("use_model", True)
        try:
            result = self.ws.researcher.run(
                question,
                mode=mode,
                urls=[str(url) for url in urls],
                subquestions=[str(item) for item in subquestions] or None,
                model_id=request.payload().get("model_id") or None,
                use_model=bool(use_model),
                allow_private_hosts=request.payload().get("allow_private_hosts"),
            )
        except ApprovalRequiredError as exc:
            raise ApiError(403, "approval_required", exc.message) from exc
        except ResearchBlocked as blocked:
            # The run row already exists and says `failed`; the GUI reports the decision
            # that would unblock it rather than pretending the question was answered.
            raise ApiError(
                403, "approval_required", blocked.message,
                data={"run_id": blocked.run_id, "approval_id": blocked.approval_id},
            ) from blocked
        return result

    @route("GET", "/api/research/{run_id}", "One run: its report, sources and verification.")
    def get_research_run(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        run_id = unquote(match.group("run_id"))
        run = self.ws.research.get(run_id)
        sources = self.ws.research.sources(run_id)
        from archx_agent.application.researcher import ResearchRunner, citation_numbers

        labels = citation_numbers(sources)
        verification = ResearchRunner.verify(run.report or "", list(labels.values()))
        return {
            "run": run.to_dict(),
            "sources": [source.to_dict() for source in sources],
            "labels": {str(source_id): label for source_id, label in labels.items()},
            "verification": verification,
        }

    @route("POST", "/api/research/{run_id}/close", "Mark a run done - your call, not the runner's.")
    def post_research_close(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        run_id = unquote(match.group("run_id"))
        note = request.payload().get("note") or ""
        if not isinstance(note, str):
            raise ApiError(400, "validation", "note must be text")
        run = self.ws.research.close(run_id, note=note, by="user:gui")
        return run.to_dict()

    @route("POST", "/api/research/{run_id}/reopen", "Undo a close.")
    def post_research_reopen(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        run = self.ws.research.reopen(unquote(match.group("run_id")), by="user:gui")
        return run.to_dict()

    @route("GET", "/api/research/{run_id}/report", "The report itself, as text.")
    def get_report(self, request: Request, match: re.Match[str]) -> Response:
        run_id = unquote(match.group("run_id"))
        run = self.ws.research.get(run_id)
        return Response(
            body=(run.report or "").encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{run_id}.md"'},
        )

    # -- learning -------------------------------------------------------
    @route("GET", "/api/learning", "Learning goals with their progress.")
    def get_learning(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        goals = self.ws.learning.list_goals(limit=request.q_int("limit", 20))
        return {
            "goals": [{**goal.to_dict(), "stats": self.ws.learning.stats(goal.id)} for goal in goals],
            "stats": self.ws.learning.stats(),
        }

    @route("POST", "/api/learning/goals", "Create a learning goal.")
    def post_learning_goal(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        goal = self.ws.learning.create_goal(
            request.text("title", required=True) or "",
            objective=request.payload().get("objective") or None,
            topic=request.payload().get("topic") or None,
            level=str(request.payload().get("level") or "beginner"),
            success_criteria=request.payload().get("criteria") or [],
            priority=int(request.payload().get("priority") or 5),
        )
        return {**goal.to_dict(), "stats": self.ws.learning.stats(goal.id)}

    @route("GET", "/api/learning/goals/{goal_id}", "One goal: items, schedule, next question, sessions.")
    def get_learning_goal(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        goal = self.ws.learning.require_goal(unquote(match.group("goal_id")))
        items = self.ws.learning.items(goal.id)
        try:
            nxt = self.ws.tutor.next_item(goal.id)
            nxt["item"].pop("expected", None)
            nxt["item"].pop("explanation", None)
            nxt["item"].pop("hints", None)
        except NothingToStudy as exc:
            nxt = {"nothing_to_study": True, "message": exc.message}
        return {
            "goal": goal.to_dict(),
            "items": [item.to_dict() for item in items],
            "stats": self.ws.learning.stats(goal.id),
            "next": nxt,
            "sessions": [session.to_dict() for session in self.ws.learning.sessions(goal.id, limit=5)],
        }

    @route("POST", "/api/learning/goals/{goal_id}/items", "Add one item to a goal.")
    def post_learning_item(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        goal = self.ws.learning.require_goal(unquote(match.group("goal_id")))
        payload = request.payload()
        hints = payload.get("hints") or []
        if isinstance(hints, str):
            hints = [line for line in hints.splitlines() if line.strip()]
        item = self.ws.learning.add_item(
            goal.id,
            request.text("prompt", required=True) or "",
            expected=(str(payload.get("expected") or "").strip() or None),
            hints=[str(hint) for hint in hints],
            explanation=(str(payload.get("explanation") or "").strip() or None),
        )
        return {**item.to_dict(), "goal": goal.to_dict()}

    @route("POST", "/api/learning/goals/{goal_id}/plan", "Propose items for a goal.")
    def post_learning_plan(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        goal = self.ws.learning.require_goal(unquote(match.group("goal_id")))
        return self.ws.tutor.plan(
            goal.id,
            use_model=bool(request.payload().get("use_model", False)),
            max_items=request.payload().get("max_items"),
        )

    @route("POST", "/api/learning/goals/{goal_id}/answer", "Answer an item: grade, schedule, explanation.")
    def post_learning_answer(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        goal = self.ws.learning.require_goal(unquote(match.group("goal_id")))
        item_id = request.text("item_id", required=True) or ""
        item = self.ws.learning.require_item(item_id)
        if item.goal_id != goal.id:
            raise ApiError(400, "validation", f"item {item.id} does not belong to goal {goal.id}")
        rating = request.payload().get("self_rating")
        result = self.ws.tutor.answer(
            item.id,
            str(request.payload().get("answer") or ""),
            self_rating=int(rating) if rating not in (None, "") else None,
            hints_used=int(request.payload().get("hints_used") or 0),
        )
        return result

    @route("POST", "/api/learning/items/{item_id}/hint", "Reveal one hint (refused before an attempt).")
    def post_learning_hint(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        item = self.ws.learning.require_item(unquote(match.group("item_id")))
        level = int(request.payload().get("level") or 1)
        try:
            return self.ws.tutor.hint(item.id, level=level)
        except HintBeforeAttempt as refused:
            raise ApiError(409, "try_first", refused.message, data={"item_id": refused.item_id}) from refused

    @route("POST", "/api/learning/goals/{goal_id}/review", "Start a review session of what is due.")
    def post_learning_review(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        goal = self.ws.learning.require_goal(unquote(match.group("goal_id")))
        try:
            return self.ws.tutor.review(goal.id)
        except NothingToStudy as exc:
            raise ApiError(409, "nothing_due", exc.message) from exc

    # -- coding workspace -----------------------------------------------
    @route("GET", "/api/code/sessions", "Coding sessions, with what each one changed and ran.")
    def get_code_sessions(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        status = request.q("status")
        if status not in (None, "", "open", "closed"):
            raise ApiError(400, "validation", "status must be open or closed")
        sessions = self.ws.code.sessions(status=status or None, limit=request.q_int("limit", 20))
        return {
            "sessions": [
                {**session.to_dict(), "stats": self._code_stats(session.id)} for session in sessions
            ],
            "roots": self.ws.tools.roots(),
            "stats": self.ws.code.stats(),
        }

    def _code_stats(self, session_id: str) -> dict[str, Any]:
        changes = self.ws.coding.changes(session_id)
        runs = self.ws.coding.runs(session_id)
        return {
            "changes": len(changes),
            "added": sum(change.added for change in changes),
            "removed": sum(change.removed for change in changes),
            "runs": len(runs),
            "failed": sum(1 for run in runs if run.status != "passed"),
        }

    @route("POST", "/api/code/sessions", "Open a session on a directory inside the tool roots.")
    def post_code_session(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session = self.ws.code.open(
            request.identifier("root"),
            title=request.text("title", required=False),
            note=request.text("note", required=False),
        )
        return {**session.to_dict(), "stats": self._code_stats(session.id)}

    @route("GET", "/api/code/sessions/{session_id}", "One session: edits, runs, the task.")
    def get_code_session(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.code.show(unquote(match.group("session_id")))

    @route("POST", "/api/code/sessions/{session_id}/read", "Read a file (needs fs.read).")
    def post_code_read(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        return self.ws.code.read(
            session_id,
            request.text("path", required=True) or "",
            start_line=_positive_int(request, "start_line", 1),
            max_lines=_positive_int(request, "max_lines"),
        )

    @route("GET", "/api/code/sessions/{session_id}/file", "Read a file with a query string.")
    def get_code_file(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        path = request.q("path") or ""
        if not path:
            raise ApiError(400, "validation", "a path is required")
        return self.ws.code.read(
            session_id, path, max_lines=request.q_int("max_lines", 0, lo=0) or None
        )

    @route("GET", "/api/code/sessions/{session_id}/tree", "List a directory (needs fs.read).")
    def get_code_tree(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        path = request.q("path") or "."
        return self.ws.code.list_dir(session_id, path, limit=request.q_int("limit", 200))

    @route("POST", "/api/code/sessions/{session_id}/write", "Create or replace a file (needs fs.write).")
    def post_code_write(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        content = request.payload().get("content")
        if not isinstance(content, str):
            raise ApiError(400, "validation", "content must be text")
        change = self.ws.code.write(
            session_id,
            request.text("path", required=True) or "",
            content,
            note=request.text("note", required=False),
        )
        return change.to_dict()

    @route("POST", "/api/code/sessions/{session_id}/delete", "Delete a file (needs fs.delete).")
    def post_code_delete(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        change = self.ws.code.delete(
            session_id,
            request.text("path", required=True) or "",
            note=request.text("note", required=False),
        )
        return change.to_dict()

    @route("POST", "/api/code/sessions/{session_id}/run", "Run a command in the session root.")
    def post_code_run(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        command = request.text("command", required=True) or ""
        timeout = request.payload().get("timeout")
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            raise ApiError(400, "validation", "timeout must be a positive integer")
        run = self.ws.code.run(
            session_id,
            command,
            timeout=timeout,
            cwd=request.text("cwd", required=False),
        )
        return run.to_dict()

    @route("POST", "/api/code/sessions/{session_id}/test", "Run a named check from archx.checks.json.")
    def post_code_test(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        name = request.text("check", required=False) or "test"
        return self.ws.code.test(session_id, name).to_dict()

    @route("GET", "/api/code/sessions/{session_id}/checks", "The checks this project declares.")
    def get_code_checks(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.code.checks(unquote(match.group("session_id")))

    @route("GET", "/api/code/sessions/{session_id}/diff", "The session's whole patch.")
    def get_code_diff(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.code.diff(
            unquote(match.group("session_id")), attach=request.q_bool("attach", True)
        )

    @route("POST", "/api/code/sessions/{session_id}/close", "Close a session; the record stays.")
    def post_code_close(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session = self.ws.code.close(
            unquote(match.group("session_id")), note=request.text("note", required=False)
        )
        return session.to_dict()

    @route("POST", "/api/code/runs/{run_id}/rerun", "Run a recorded command again.")
    def post_code_rerun(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.code.rerun(unquote(match.group("run_id"))).to_dict()

    # -- experimental mode ----------------------------------------------
    @route("GET", "/api/experiments", "Experiments, with the counts that make them readable.")
    def get_experiments(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        status = request.q("status")
        if status not in (None, "", "open", "closed"):
            raise ApiError(400, "validation", "status must be open or closed")
        rows = self.ws.experiment.list(status=status or None, limit=request.q_int("limit", 20))
        counts = self.ws.experiments.run_counts()
        return {
            "experiments": [
                {**row.to_dict(), "stats": counts.get(row.id, {"runs": 0, "failed": 0})}
                for row in rows
            ],
            "roots": self.ws.tools.roots(),
            "stats": self.ws.experiment.stats(),
        }

    @route("POST", "/api/experiments", "Declare an experiment: a command, its parameters, its metrics.")
    def post_experiment(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        params = request.payload().get("params")
        if params is not None and not isinstance(params, list):
            raise ApiError(400, "validation", "params must be a list of objects")
        metrics = request.payload().get("metrics")
        if metrics is not None and not isinstance(metrics, dict):
            raise ApiError(400, "validation", "metrics must be an object")
        experiment = self.ws.experiment.create(
            request.text("name", required=True) or "",
            request.text("command", required=True) or "",
            root=request.text("root", required=False),
            hypothesis=request.text("hypothesis", required=False),
            params=params,
            metrics=metrics,
        )
        return experiment.to_dict()

    @route("GET", "/api/experiments/{experiment_id}", "One experiment: its runs, metrics and counts.")
    def get_experiment(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.experiment.show(unquote(match.group("experiment_id")))

    @route("POST", "/api/experiments/{experiment_id}/run", "Run the experiment once.")
    def post_experiment_run(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        experiment_id = unquote(match.group("experiment_id"))
        params = request.payload().get("params")
        if params is not None and not isinstance(params, dict):
            raise ApiError(400, "validation", "params must be an object")
        timeout = request.payload().get("timeout")
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            raise ApiError(400, "validation", "timeout must be a positive integer")
        run = self.ws.experiment.run(
            experiment_id,
            params,
            timeout=timeout,
            seed=request.text("seed", required=False),
            note=request.text("note", required=False),
        )
        return run.to_dict()

    @route("GET", "/api/experiments/{experiment_id}/compare", "Line the runs up and name the best.")
    def get_experiment_compare(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.experiment.compare(
            unquote(match.group("experiment_id")),
            metric=request.q("metric") or None,
            minimise=request.q_bool("minimise", False),
            limit=request.q_int("limit", 50),
        )

    @route("GET", "/api/experiments/{experiment_id}/runs", "Every run of an experiment.")
    def get_experiment_runs(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        runs = self.ws.experiment.runs(
            unquote(match.group("experiment_id")), limit=request.q_int("limit", 50)
        )
        return {"runs": [run.to_dict() for run in runs]}

    @route("POST", "/api/experiments/{experiment_id}/close", "Close it; the runs stay readable.")
    def post_experiment_close(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.experiment.close(unquote(match.group("experiment_id"))).to_dict()

    @route("POST", "/api/experiments/{experiment_id}/reopen", "Reopen a closed experiment.")
    def post_experiment_reopen(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.experiment.reopen(unquote(match.group("experiment_id"))).to_dict()

    @route("DELETE", "/api/experiments/{experiment_id}", "Delete an experiment and its runs.")
    def delete_experiment(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        experiment_id = unquote(match.group("experiment_id"))
        self.ws.experiment.delete(experiment_id)
        return {"deleted": experiment_id}

    # -- play mode ------------------------------------------------------
    @route("GET", "/api/play/games", "Games, with the counts that make them readable.")
    def get_play_games(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        status = request.q("status")
        if status not in (None, "", "open", "finished", "abandoned"):
            raise ApiError(400, "validation", "status must be open, finished or abandoned")
        games = self.ws.play_mode.games(status=status or None, limit=request.q_int("limit", 20))
        return {
            "games": games,
            "stats": self.ws.play_mode.stats(),
            "games_available": sorted(games_module.GAMES),
        }

    @route("POST", "/api/play/games", "Start a game; the rules build the initial board.")
    def post_play_game(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        seed = request.payload().get("seed")
        if seed is not None and not isinstance(seed, int):
            raise ApiError(400, "validation", "seed must be an integer")
        return self.ws.play_mode.new(request.text("game", required=False), seed=seed)

    @route("GET", "/api/play/games/{game_id}", "The board, whose turn it is, and the legal moves.")
    def get_play_game(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.play_mode.view(
            unquote(match.group("game_id")), limit=request.q_int("moves", 12)
        )

    @route("POST", "/api/play/games/{game_id}/move", "Propose a move; the rules accept it or say why not.")
    def post_play_move(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        # A refused move is an answer, not a malformed request: 200 with `legal: false` and the
        # reason, so the page can show the referee saying no instead of an error banner.
        return self.ws.play_mode.move(
            unquote(match.group("game_id")),
            request.text("move", required=True) or "",
        )

    @route("POST", "/api/play/games/{game_id}/engine", "Let the built-in engine play one move.")
    def post_play_engine(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        seed = request.payload().get("seed")
        if seed is not None and not isinstance(seed, int):
            raise ApiError(400, "validation", "seed must be an integer")
        return self.ws.play_mode.engine_move(unquote(match.group("game_id")), seed=seed)

    @route("POST", "/api/play/games/{game_id}/auto", "Let the engine play several moves.")
    def post_play_auto(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        plies = request.payload().get("plies", 1)
        if not isinstance(plies, int) or isinstance(plies, bool):
            raise ApiError(400, "validation", "plies must be an integer")
        return self.ws.play_mode.auto(unquote(match.group("game_id")), plies=plies)

    @route("POST", "/api/play/games/{game_id}/resign", "Abandon a game; the moves stay readable.")
    def post_play_resign(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.play_mode.resign(
            unquote(match.group("game_id")), winner=request.text("winner", required=False)
        )

    @route("GET", "/api/play/games/{game_id}/history", "Every move, including the refused ones.")
    def get_play_history(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.play_mode.history(unquote(match.group("game_id")))

    @route("GET", "/api/play/sims", "Recorded simulations, with their hashes.")
    def get_play_sims(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        sims = self.ws.play_mode.sims(limit=request.q_int("limit", 20))
        return {"sims": sims, "stats": self.ws.play_mode.stats()}

    @route("POST", "/api/play/sims", "Run a deterministic simulation and record its hash.")
    def post_play_sim(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        numbers: dict[str, int] = {}
        for name, default in (("width", 40), ("height", 20), ("steps", 20), ("seed", 0)):
            value = request.payload().get(name, default)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ApiError(400, "validation", f"{name} must be an integer")
            numbers[name] = value
        density = request.payload().get("density", 0.3)
        if not isinstance(density, (int, float)) or isinstance(density, bool):
            raise ApiError(400, "validation", "density must be a number")
        return self.ws.play_mode.simulate(density=float(density), **numbers)

    @route("GET", "/api/play/sims/{sim_id}", "One simulation: parameters, series, final grid.")
    def get_play_sim(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.play_mode.sim_view(unquote(match.group("sim_id")))

    @route("POST", "/api/play/sims/{sim_id}/replay", "Recompute the simulation and check its hash.")
    def post_play_replay(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.play_mode.replay(unquote(match.group("sim_id")))

    @route("GET", "/api/play/stats", "Games, moves, refusals and simulations in this home.")
    def get_play_stats(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.play_mode.stats()

    # -- voice and media ------------------------------------------------
    @route("GET", "/api/voice/assets", "Media this home has measured, newest first.")
    def get_voice_assets(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        kind = request.q("kind")
        if kind not in (None, "", "image", "audio", "text", "unknown"):
            raise ApiError(400, "validation", "kind must be image, audio, text or unknown")
        assets = self.ws.voice.assets(kind=kind or None, limit=request.q_int("limit", 20))
        return {
            "assets": assets,
            "roots": self.ws.tools.roots(),
            "stats": self.ws.voice.stats(),
        }

    @route("POST", "/api/voice/probe", "Measure a file's bytes; the name is only a claim. (needs fs.read)")
    def post_voice_probe(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.voice.probe(
            request.text("path", required=True) or "",
            retain=bool(request.payload().get("retain", False)),
            force=bool(request.payload().get("force", False)),
        )

    @route("GET", "/api/voice/assets/{asset_id}", "One asset: what the bytes said, its words, its attempts.")
    def get_voice_asset(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.voice.view(unquote(match.group("asset_id")))

    @route("POST", "/api/voice/assets/{asset_id}/transcribe", "Ask for words (this build refuses, on the record).")
    def post_voice_transcribe(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        # A refusal is the answer: 200 with `status: refused` and the reasons, so the page can
        # show what is missing instead of an error banner that implies a bug.
        return self.ws.voice.transcribe(unquote(match.group("asset_id")))

    @route("GET", "/api/voice/assets/{asset_id}/transcripts", "The words attached to an asset.")
    def get_voice_transcripts(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        asset_id = unquote(match.group("asset_id"))
        return {"asset_id": asset_id, "transcripts": self.ws.voice.transcripts(asset_id)}

    @route("POST", "/api/voice/assets/{asset_id}/transcripts", "Attach words a person wrote.")
    def post_voice_transcript(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.voice.add_transcript(
            unquote(match.group("asset_id")),
            text=request.text("text", required=False),
            path=request.text("path", required=False),
        )

    @route("POST", "/api/voice/say", "Ask for speech (this build refuses, on the record).")
    def post_voice_say(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.voice.say(request.text("text", required=True) or "")

    @route("GET", "/api/voice/attempts", "Every attempt to hear or speak, including the refused ones.")
    def get_voice_attempts(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return {
            "attempts": self.ws.voice.attempts(
                asset_id=request.q("asset_id") or None, limit=request.q_int("limit", 30)
            )
        }

    @route("GET", "/api/voice/stats", "What this home holds, and what it still cannot do.")
    def get_voice_stats(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        stats = self.ws.voice.stats()
        stats["reasons"] = {
            "transcribe": self.ws.voice.blockers("transcribe"),
            "synthesize": self.ws.voice.blockers("synthesize"),
        }
        return stats

    # -- datasets -------------------------------------------------------
    # The counts ride on the collection rather than a `/api/datasets/stats` sibling: the router
    # sorts its patterns, and a capture (`{dataset_id}`) sorts before a literal segment ("stats"),
    # so a stats route would be shadowed by the id route. Sharing the payload is not a trick half
    # as confusing as a route that never runs.
    @route("GET", "/api/datasets", "Datasets this home has prepared, newest first.")
    def get_datasets(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return {
            "datasets": self.ws.data.list(limit=request.q_int("limit", 20)),
            "roots": self.ws.tools.roots(),
            "stats": self.ws.data.stats(),
        }

    @route("POST", "/api/datasets", "Create a dataset over one or more source paths.")
    def post_dataset(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        sources = request.payload().get("sources") or (
            [request.text("source", required=True)] if request.text("source", required=False) else []
        )
        return self.ws.data.create(
            request.text("name", required=True) or "",
            [str(source) for source in sources],
            license=request.text("license", required=False),
            notes=request.text("notes", required=False),
        )

    @route("GET", "/api/datasets/{dataset_id}", "One dataset: counts, splits, the ledger.")
    def get_dataset(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.data.view(unquote(match.group("dataset_id")))

    @route("GET", "/api/datasets/{dataset_id}/records", "The candidates, kept and dropped.")
    def get_dataset_records(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        dataset_id = unquote(match.group("dataset_id"))
        status = request.q("status")
        if status not in (None, "", "kept", "dropped"):
            raise ApiError(400, "validation", "status must be kept or dropped")
        split = request.q("split")
        if split not in (None, "", "train", "val", "test"):
            raise ApiError(400, "validation", "split must be train, val or test")
        return {
            "dataset_id": dataset_id,
            "records": self.ws.data.records(
                dataset_id, status=status or None, split=split or None,
                limit=request.q_int("limit", 100),
            ),
        }

    @route("POST", "/api/datasets/{dataset_id}/scan", "Measure every candidate (needs fs.read).")
    def post_dataset_scan(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.data.scan(unquote(match.group("dataset_id")))

    @route("POST", "/api/datasets/{dataset_id}/clean", "Apply the rules; removals keep their reason.")
    def post_dataset_clean(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.data.clean(
            unquote(match.group("dataset_id")),
            min_chars=int(payload.get("min_chars") or 0),
            dedupe=bool(payload.get("dedupe", True)),
            normalize=bool(payload.get("normalize", False)),
            drop_empty=bool(payload.get("drop_empty", True)),
            require_license=bool(payload.get("require_license", False)),
        )

    @route("POST", "/api/datasets/{dataset_id}/split", "Stable, seeded split; a leak is a refusal.")
    def post_dataset_split(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.data.split(
            unquote(match.group("dataset_id")),
            train=float(payload.get("train", 0.8)),
            val=float(payload.get("val", 0.1)),
            test=float(payload.get("test", 0.1)),
            seed=str(payload.get("seed", "0")),
        )

    @route("POST", "/api/datasets/{dataset_id}/build", "Write the export, record the manifest hash.")
    def post_dataset_build(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.data.build(
            unquote(match.group("dataset_id")),
            force=bool(request.payload().get("force", False)),
        )

    @route("GET", "/api/datasets/{dataset_id}/verify", "Recompute the manifest and disagree if it moved.")
    def get_dataset_verify(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.data.verify(unquote(match.group("dataset_id")))

    @route("GET", "/api/datasets/{dataset_id}/steps", "The ledger of steps that shaped the set.")
    def get_dataset_steps(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        dataset_id = unquote(match.group("dataset_id"))
        return {"dataset_id": dataset_id, "steps": self.ws.data.steps(dataset_id)}

    # -- training -------------------------------------------------------
    @route("GET", "/api/training/runs", "Training runs, newest first, with what this build can run.")
    def get_training_runs(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        status = request.q("status")
        if status not in (None, "", "queued", "running", "completed", "failed", "refused"):
            raise ApiError(400, "validation", "status must be a known training status")
        return {
            "runs": self.ws.trainer.jobs(
                status=status or None, dataset=request.q("dataset") or None,
                limit=request.q_int("limit", 20),
            ),
            "stats": self.ws.trainer.stats(),
            "methods": list(METHODS),
        }

    @route("POST", "/api/training/runs", "Run a trainer here, or record the refusal with its reasons.")
    def post_training_run(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.trainer.run(
            method=str(payload.get("method") or "ngram"),
            dataset=request.text("dataset", required=True) or "",
            seed=int(payload.get("seed") or 0),
            order=int(payload.get("order") or 3),
            smoothing=float(payload.get("smoothing") or 0.1),
            label_source=str(payload.get("label_source") or "directory"),
            notes=str(payload.get("notes") or ""),
        )

    @route("GET", "/api/training/runs/{job_id}", "One run: its checks, metrics, artifact and reasons.")
    def get_training_run(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.trainer.view(unquote(match.group("job_id")))

    @route("GET", "/api/training/runs/{job_id}/metrics", "The metrics, grouped by split.")
    def get_training_metrics(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.trainer.metrics(unquote(match.group("job_id")))

    @route("POST", "/api/training/preflight", "What would have to be true before a run means anything.")
    def post_training_preflight(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.trainer.preflight(
            method=str(payload.get("method") or "ngram"),
            dataset=request.text("dataset", required=False),
            base_model=request.text("base_model", required=False),
        )

    # -- static assets --------------------------------------------------
    def page(self) -> Response:
        return Response(body=(ASSETS / "index.html").read_bytes(), content_type=_CONTENT_TYPES[".html"])

    def asset(self, name: str) -> Response:
        """Serve one file from ``assets/`` by exact name - never by path."""
        safe = Path(name).name
        # 255 is the limit most filesystems impose; beyond it the open fails, and a failed open
        # for a name the client chose is a 404, not a server fault.
        if safe != name or safe.startswith(".") or not safe or len(safe.encode("utf-8", "replace")) > 255:
            raise ApiError(404, "not_found", "no such asset")
        path = ASSETS / safe
        try:
            if not path.is_file():
                raise ApiError(404, "not_found", "no such asset")
        except OSError as exc:
            raise ApiError(404, "not_found", "no such asset") from exc
        return Response(
            body=path.read_bytes(),
            content_type=_CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
            headers={"Cache-Control": "no-store"},
        )


def _positive_int(request: Request, name: str, default: int | None = None) -> int | None:
    """A payload number, or a 400. A string where a count belongs must not become one."""
    raw = request.payload().get(name)
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ApiError(400, "validation", f"{name} must be a positive integer")
    return raw


# --------------------------------------------------------------------------
# the socket
# --------------------------------------------------------------------------
def split_target(target: str) -> tuple[str, dict[str, list[str]], str | None]:
    parts = urlsplit(target)
    query = parse_qs(parts.query, keep_blank_values=True)
    token = (query.get(TOKEN_PARAM) or [None])[0]
    return unquote(parts.path) or "/", query, token


class GuiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Do not advertise the interpreter: a version banner is free reconnaissance.
    server_version = f"ArchxGui/{__version__}"
    sys_version = ""

    api: GuiApi  # set by the server factory

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        # Keep the terminal for the banner; the trace database already records what mattered.
        if getattr(self.server, "verbose", False):  # pragma: no cover - debugging aid
            super().log_message(format, *args)

    # -- verbs ----------------------------------------------------------
    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_HEAD(self) -> None:
        self._handle("HEAD")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def do_OPTIONS(self) -> None:
        # No CORS: answering a preflight would make cross-site writes possible.
        self._send(Response(status=405, payload={"ok": False, "error": {
            "code": "no_cors", "message": "this server does not answer CORS preflights"}}))

    def __getattr__(self, name: str):
        """Answer every other HTTP verb ourselves.

        `BaseHTTPRequestHandler` replies 501 with an HTML error page for a verb it has no
        ``do_`` method for, which makes this server the only part of the app that answers in
        HTML and leaks the stdlib's wording. `PATCH` did exactly that. Every verb now reaches
        the router, which knows which routes exist and which methods they accept.
        """
        if name.startswith("do_") and len(name) > 3:
            method = name[3:]

            def handle_verb() -> None:
                self._handle(method)

            return handle_verb
        raise AttributeError(name)

    # -- one request ----------------------------------------------------
    def _handle(self, method: str) -> None:
        try:
            length = int(self.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        if length > self.api.max_body_bytes:
            self._send(Response(status=413, payload={"ok": False, "error": {
                "code": "too_large", "message": f"a body must be at most {self.api.max_body_bytes} bytes"}}))
            # Refusing before reading leaves the client mid-upload. Closing then makes the kernel
            # answer with a reset, and the client sees "connection reset" instead of the refusal
            # it was given. Draining a bounded amount lets the response be read. The bound is the
            # body limit, so this cannot be used to make the server chew on a huge upload.
            self._drain_body(min(length, self.api.max_body_bytes))
            return
        raw = self.rfile.read(length) if length else b""
        body: Any = None
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(Response(status=400, payload={"ok": False, "error": {
                    "code": "bad_json", "message": "the request body is not valid JSON"}}))
                return
        path, query, token = split_target(self.path)
        effective = "GET" if method == "HEAD" else method
        request = Request(
            method=effective,
            path=path,
            query=query,
            headers={key.lower(): value for key, value in self.headers.items()},
            body=body,
            token=token,
            token_in_query=token is not None,
            remote=self.client_address[0] if self.client_address else "unknown",
        )
        if effective == "GET" and not path.startswith("/api/"):
            try:
                response = self.api.page() if path in {"/", "/index.html"} else self.api.asset(path.rsplit("/", 1)[-1])
            except ApiError as exc:
                response = self.api._error_response(exc)
            except OSError:
                response = Response(status=500, payload={"ok": False, "error": {
                    "code": "missing_assets", "message": "the GUI assets are not installed"}})
        else:
            response = self.api.dispatch(request)
        self._send(response, head=method == "HEAD")

    def _drain_body(self, limit: int) -> None:
        """Read and discard up to ``limit`` bytes that are already in flight, then close."""
        try:
            self.connection.settimeout(1.0)
        except OSError:  # pragma: no cover - a socket that cannot be tuned is not fatal
            return
        remaining = limit
        while remaining > 0:
            try:
                chunk = self.rfile.read(min(65536, remaining))
            except (OSError, ValueError):
                return
            if not chunk:
                return
            remaining -= len(chunk)

    def _send(self, response: Response | SSEStream, *, head: bool = False) -> None:
        if isinstance(response, SSEStream):
            return self._send_stream(response, head=head)
        body = response.encode()
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in _SECURITY_HEADERS.items():
            self.send_header(key, value)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        if not head:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):  # pragma: no cover - client vanished
                pass


    def _send_stream(self, stream: SSEStream, *, head: bool = False) -> None:
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", stream.content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")  # a proxy must not hold the frames back
        self.send_header("Connection", "close")
        for key, value in _SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()
        if head:
            return
        try:
            for frame in stream.frames:
                self.wfile.write(frame.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):  # pragma: no cover - the page was closed
            pass


class GuiServer:
    """A threading HTTP server wired to one :class:`GuiApi`."""

    def __init__(self, api: GuiApi, *, host: str = "127.0.0.1", port: int = 0, verbose: bool = False) -> None:
        self.api = api
        handler = functools.partial(GuiHandler)
        handler.api = api  # type: ignore[attr-defined]

        class _Handler(GuiHandler):
            pass

        _Handler.api = api  # type: ignore[attr-defined]
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.verbose = verbose  # type: ignore[attr-defined]
        self.host = host
        self.port = self.httpd.server_address[1]
        self._thread: threading.Thread | None = None

    # -- lifecycle ------------------------------------------------------
    @property
    def url(self) -> str:
        host = "127.0.0.1" if self.host in {"0.0.0.0", "::"} else self.host
        return f"http://{host}:{self.port}/"

    @property
    def token_url(self) -> str:
        return f"{self.url}?{TOKEN_PARAM}={self.api.token}"

    def start(self) -> "GuiServer":
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="archx-gui", daemon=True)
        self._thread.start()
        return self

    def serve_forever(self) -> None:
        self.httpd.serve_forever(poll_interval=0.2)

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self) -> "GuiServer":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
