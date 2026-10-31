"""GUI socket binding, URL generation and server lifecycle."""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
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
from .http import GuiHandler

class GuiServer:
    """A threading HTTP server wired to one :class:`GuiApi`."""

    def __init__(
        self,
        api: GuiApi,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        verbose: bool = False,
    ) -> None:
        self.api = api
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
        self._thread = threading.Thread(
            target=self.httpd.serve_forever, name="archx-gui", daemon=True
        )
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
