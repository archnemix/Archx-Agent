"""GUI URL splitting and free-port helpers."""

from __future__ import annotations

import socket
from urllib.parse import parse_qs, unquote, urlsplit
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

def split_target(target: str) -> tuple[str, dict[str, list[str]], str | None]:
    parts = urlsplit(target)
    query = parse_qs(parts.query, keep_blank_values=True)
    token = (query.get(TOKEN_PARAM) or [None])[0]
    return unquote(parts.path) or "/", query, token

def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
