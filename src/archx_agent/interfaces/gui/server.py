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
from archx_agent.application.researcher import ResearchBlocked
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ArchxError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now

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


_STATUS_FOR_ERROR: tuple[tuple[type, int, str], ...] = (
    (ValidationError, 400, "validation"),
    (NotFoundError, 404, "not_found"),
    (ConflictError, 409, "conflict"),
    (ApprovalRequiredError, 403, "approval_required"),
    (PermissionDeniedError, 403, "permission_denied"),
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
    def dispatch(self, request: Request) -> Response:
        with self._lock:
            self.requests += 1
        try:
            if request.method == "OPTIONS":
                raise ApiError(405, "no_cors", "this server does not answer CORS preflights")
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                self._require_csrf(request)
            if request.path == "/api/health":
                return Response(payload={"ok": True, "data": self.health()})
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
                if isinstance(result, (Response, bytes, str)):
                    return result if isinstance(result, Response) else Response(payload=result)
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
        out = []
        for record in self.ws.models.list():
            ready, why = self.ws.runtime_availability(record)
            out.append({**record.to_dict(), "ready": ready, "ready_reason": why})
        return out

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
        message = str(request.field("message", required=True)).strip()
        if len(message) > 8000:
            raise ApiError(400, "validation", "a message must be at most 8000 characters")
        conversation_id = request.payload().get("conversation_id") or None
        model_id = request.payload().get("model_id") or None
        reply = self.ws.chat.send(message, conversation_id=conversation_id, model_id=model_id)
        payload = reply.to_dict()
        payload["simulated"] = bool(reply.simulated)
        return payload

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

    # -- memory ---------------------------------------------------------
    @route("GET", "/api/memory", "Stored memories, newest first.")
    def get_memory(self, request: Request, match: re.Match[str]) -> list[dict[str, Any]]:
        kinds = [value for value in (request.query.get("kind") or []) if value]
        items = self.ws.memory.list(kinds=kinds or None, limit=request.q_int("limit", 50))
        return [item.to_dict() for item in items]

    @route("POST", "/api/memory", "Store a memory (the same validation as `memory add`).")
    def post_memory(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        kind = str(request.field("kind", default="permanent"))
        title = str(request.field("title", required=True)).strip()
        content = str(request.field("content", required=True)).strip()
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
        runs = self.ws.research.list(limit=request.q_int("limit", 20), status=request.q("status") or None)
        return [run.to_dict() for run in runs]

    @route("POST", "/api/research", "Run a research question now, in this process.")
    def post_research(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        question = str(request.field("question", required=True)).strip()
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

    @route("GET", "/api/research/{run_id}/report", "The report itself, as text.")
    def get_report(self, request: Request, match: re.Match[str]) -> Response:
        run_id = unquote(match.group("run_id"))
        run = self.ws.research.get(run_id)
        return Response(
            body=(run.report or "").encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{run_id}.md"'},
        )

    # -- static assets --------------------------------------------------
    def page(self) -> Response:
        return Response(body=(ASSETS / "index.html").read_bytes(), content_type=_CONTENT_TYPES[".html"])

    def asset(self, name: str) -> Response:
        """Serve one file from ``assets/`` by exact name - never by path."""
        safe = Path(name).name
        if safe != name or safe.startswith("."):
            raise ApiError(404, "not_found", "no such asset")
        path = ASSETS / safe
        if not path.is_file():
            raise ApiError(404, "not_found", "no such asset")
        return Response(
            body=path.read_bytes(),
            content_type=_CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
            headers={"Cache-Control": "no-store"},
        )


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

    # -- one request ----------------------------------------------------
    def _handle(self, method: str) -> None:
        try:
            length = int(self.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        if length > self.api.max_body_bytes:
            self._send(Response(status=413, payload={"ok": False, "error": {
                "code": "too_large", "message": f"a body must be at most {self.api.max_body_bytes} bytes"}}))
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

    def _send(self, response: Response, *, head: bool = False) -> None:
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
