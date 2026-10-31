"""Runs an extension-provided program with a JSON request/response contract.

An extension tool is a program in the extension's own directory. It receives one JSON
object on stdin and must print one JSON object on stdout:

    {"arguments": {...}, "tool": "name", "extension": "name"}   ->   {"result": {...}}

Why a program and not imported Python? Because importing untrusted code into the agent
process would give it the database, the event store and every manager. A subprocess gets
bounded-memory output handling and POSIX timeout group cleanup like ``shell.run``.
The rebuilt environment and checked cwd are not an OS filesystem sandbox; spooling
has no hard disk quota and Windows cleanup only kills the direct process.

This module executes. Trust decisions and permission checks happen before it is called.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from archx_agent.helpers.processes import run_spooled, positive_integer

from archx_agent.helpers.exceptions import (
    ExtensionError,
    ToolTimeoutError,
    ToolValidationError,
)


@dataclass
class ExtensionRuntime:
    max_output_bytes: int = 200_000
    timeout_seconds: int = 60

    def __post_init__(self) -> None:
        try:
            positive_integer(self.max_output_bytes, "max_output_bytes")
            positive_integer(self.timeout_seconds, "timeout_seconds")
        except ValueError as exc:
            raise ToolValidationError(str(exc)) from exc

    def run(
        self,
        argv: list[str],
        request: dict,
        *,
        cwd: str,
        env_extra: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> dict:
        if (
            not isinstance(argv, list)
            or not argv
            or not argv[0]
            or any(not isinstance(arg, str) or "\0" in arg for arg in argv)
        ):
            raise ToolValidationError(
                "an extension tool needs a command (an argv list)"
            )
        if not isinstance(request, dict):
            raise ToolValidationError("extension request must be a JSON object")
        try:
            workdir = Path(cwd).resolve()
            if not workdir.is_dir():
                raise ExtensionError(f"extension directory missing: {workdir}")
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            raise ExtensionError("extension directory cannot be resolved") from exc
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(workdir),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TMPDIR": tempfile.gettempdir(),
        }
        if env_extra is not None and not isinstance(env_extra, dict):
            raise ToolValidationError("extension environment must be an object")
        extra = {str(k): str(v) for k, v in (env_extra or {}).items()}
        if any(
            not key or "=" in key or "\0" in key or "\0" in value
            for key, value in extra.items()
        ):
            raise ToolValidationError("invalid extension environment key or value")
        env.update(extra)
        try:
            limit = positive_integer(
                self.timeout_seconds if timeout is None else timeout, "timeout"
            )
            payload = json.dumps(request).encode("utf-8")
        except (ValueError, TypeError, RecursionError) as exc:
            raise ToolValidationError(
                f"invalid extension request or limit: {exc}"
            ) from exc
        try:
            result = run_spooled(
                argv,
                cwd=str(workdir),
                env=env,
                input_bytes=payload,
                timeout=limit,
                max_output_bytes=self.max_output_bytes,
            )
        except OSError as exc:
            raise ExtensionError(
                f"cannot run extension tool {argv[0]!r}: {exc.strerror or exc}"
            ) from exc
        if result.timed_out:
            raise ToolTimeoutError(
                f"extension tool timed out after {limit}s: {' '.join(argv)}"
            )
        # Never parse a clipped prefix as a complete response: a valid JSON prefix
        # followed by excessive whitespace/data is still an oversized response.
        if len(result.stdout) > self.max_output_bytes:
            raise ExtensionError(
                f"extension stdout exceeds {self.max_output_bytes} bytes"
            )
        try:
            stdout = result.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExtensionError("extension stdout must be UTF-8 JSON") from exc
        stderr = result.stderr[: self.max_output_bytes].decode(
            "utf-8", errors="replace"
        )
        duration_ms = result.duration_ms
        if result.exit_code != 0:
            raise ExtensionError(
                f"extension tool exited with {result.exit_code}"
                + (f": {stderr.strip()[:300]}" if stderr.strip() else "")
            )
        text = stdout.strip()
        if not text:
            raise ExtensionError(
                "extension tool printed nothing (expected one JSON object)"
            )
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ExtensionError(
                f"extension tool did not print JSON: {exc} (first 200 chars: {text[:200]!r})"
            ) from exc
        if not isinstance(parsed, dict):
            raise ExtensionError("extension tool must print a JSON object")
        parsed.setdefault("duration_ms", duration_ms)
        if stderr.strip():
            parsed.setdefault("stderr", stderr.strip()[:2000])
        if len(result.stderr) > self.max_output_bytes:
            parsed["stderr_truncated"] = True
        return parsed


__all__ = ["ExtensionRuntime"]
