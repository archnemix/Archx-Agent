"""GUI API assets responsibility."""

from __future__ import annotations

from pathlib import Path
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


class GuiAssetsMixin:
    def page(self) -> Response:
        return Response(
            body=(ASSETS / "index.html").read_bytes(),
            content_type=_CONTENT_TYPES[".html"],
        )

    def asset(self, name: str) -> Response:
        """Serve one file from ``assets/`` by exact name - never by path."""
        safe = Path(name).name
        # 255 is the limit most filesystems impose; beyond it the open fails, and a failed open
        # for a name the client chose is a 404, not a server fault.
        if (
            safe != name
            or safe.startswith(".")
            or not safe
            or len(safe.encode("utf-8", "replace")) > 255
        ):
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
