"""MCP binary stdio framing, bounded diagnostics and POSIX child-group cleanup."""

from __future__ import annotations
import json
import os
import signal
import subprocess
import threading
import time
from collections import deque
from typing import Iterable, Mapping
from archx_agent.helpers.exceptions import (
    MCPProtocolError,
    MCPServerError,
    ValidationError,
)
from archx_agent.helpers.processes import positive_integer
from .base import _JsonRpcBase


def _lines(stream, limit: int):
    buffer = bytearray()
    while True:
        chunk = stream.read(min(65_536, limit + 1 - len(buffer)))
        if not chunk:
            if buffer:
                yield bytes(buffer)
            return
        buffer.extend(chunk)
        while True:
            end = buffer.find(b"\n")
            if end < 0:
                break
            if end > limit:
                raise MCPProtocolError(f"stdio message exceeds {limit} bytes")
            line = bytes(buffer[:end])
            del buffer[: end + 1]
            yield line
        if len(buffer) > limit:
            raise MCPProtocolError(f"stdio message exceeds {limit} bytes")


class McpStdioClient(_JsonRpcBase):
    def __init__(
        self,
        command: Iterable[str],
        *,
        name: str = "mcp",
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = 20.0,
        max_message_bytes: int = 8_000_000,
        max_pending: int = 32,
    ) -> None:
        if isinstance(command, (str, bytes)):
            raise ValidationError("MCP command must be an argv sequence")
        try:
            argv = list(command)
        except TypeError as exc:
            raise ValidationError("MCP command must be an argv sequence") from exc
        if (
            not argv
            or any(not isinstance(arg, str) or "\0" in arg for arg in argv)
            or not argv[0]
        ):
            raise ValidationError(
                "MCP command needs a nonempty executable and NUL-free string arguments"
            )
        super().__init__(
            name=name,
            timeout=timeout,
            max_message_bytes=max_message_bytes,
            max_pending=max_pending,
        )
        self.argv = argv
        try:
            child_env = dict(os.environ if env is None else env)
            if any(
                not isinstance(k, str)
                or not k
                or "=" in k
                or "\0" in k
                or not isinstance(v, str)
                or "\0" in v
                for k, v in child_env.items()
            ):
                raise ValueError("invalid environment")
            self.process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=child_env,
                bufsize=0,
                start_new_session=os.name == "posix",
            )
        except (OSError, ValueError, TypeError) as exc:
            raise MCPServerError(f"{name}: cannot start {argv[0]!r}: {exc}") from exc
        self._stderr_lines: deque[str] = deque(maxlen=200)
        self._stderr_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._reader = threading.Thread(
            target=self._read_loop, name=f"{name}-reader", daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, name=f"{name}-stderr", daemon=True
        )
        try:
            self._stderr_thread.start()
            self._reader.start()
        except RuntimeError as exc:
            error = MCPServerError(
                f"{self.name}: cannot start transport reader threads"
            )
            self._abort(error)
            raise error from exc

    def _send(self, payload: bytes, deadline: float) -> None:
        if self.closed or self.process.poll() is not None:
            raise MCPServerError(self._exit_message())
        assert self.process.stdin is not None
        data = memoryview(payload + b"\n")
        while data:
            if self.closed or time.monotonic() >= deadline:
                raise MCPServerError(f"{self.name}: connection closed while writing")
            written = self.process.stdin.write(data)
            if not written:
                raise MCPServerError(f"{self.name}: stdin closed while writing")
            data = data[written:]

    def _read_loop(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in _lines(self.process.stdout, self.max_message_bytes):
                if not line.strip():
                    continue
                try:
                    message = json.loads(line.decode("utf-8"))
                except (ValueError, RecursionError, UnicodeError) as exc:
                    raise MCPProtocolError(
                        f"{self.name}: invalid JSON/UTF-8 on stdout"
                    ) from exc
                self._dispatch_incoming(message)
        except Exception as exc:
            if not self.closed:
                error = (
                    exc
                    if isinstance(exc, MCPServerError)
                    else MCPServerError(
                        f"{self.name}: stdout failed: {type(exc).__name__}"
                    )
                )
                self._abort(error)
        finally:
            if not self.closed:
                self._abort(MCPServerError(self._exit_message()))

    def _stderr_loop(self) -> None:
        assert self.process.stderr is not None
        try:
            while chunk := self.process.stderr.read(4096):
                # A diagnostic entry is never larger than one 4096-byte chunk.
                parts = chunk.decode("utf-8", errors="replace").splitlines()
                with self._stderr_lock:
                    self._stderr_lines.extend(parts)
        except (OSError, ValueError):
            pass  # shutdown can close raw descriptors while this daemon is reading

    def _exit_message(self) -> str:
        code = self.process.poll()
        if code is None:
            try:
                code = self.process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
        detail = "; ".join(self.stderr_tail(3))
        if code is None:
            return f"{self.name}: the server connection closed unexpectedly"
        message = f"{self.name}: the server exited with status {code}"
        return f"{message} ({detail})" if detail else message

    def stderr_tail(self, lines: int = 5) -> list[str]:
        try:
            positive_integer(lines, "lines")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        with self._stderr_lock:
            return list(self._stderr_lines)[-lines:]

    def alive(self) -> bool:
        return not self.closed and self.process.poll() is None

    def _stop_transport(self) -> None:
        with self._lifecycle_lock:
            try:
                if os.name == "posix":
                    os.killpg(self.process.pid, signal.SIGKILL)
                elif self.process.poll() is None:
                    self.process.kill()
            except ProcessLookupError:
                pass
            except OSError as exc:
                with self._stderr_lock:
                    self._stderr_lines.append(
                        f"[process cleanup failed: {type(exc).__name__}]"
                    )
            for stream in (
                self.process.stdin,
                self.process.stdout,
                self.process.stderr,
            ):
                if stream is not None:
                    try:
                        stream.close()  # raw FileIO: no buffered-reader lock to acquire
                    except OSError:
                        pass
            try:
                self.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass  # exceptional OS/uninterruptible I/O; caller must still return
