"""MCP server HTTP framing, bearer authentication and explicit socket lifecycle.

Private loopback use may be unauthenticated. Non-loopback binds require a token;
this is still not TLS, per-client authorization or public-service certification.
"""

from __future__ import annotations
import hmac
import ipaddress
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from archx_agent import __version__
from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.processes import positive_integer
from .protocol import SERVER_NAME


class McpHttpMixin:
    def serve_http(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8848,
        token: str | None = None,
        max_body_bytes: int = 8_000_000,
        request_timeout: float = 10.0,
    ) -> ThreadingHTTPServer:
        try:
            positive_integer(max_body_bytes, "max_body_bytes")
            if (
                isinstance(request_timeout, bool)
                or not isinstance(request_timeout, (int, float))
                or not math.isfinite(request_timeout)
                or request_timeout <= 0
            ):
                raise ValueError("request_timeout must be positive and finite")
            if token is not None and (
                not isinstance(token, str)
                or not token
                or any(not 33 <= ord(c) <= 126 for c in token)
            ):
                raise ValueError(
                    "token must be nonempty printable ASCII without whitespace"
                )
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = host == "localhost"
            if not local and token is None:
                raise ValueError(
                    "non-loopback MCP binds require an explicit bearer token; use private transport/TLS"
                )
        except (ValueError, TypeError) as exc:
            raise ValidationError(str(exc)) from exc
        handler = self._http_handler(
            token=token, max_body_bytes=max_body_bytes, request_timeout=request_timeout
        )
        server = ThreadingHTTPServer((host, port), handler)
        self.ws.events.record(
            "mcp",
            "server.listening",
            level="summary",
            payload={
                "host": host,
                "port": server.server_address[1],
                "authenticated": token is not None,
            },
        )
        return server

    def _http_handler(
        self, *, token=None, max_body_bytes=8_000_000, request_timeout=10.0
    ):
        server_self = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.connection.settimeout(request_timeout)

            def _authorised(self):
                if token is None:
                    return True
                values = self.headers.get_all("Authorization", [])
                return (
                    len(values) == 1
                    and values[0][:7].lower() == "bearer "
                    and hmac.compare_digest(
                        values[0][7:].encode("utf-8"), token.encode("ascii")
                    )
                )

            def _send(self, status, payload):
                self.close_connection = True
                body = (
                    json.dumps(payload).encode("utf-8") if payload is not None else b""
                )
                if len(body) > max_body_bytes:
                    status = 413
                    body = json.dumps(
                        server_self._error(None, -32000, "response exceeds byte budget")
                    ).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass

            def _access(self):
                if not self._authorised():
                    self._send(401, server_self._error(None, -32001, "unauthorized"))
                    return False
                if self.path not in ("/", "/mcp"):
                    self._send(
                        404, server_self._error(None, -32600, "unknown endpoint")
                    )
                    return False
                return True

            def do_GET(self):
                if self._access():
                    self._send(
                        200,
                        {
                            "name": SERVER_NAME,
                            "version": __version__,
                            "tools": server_self.allowed_tools,
                        },
                    )

            def do_POST(self):
                if not self._access():
                    return
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get_all("Transfer-Encoding") or len(lengths) != 1:
                    self._send(
                        400,
                        server_self._error(
                            None,
                            -32600,
                            "one Content-Length required; transfer encoding unsupported",
                        ),
                    )
                    return
                value = lengths[0].strip()
                if not value.isascii() or not value.isdecimal():
                    self._send(
                        400, server_self._error(None, -32600, "invalid Content-Length")
                    )
                    return
                digits = value.lstrip("0") or "0"
                if (
                    len(digits) > len(str(max_body_bytes))
                    or int(digits) > max_body_bytes
                ):
                    self._send(
                        413,
                        server_self._error(None, -32600, "request exceeds byte budget"),
                    )
                    return
                size = int(digits)
                try:
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        self._send(
                            400, server_self._error(None, -32700, "truncated body")
                        )
                        return
                    message = json.loads(raw.decode("utf-8"))
                except TimeoutError:
                    self._send(
                        408, server_self._error(None, -32700, "body inactivity timeout")
                    )
                    return
                except (ValueError, UnicodeError, RecursionError):
                    self._send(
                        400, server_self._error(None, -32700, "invalid UTF-8/JSON")
                    )
                    return
                response = server_self.handle(message)
                self._send(202 if response is None else 200, response)

            def log_message(self, *args):
                pass

        return Handler
