"""Bounded JSON-RPC queues, caller deadlines, dispatch and connection failure state.

One transient daemon sender serializes transport I/O. A caller's deadline includes
queueing and sending; it is not a guarantee that DNS/OS I/O can be forcibly cancelled.
"""

from __future__ import annotations

import json
import math
import queue
import threading
import time
from typing import Any, Mapping

from archx_agent.helpers.exceptions import (
    MCPProtocolError,
    MCPServerError,
    MCPTimeoutError,
    ValidationError,
)
from archx_agent.helpers.processes import positive_integer
from .records import _Pending
from .surface import McpSurfaceMixin


def positive_timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("MCP timeout must be a positive finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValidationError("MCP timeout must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValidationError("MCP timeout must be a positive finite number")
    return number


class _JsonRpcBase(McpSurfaceMixin):
    """Caller-visible state; subclasses implement only wire I/O and cleanup hooks."""

    def __init__(
        self,
        *,
        name: str,
        timeout: float = 20.0,
        max_message_bytes: int = 8_000_000,
        max_pending: int = 32,
    ) -> None:
        self.timeout = positive_timeout(timeout)
        try:
            self.max_message_bytes = positive_integer(
                max_message_bytes, "max_message_bytes"
            )
            self.max_pending = positive_integer(max_pending, "max_pending")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        self.name = name
        self._next_id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._outgoing: queue.Queue = queue.Queue(maxsize=max_pending)
        self._sender: threading.Thread | None = None
        self.protocol_version: str | None = None
        self.server_info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}
        self.closed = False
        self._terminal_error: Exception | None = None

    def _new_id(self) -> int:
        with self._lock:
            self._next_id += 1
            return self._next_id

    def _send(
        self, payload: bytes, deadline: float
    ) -> None:  # pragma: no cover - transport hook
        raise NotImplementedError

    def _stop_transport(self) -> None:
        """Optional transport cleanup; must not block on a buffered reader lock."""

    def _submit(self, message: dict[str, Any], deadline: float) -> None:
        try:
            payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
            raise MCPProtocolError(
                f"{self.name}: request must contain JSON data"
            ) from exc
        if len(payload) > self.max_message_bytes:
            raise MCPProtocolError(
                f"{self.name}: outgoing message exceeds {self.max_message_bytes} bytes"
            )
        with self._lock:
            if self.closed:
                raise self._terminal_error or MCPServerError(
                    f"{self.name}: client closed"
                )
            try:
                self._outgoing.put_nowait((payload, deadline))
            except queue.Full as exc:
                raise MCPServerError(f"{self.name}: outbound queue is full") from exc
            if self._sender is None:
                self._sender = threading.Thread(
                    target=self._send_loop, name=f"{self.name}-sender", daemon=True
                )
                try:
                    self._sender.start()
                except RuntimeError as exc:
                    self._sender = None
                    self._outgoing.get_nowait()
                    self._outgoing.task_done()
                    raise MCPServerError(
                        f"{self.name}: cannot start sender thread"
                    ) from exc

    def _write(self, message: dict[str, Any]) -> None:
        self._submit(message, time.monotonic() + self.timeout)

    def _send_loop(self) -> None:
        while True:
            try:
                payload, deadline = self._outgoing.get(timeout=0.1)
            except queue.Empty:
                with self._lock:
                    if self._outgoing.empty():
                        self._sender = None
                        return
                continue
            try:
                if not self.closed:
                    if time.monotonic() >= deadline:
                        raise MCPTimeoutError(
                            f"{self.name}: message expired before sending"
                        )
                    self._send(payload, deadline)
            except (
                Exception
            ) as exc:  # transport thread must wake callers, never die silently
                error = (
                    exc
                    if isinstance(exc, MCPServerError)
                    else MCPServerError(
                        f"{self.name}: transport failed: {type(exc).__name__}"
                    )
                )
                self._abort(error)
            finally:
                self._outgoing.task_done()

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        limit = self.timeout if timeout is None else positive_timeout(timeout)
        deadline = time.monotonic() + limit
        request_id = self._new_id()
        pending = _Pending(request_id)
        with self._lock:
            if self.closed:
                raise self._terminal_error or MCPServerError(
                    f"{self.name}: client closed"
                )
            if len(self._pending) >= self.max_pending:
                raise MCPServerError(f"{self.name}: too many pending requests")
            self._pending[request_id] = pending
        try:
            self._submit(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": dict(params or {}),
                },
                deadline,
            )
            if not pending.event.wait(max(0.0, deadline - time.monotonic())):
                error = MCPTimeoutError(
                    f"{self.name}: no answer to {method} within {limit}s"
                )
                self._abort(error)
                raise error
            if pending.error is not None:
                raise pending.error
            return pending.result or {}
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = dict(params)
        self._write(payload)

    def _dispatch_incoming(self, message: dict[str, Any]) -> None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise MCPProtocolError(f"{self.name}: expected a JSON-RPC 2.0 object")
        if "method" in message and (
            not isinstance(message["method"], str)
            or not message["method"]
            or "result" in message
            or "error" in message
        ):
            raise MCPProtocolError(f"{self.name}: malformed JSON-RPC method")
        if ("result" in message or "error" in message) and "id" not in message:
            raise MCPProtocolError(f"{self.name}: response has no id")
        if "id" in message and ("result" in message or "error" in message):
            if "result" in message and "error" in message:
                raise MCPProtocolError(
                    f"{self.name}: response has both result and error"
                )
            request_id = message["id"]
            if isinstance(request_id, bool) or not isinstance(
                request_id, (int, str, type(None))
            ):
                raise MCPProtocolError(f"{self.name}: invalid response id")
            error = message.get("error")
            if "error" in message and (
                not isinstance(error, dict)
                or not isinstance(error.get("message"), str)
                or isinstance(error.get("code"), bool)
                or not isinstance(error.get("code"), int)
            ):
                raise MCPProtocolError(f"{self.name}: malformed JSON-RPC error")
            with self._lock:
                pending = (
                    self._pending.get(request_id)
                    if isinstance(request_id, int)
                    else None
                )
            if pending is None:
                return  # a late or unsolicited response cannot satisfy another request
            if error is not None:
                pending.error = MCPServerError(
                    f"{self.name}: {error['message']} (code {error['code']})"
                )
            else:
                result = message.get("result")
                pending.result = (
                    result if isinstance(result, dict) else {"value": result}
                )
            pending.event.set()
            return
        if "id" in message and "method" in message:
            request_id = message["id"]
            if isinstance(request_id, bool) or not isinstance(
                request_id, (int, str, type(None))
            ):
                raise MCPProtocolError(f"{self.name}: invalid server request id")
            if message["method"] == "ping":
                self._write({"jsonrpc": "2.0", "id": request_id, "result": {}})
            else:
                self._write(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"method not found: {message['method']}",
                        },
                    }
                )
            return
        if "id" in message or "method" not in message:
            raise MCPProtocolError(f"{self.name}: malformed JSON-RPC envelope")
        # Unknown notifications do not trigger tool execution.

    def _fail_all(self, exc: Exception) -> None:
        with self._lock:
            pending, self._pending = self._pending, {}
        for item in pending.values():
            item.error = exc
            item.event.set()

    def _abort(self, exc: Exception) -> None:
        with self._lock:
            already_closed = self.closed
            self.closed = True
            if not already_closed:
                self._terminal_error = exc
        while True:
            try:
                self._outgoing.get_nowait()
                self._outgoing.task_done()
            except queue.Empty:
                break
        self._fail_all(exc)
        if not already_closed:
            self._stop_transport()

    def alive(self) -> bool:
        return not self.closed

    def close(self, *, timeout: float = 3.0) -> None:
        positive_timeout(timeout)
        self._abort(MCPServerError(f"{self.name}: client closed"))
