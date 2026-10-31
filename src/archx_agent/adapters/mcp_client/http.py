"""Bounded MCP HTTP bodies, UTF-8/JSON/SSE parsing and serialized session headers."""

from __future__ import annotations
import json
import re
import time
from typing import Any, Mapping
from urllib import error as urlerror, request as urlrequest
from urllib.parse import urlsplit
from archx_agent.helpers.exceptions import (
    MCPProtocolError,
    MCPServerError,
    MCPTimeoutError,
    ValidationError,
)
from .base import _JsonRpcBase


class _NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()  # refusal exceptions may retain frames; do not retain the response socket
        raise MCPProtocolError(
            "MCP redirects are refused; configure the final endpoint"
        )


class McpHttpClient(_JsonRpcBase):
    def __init__(
        self,
        url: str,
        *,
        name: str = "mcp-http",
        headers: Mapping[str, str] | None = None,
        timeout: float = 20.0,
        max_message_bytes: int = 8_000_000,
        max_pending: int = 32,
    ) -> None:
        try:
            if not isinstance(url, str) or any(
                ord(char) <= 32 or ord(char) == 127 for char in url
            ):
                raise ValueError("invalid URL text")
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("expected an http(s) URL without embedded credentials")
            parsed.port  # validate port syntax/range before starting transport I/O
        except (ValueError, TypeError) as exc:
            raise ValidationError(
                "an MCP HTTP server needs a valid http(s) URL without embedded credentials"
            ) from exc
        super().__init__(
            name=name,
            timeout=timeout,
            max_message_bytes=max_message_bytes,
            max_pending=max_pending,
        )
        self.url = url
        if headers is not None and not isinstance(headers, Mapping):
            raise ValidationError("MCP HTTP headers must be a mapping")
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **dict(headers or {}),
        }
        for key, value in self.headers.items():
            if (
                not isinstance(key, str)
                or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key)
                or not isinstance(value, str)
                or any(c in value for c in "\r\n\0")
            ):
                raise ValidationError(
                    "MCP HTTP headers must be valid text name/value pairs"
                )
            try:
                value.encode("latin-1")
            except UnicodeError as exc:
                raise ValidationError(
                    "MCP HTTP header values must fit HTTP Latin-1 bytes"
                ) from exc
        self._opener = urlrequest.build_opener(_NoRedirect())
        self.session_id: str | None = None

    def _read_body(
        self, response, deadline: float, limit: int, *, prefix: bool = False
    ) -> bytes:
        chunks = []
        size = 0
        expected = None
        if not prefix:
            lengths = response.headers.get_all("Content-Length", [])
            encodings = response.headers.get_all("Transfer-Encoding", [])
            if len(lengths) > 1 or len(encodings) > 1 or lengths and encodings:
                raise MCPProtocolError(f"{self.name}: ambiguous HTTP response framing")
            if encodings and encodings[0].strip().lower() != "chunked":
                raise MCPProtocolError(
                    f"{self.name}: unsupported HTTP transfer encoding"
                )
            if lengths:
                value = lengths[0].strip()
                if not value.isascii() or not value.isdecimal():
                    raise MCPProtocolError(f"{self.name}: invalid HTTP response length")
                if len(value.lstrip("0")) > len(str(limit)):
                    raise MCPProtocolError(
                        f"{self.name}: HTTP body exceeds {limit} bytes"
                    )
                expected = int(value.lstrip("0") or "0")
                if expected > limit:
                    raise MCPProtocolError(
                        f"{self.name}: HTTP body exceeds {limit} bytes"
                    )
        while True:
            if self.closed or time.monotonic() >= deadline:
                raise MCPTimeoutError(f"{self.name}: response deadline expired")
            if prefix and size >= limit:
                return b"".join(chunks)
            chunk = response.read1(min(65_536, limit + (0 if prefix else 1) - size))
            if not chunk:
                if expected is not None and size != expected:
                    raise MCPProtocolError(f"{self.name}: truncated HTTP response body")
                return b"".join(chunks)
            size += len(chunk)
            if size > limit:
                raise MCPProtocolError(f"{self.name}: HTTP body exceeds {limit} bytes")
            chunks.append(chunk)

    def _send(self, payload: bytes, deadline: float) -> None:
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urlrequest.Request(
            self.url, data=payload, headers=headers, method="POST"
        )
        try:
            with self._opener.open(
                request, timeout=max(0.001, deadline - time.monotonic())
            ) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    self.session_id = session
                raw = self._read_body(response, deadline, self.max_message_bytes)
                content_type = (response.headers.get("Content-Type") or "").lower()
        except urlerror.HTTPError as exc:
            try:
                detail = self._read_body(
                    exc, deadline, min(self.max_message_bytes, 300), prefix=True
                ).decode("utf-8", errors="replace")
            finally:
                exc.close()
            raise MCPServerError(
                f"{self.name}: HTTP {exc.code} from {self.url}: {detail}"
            ) from exc
        except (urlerror.URLError, OSError) as exc:
            if isinstance(getattr(exc, "reason", exc), TimeoutError):
                raise MCPTimeoutError(f"{self.name}: HTTP deadline expired") from exc
            raise MCPServerError(
                f"{self.name}: cannot reach {self.url}: {exc}"
            ) from exc
        try:
            text = raw.decode("utf-8")
        except UnicodeError as exc:
            raise MCPProtocolError(f"{self.name}: HTTP response is not UTF-8") from exc
        for message in _parse_http_body(text, content_type):
            self._dispatch_incoming(message)


def _parse_http_body(raw: str, content_type: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if not text:
        return []
    try:
        if "text/event-stream" in content_type or text.startswith(("event:", "data:")):
            messages = []
            for block in text.replace("\r\n", "\n").split("\n\n"):
                payload = "\n".join(
                    line[5:].lstrip()
                    for line in block.split("\n")
                    if line.startswith("data:")
                ).strip()
                if payload and payload != "[DONE]":
                    messages.append(json.loads(payload))
        else:
            parsed = json.loads(text)
            if parsed == []:
                raise MCPProtocolError("empty JSON-RPC batch")
            messages = parsed if isinstance(parsed, list) else [parsed]
    except (ValueError, RecursionError) as exc:
        raise MCPProtocolError(f"invalid JSON/SSE response: {exc}") from exc
    if any(not isinstance(message, dict) for message in messages):
        raise MCPProtocolError("JSON/SSE response must contain objects")
    return messages
