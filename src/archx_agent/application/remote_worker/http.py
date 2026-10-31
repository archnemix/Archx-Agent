"""Remote worker HTTP authentication, bounded framing, JSON and exact routing.

Each response closes its connection: rejected/unread bodies cannot become a second
request. This is a private/trusted worker transport, not a public multi-tenant server.
"""

from __future__ import annotations

import hmac
import json
import math
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from archx_agent.helpers.processes import positive_integer
from .worker import Worker
from .protocol import PROTOCOL, WorkerRefusal, WorkerBusy
from .policy import require_authenticated_bind

MAX_BODY_BYTES = 8_000_000


def make_server(
    worker: Worker,
    *,
    host: str = "127.0.0.1",
    port: int = 9001,
    max_body_bytes: int = MAX_BODY_BYTES,
    request_timeout: float = 10.0,
) -> ThreadingHTTPServer:
    require_authenticated_bind(host, token=worker.token, allow_exec=worker.allow_exec)
    positive_integer(max_body_bytes, "max_body_bytes")
    if (
        isinstance(request_timeout, bool)
        or not isinstance(request_timeout, (int, float))
        or not math.isfinite(request_timeout)
        or request_timeout <= 0
    ):
        raise ValueError("request_timeout must be a positive finite number")

    # Bind credentials to this server instance; later object mutation must not
    # silently disable authentication. Recreate the server to rotate credentials.
    expected_token = worker.token.encode("ascii") if worker.token is not None else None

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "archx-worker/1"

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(request_timeout)

        def log_message(self, fmt: str, *args: Any) -> None:
            if os.environ.get("ARCHX_WORKER_LOG"):
                super().log_message(fmt, *args)

        def _authorised(self) -> bool:
            expected = expected_token
            if expected is None:
                # An unauthenticated training server cannot be upgraded to shell
                # execution in-place. A newly authenticated server is required.
                return not worker.allow_exec
            values = self.headers.get_all("Authorization", [])
            if len(values) != 1:
                return False
            header = values[0]
            given = header[7:] if header.lower().startswith("bearer ") else ""
            return bool(given) and hmac.compare_digest(
                given.encode("utf-8"), expected
            )

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            self.close_connection = True
            body = json.dumps(payload).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Disconnected callers must not cause a handler traceback.

        def _target(self):
            try:
                if not self.path.startswith("/") or self.path.startswith("//"):
                    raise ValueError("not an origin-form target")
                return urlsplit(self.path)
            except ValueError:
                self._send(
                    400, {"protocol": PROTOCOL, "error": "invalid request target"}
                )
                return None

        def do_GET(self) -> None:  # noqa: N802
            if not self._authorised():
                self._send(
                    401,
                    {
                        "protocol": PROTOCOL,
                        "error": "this worker requires a bearer token",
                    },
                )
                return
            target = self._target()
            if target is None:
                return
            if target.path == "/files":
                root = (parse_qs(target.query).get("root") or ["project"])[0]
                answer = worker.list_files(root)
                self._send(403 if answer.get("refused") else 200, answer)
            elif target.path in ("/health", "/"):
                self._send(
                    200,
                    {
                        "protocol": PROTOCOL,
                        "machine": worker.name,
                        "status": "ok",
                        "jobs": len(worker.jobs),
                        "capacity": worker.capacity(),
                    },
                )
            elif (
                target.path.startswith("/jobs/")
                and target.path[6:]
                and "/" not in target.path[6:]
            ):
                self._send(200, worker.result(target.path[6:]))
            else:
                self._send(
                    404, {"protocol": PROTOCOL, "error": "no route for this path"}
                )

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorised():
                self._send(
                    401,
                    {
                        "protocol": PROTOCOL,
                        "error": "this worker requires a bearer token",
                    },
                )
                return
            values = self.headers.get_all("Content-Length", [])
            length_text = values[0] if values else "0"
            if (
                len(values) > 1
                or "Transfer-Encoding" in self.headers
                or not length_text.isascii()
                or not length_text.isdigit()
                or len(length_text) > 12
            ):
                self._send(
                    400,
                    {
                        "protocol": PROTOCOL,
                        "error": "use one nonnegative Content-Length; transfer encoding is unsupported",
                    },
                )
                return
            length = int(length_text)
            if length > max_body_bytes:
                self._send(
                    413,
                    {
                        "protocol": PROTOCOL,
                        "error": f"body exceeds {max_body_bytes} bytes",
                    },
                )
                return
            try:
                raw = self.rfile.read(length) if length else b""
            except TimeoutError:
                self._send(
                    408, {"protocol": PROTOCOL, "error": "request body timed out"}
                )
                return
            if len(raw) != length:
                self._send(
                    400,
                    {
                        "protocol": PROTOCOL,
                        "error": "request body shorter than Content-Length",
                    },
                )
                return
            try:
                request = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, RecursionError):
                self._send(
                    400, {"protocol": PROTOCOL, "error": "body must be UTF-8 JSON"}
                )
                return
            if not isinstance(request, dict):
                self._send(
                    400,
                    {"protocol": PROTOCOL, "error": "request must be a JSON object"},
                )
                return
            target = self._target()
            if target is None:
                return
            path = target.path.rstrip("/")
            if path == "/exec":
                answer = worker.execute(request)
                self._send(403 if answer.get("refused") else 200, answer)
            elif path == "/files":
                answer = worker.write_files(request)
                self._send(403 if answer.get("refused") else 200, answer)
            elif path == "/jobs":
                try:
                    accepted = worker.accept(request)
                except WorkerBusy as refusal:
                    self._send(429, {
                        "protocol": PROTOCOL,
                        "machine": worker.name,
                        "error": str(refusal),
                        "status": "refused",
                    })
                    return
                except WorkerRefusal as refusal:
                    self._send(
                        422,
                        {
                            "protocol": PROTOCOL,
                            "machine": worker.name,
                            "error": str(refusal),
                            "status": "refused",
                        },
                    )
                    return
                self._send(200, accepted)
            else:
                self._send(
                    404, {"protocol": PROTOCOL, "error": "no route for this path"}
                )

    return ThreadingHTTPServer((host, port), Handler)
