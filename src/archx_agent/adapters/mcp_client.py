"""MCP (Model Context Protocol) client transports.

Two transports, both real:

* ``stdio`` - spawn a server process and speak line-delimited JSON-RPC 2.0 over its
  stdin/stdout. This is how most MCP servers ship today.
* ``http`` - POST JSON-RPC to a URL, accepting either a JSON body or an SSE stream
  (``text/event-stream``) as the response, and echoing ``Mcp-Session-Id`` when the server
  issues one.

What this module does **not** do: it does not decide whether a tool may be called. It
connects, lists and invokes. ``managers/mcp.py`` registers the discovered tools with
``ToolManager``, which asks the permission centre first. A server can advertise anything;
only a trusted registration plus a grant can execute.

Protocol safety choices:

* every request has a deadline (``timeout``) and the pending request is failed, not left
  hanging, so a wedged server cannot freeze the CLI;
* unknown notifications are ignored, unknown *server requests* get a JSON-RPC
  ``method not found`` error (never a silent hang);
* stderr is captured and reported on failure, because "it exited 1" alone is useless;
* the environment for a spawned server is inherited minus nothing but plus nothing -
  the server is a program the user chose to run, unlike a *tool* subprocess where the
  environment is rebuilt (see ``adapters/local_tools.py``). The difference is deliberate:
  MCP servers commonly need their own credentials from the environment.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping
from urllib import error as urlerror
from urllib import request as urlrequest

from archx_agent.helpers.exceptions import (
    MCPProtocolError,
    MCPServerError,
    MCPTimeoutError,
    MCPToolError,
    ValidationError,
)

PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "archx-agent"


@dataclass
class McpToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "annotations": self.annotations,
        }


@dataclass
class McpCallResult:
    content: list[dict[str, Any]]
    is_error: bool = False
    structured: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"content": self.content, "isError": self.is_error, "structured": self.structured}

    @property
    def text(self) -> str:
        parts = []
        for item in self.content:
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(json.dumps(item, sort_keys=True))
        return "\n".join(parts)


class _Pending:
    __slots__ = ("id", "result", "error", "event")

    def __init__(self, request_id: int) -> None:
        self.id = request_id
        self.result: dict[str, Any] | None = None
        self.error: Exception | None = None
        self.event = threading.Event()


class _JsonRpcBase:
    """Shared request bookkeeping, error mapping and response interpretation."""

    def __init__(self, *, name: str, timeout: float = 20.0) -> None:
        self.name = name
        self.timeout = timeout
        self._next_id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self.protocol_version: str | None = None
        self.server_info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}
        self.closed = False

    # -- ids --------------------------------------------------------------
    def _new_id(self) -> int:
        with self._lock:
            self._next_id += 1
            return self._next_id

    # -- transport hooks --------------------------------------------------
    def _write(self, message: dict[str, Any]) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    # -- request/response -------------------------------------------------
    def request(self, method: str, params: Mapping[str, Any] | None = None,
                *, timeout: float | None = None) -> dict[str, Any]:
        request_id = self._new_id()
        pending = _Pending(request_id)
        with self._lock:
            self._pending[request_id] = pending
        try:
            self._write(
                {"jsonrpc": "2.0", "id": request_id, "method": method,
                 "params": dict(params or {})}
            )
        except Exception as exc:  # noqa: BLE001 - transport failure is the caller's answer
            with self._lock:
                self._pending.pop(request_id, None)
            if isinstance(exc, MCPServerError):
                raise
            raise MCPServerError(f"{self.name}: cannot send {method}: {exc}") from exc
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._lock:
                    self._pending.pop(request_id, None)
                raise MCPTimeoutError(
                    f"{self.name}: no answer to {method} within "
                    f"{timeout if timeout is not None else self.timeout}s"
                )
            if pending.event.wait(min(0.05, remaining)):
                break
        with self._lock:
            self._pending.pop(request_id, None)
        if pending.error is not None:
            raise pending.error
        return pending.result or {}

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = dict(params)
        self._write(payload)

    # -- incoming ---------------------------------------------------------
    def _dispatch_incoming(self, message: dict[str, Any]) -> None:
        if not isinstance(message, dict):
            return
        if "id" in message and ("result" in message or "error" in message):
            request_id = message.get("id")
            with self._lock:
                pending = self._pending.get(request_id) if isinstance(request_id, int) else None
            if pending is None:
                return  # late answer to a timed-out request
            error = message.get("error")
            if error is not None:
                pending.error = MCPServerError(
                    f"{self.name}: {error.get('message', 'error')} "
                    f"(code {error.get('code', '?')})"
                )
            else:
                result = message.get("result")
                pending.result = result if isinstance(result, dict) else {"value": result}
            pending.event.set()
            return
        if "id" in message and "method" in message:
            # A server -> client request. We answer, so the server never hangs on us.
            method = message.get("method")
            if method == "ping":
                self._write({"jsonrpc": "2.0", "id": message["id"], "result": {}})
            else:
                self._write(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {"code": -32601, "message": f"method not found: {method}"},
                    }
                )
            return
        # otherwise: a notification, which this client does not act on

    def _fail_all(self, exc: Exception) -> None:
        with self._lock:
            pending, self._pending = self._pending, {}
        for item in pending.values():
            item.error = exc
            item.event.set()

    # -- MCP surface ------------------------------------------------------
    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": "1"},
            },
        )
        self.protocol_version = str(result.get("protocolVersion") or "")
        self.server_info = result.get("serverInfo") or {}
        self.capabilities = result.get("capabilities") or {}
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[McpToolInfo]:
        result = self.request("tools/list")
        tools = []
        for raw in result.get("tools") or []:
            if not isinstance(raw, dict) or not raw.get("name"):
                continue
            tools.append(
                McpToolInfo(
                    name=str(raw["name"]),
                    description=str(raw.get("description") or ""),
                    input_schema=raw.get("inputSchema") or {},
                    annotations=raw.get("annotations") or {},
                )
            )
        return tools

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None,
                  *, timeout: float | None = None) -> McpCallResult:
        result = self.request(
            "tools/call", {"name": name, "arguments": dict(arguments or {})}, timeout=timeout
        )
        content = result.get("content")
        if not isinstance(content, list):
            content = []
        is_error = bool(result.get("isError"))
        call = McpCallResult(
            content=[c for c in content if isinstance(c, dict)],
            is_error=is_error,
            structured=result.get("structuredContent") if isinstance(result.get("structuredContent"), dict) else None,
        )
        if is_error:
            raise MCPToolError(f"{self.name}: tool {name} reported an error: {call.text[:300]}")
        return call

    def list_resources(self) -> list[dict[str, Any]]:
        result = self.request("resources/list")
        return [r for r in (result.get("resources") or []) if isinstance(r, dict)]

    def read_resource(self, uri: str) -> dict[str, Any]:
        return self.request("resources/read", {"uri": uri})

    def list_prompts(self) -> list[dict[str, Any]]:
        result = self.request("prompts/list")
        return [p for p in (result.get("prompts") or []) if isinstance(p, dict)]


class McpStdioClient(_JsonRpcBase):
    """Spawns a server and speaks line-delimited JSON-RPC over its pipes."""

    def __init__(
        self,
        command: Iterable[str],
        *,
        name: str = "mcp",
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        argv = [str(x) for x in command]
        if not argv:
            raise ValidationError("an MCP stdio server needs a command to run")
        super().__init__(name=name, timeout=timeout)
        self.argv = argv
        child_env = dict(os.environ if env is None else env)
        self._stderr_lines: list[str] = []
        try:
            self.process = subprocess.Popen(  # noqa: S603 - the user configured this command
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=child_env,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise MCPServerError(
                f"{name}: cannot start {argv[0]!r}: {exc.strerror or exc}"
            ) from exc
        self._write_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, name=f"{name}-reader", daemon=True)
        self._reader.start()
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, name=f"{name}-stderr", daemon=True
        )
        self._stderr_thread.start()

    # -- transport --------------------------------------------------------
    def _write(self, message: dict[str, Any]) -> None:
        if self.closed or self.process.poll() is not None:
            raise MCPServerError(self._exit_message())
        assert self.process.stdin is not None
        line = json.dumps(message, separators=(",", ":")) + "\n"
        try:
            with self._write_lock:
                self.process.stdin.write(line)
                self.process.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise MCPServerError(self._exit_message()) from exc

    def _read_loop(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                text = line.strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    # A server that prints logs to stdout is broken; say so instead of
                    # silently treating the line as a protocol message.
                    self._stderr_lines.append(f"[non-JSON on stdout] {text[:200]}")
                    continue
                self._dispatch_incoming(message)
        finally:
            self.closed = True
            self._fail_all(MCPServerError(self._exit_message()))

    def _stderr_loop(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self._stderr_lines.append(line.rstrip("\n"))
            if len(self._stderr_lines) > 200:
                del self._stderr_lines[:50]

    # -- lifecycle --------------------------------------------------------
    def _exit_message(self) -> str:
        code = self.process.poll()
        detail = "; ".join(self.stderr_tail(3))
        if code is None:
            return f"{self.name}: the server connection closed unexpectedly"
        message = f"{self.name}: the server exited with status {code}"
        return f"{message} ({detail})" if detail else message

    def stderr_tail(self, lines: int = 5) -> list[str]:
        return list(self._stderr_lines[-lines:])

    def alive(self) -> bool:
        return not self.closed and self.process.poll() is None

    def close(self, *, timeout: float = 3.0) -> None:
        self.closed = True
        if self.process.poll() is None:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
            except OSError:  # pragma: no cover
                pass
            self.process.terminate()
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:  # pragma: no cover - stubborn server
                self.process.kill()
                self.process.wait(timeout=timeout)
        for stream in (self.process.stdout, self.process.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:  # pragma: no cover
                pass
        self._fail_all(MCPServerError(f"{self.name}: client closed"))


class McpHttpClient(_JsonRpcBase):
    """JSON-RPC over HTTP POST, accepting JSON or SSE responses."""

    def __init__(
        self,
        url: str,
        *,
        name: str = "mcp-http",
        headers: Mapping[str, str] | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not url.startswith(("http://", "https://")):
            raise ValidationError(f"an MCP HTTP server needs an http(s) URL, got {url!r}")
        super().__init__(name=name, timeout=timeout)
        self.url = url
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **{str(k): str(v) for k, v in (headers or {}).items()},
        }
        self.session_id: str | None = None

    def _write(self, message: dict[str, Any]) -> None:
        body = json.dumps(message).encode()
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urlrequest.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urlrequest.urlopen(request, timeout=self.timeout) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    self.session_id = session
                raw = response.read().decode("utf-8", errors="replace")
                content_type = (response.headers.get("Content-Type") or "").lower()
        except urlerror.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise MCPServerError(f"{self.name}: HTTP {exc.code} from {self.url}: {detail}") from exc
        except (urlerror.URLError, OSError) as exc:
            raise MCPServerError(f"{self.name}: cannot reach {self.url}: {exc}") from exc
        messages = _parse_http_body(raw, content_type)
        if not messages:
            # A notification or an accepted-but-empty response: nothing to deliver.
            return
        for message in messages:
            self._dispatch_incoming(message)

    def alive(self) -> bool:
        return not self.closed

    def close(self) -> None:
        self.closed = True
        self._fail_all(MCPServerError(f"{self.name}: client closed"))


def _parse_http_body(raw: str, content_type: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if not text:
        return []
    if "text/event-stream" in content_type or text.startswith("event:") or text.startswith("data:"):
        messages: list[dict[str, Any]] = []
        for block in text.replace("\r\n", "\n").split("\n\n"):
            data_lines = [line[5:].strip() for line in block.split("\n") if line.startswith("data:")]
            payload = "\n".join(data_lines).strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise MCPProtocolError(f"invalid SSE JSON payload: {exc}") from exc
            messages.append(parsed)
        return messages
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MCPProtocolError(f"response is not JSON: {exc}") from exc
    if isinstance(parsed, list):
        return [m for m in parsed if isinstance(m, dict)]
    return [parsed] if isinstance(parsed, dict) else []


__all__ = [
    "CLIENT_NAME",
    "PROTOCOL_VERSION",
    "McpCallResult",
    "McpHttpClient",
    "McpStdioClient",
    "McpToolInfo",
]
