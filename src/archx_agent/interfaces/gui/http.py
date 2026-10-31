"""GUI HTTP request framing, response writing and SSE transport."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any
from archx_agent import __version__
from archx_agent.interfaces.gui.protocol import (
    ASSETS as ASSETS,
    COOKIE_NAME as COOKIE_NAME,
    CSRF_HEADER as CSRF_HEADER,
    CSRF_VALUE as CSRF_VALUE,
    TOKEN_PARAM as TOKEN_PARAM,
    _SECURITY_HEADERS as _SECURITY_HEADERS,
    _CONTENT_TYPES as _CONTENT_TYPES,
    ApiError as ApiError,
    error_for as error_for,
    Request as Request,
    Response as Response,
    SSEStream as SSEStream,
    Route as Route,
    route as route,
    _positive_int as _positive_int,
)

from .api import GuiApi
from .transport_helpers import split_target

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
        self._send(
            Response(
                status=405,
                payload={
                    "ok": False,
                    "error": {
                        "code": "no_cors",
                        "message": "this server does not answer CORS preflights",
                    },
                },
            )
        )

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
        raw_length = self.headers.get("content-length") or "0"
        if (
            not raw_length.isascii()
            or not raw_length.isdigit()
            or len(raw_length) > 12
            or len(self.headers.get_all("content-length", [])) > 1
            or self.headers.get("transfer-encoding")
        ):
            self.close_connection = True
            self._send(
                Response(
                    status=400,
                    payload={
                        "ok": False,
                        "error": {
                            "code": "bad_length",
                            "message": "use a nonnegative Content-Length; transfer encoding is not supported",
                        },
                    },
                )
            )
            return
        length = int(raw_length)
        if length > self.api.max_body_bytes:
            self._send(
                Response(
                    status=413,
                    payload={
                        "ok": False,
                        "error": {
                            "code": "too_large",
                            "message": f"a body must be at most {self.api.max_body_bytes} bytes",
                        },
                    },
                )
            )
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
                self._send(
                    Response(
                        status=400,
                        payload={
                            "ok": False,
                            "error": {
                                "code": "bad_json",
                                "message": "the request body is not valid JSON",
                            },
                        },
                    )
                )
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
                response = (
                    self.api.page()
                    if path in {"/", "/index.html"}
                    else self.api.asset(path.rsplit("/", 1)[-1])
                )
            except ApiError as exc:
                response = self.api._error_response(exc)
            except OSError:
                response = Response(
                    status=500,
                    payload={
                        "ok": False,
                        "error": {
                            "code": "missing_assets",
                            "message": "the GUI assets are not installed",
                        },
                    },
                )
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
            except (
                BrokenPipeError,
                ConnectionResetError,
            ):  # pragma: no cover - client vanished
                pass

    def _send_stream(self, stream: SSEStream, *, head: bool = False) -> None:
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", stream.content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "X-Accel-Buffering", "no"
        )  # a proxy must not hold the frames back
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
        except (
            BrokenPipeError,
            ConnectionResetError,
        ):  # pragma: no cover - the page was closed
            pass
