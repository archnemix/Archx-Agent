"""Runs an extension-provided program with a JSON request/response contract.

An extension tool is a program in the extension's own directory. It receives one JSON
object on stdin and must print one JSON object on stdout:

    {"arguments": {...}, "tool": "name", "extension": "name"}   ->   {"result": {...}}

Why a program and not imported Python? Because importing untrusted code into the agent
process would give it the database, the event store and every manager. A subprocess gets
the same treatment as ``shell.run``: no inherited environment beyond PATH/HOME/LANG/TMPDIR,
no shell, a hard timeout, capped output, and a working directory inside the extension.

This module executes. Trust decisions and permission checks happen before it is called.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from archx_agent.helpers.exceptions import (
    ExtensionError,
    ToolTimeoutError,
    ToolValidationError,
)


@dataclass
class ExtensionRuntime:
    max_output_bytes: int = 200_000
    timeout_seconds: int = 60

    def run(
        self,
        argv: list[str],
        request: dict,
        *,
        cwd: str,
        env_extra: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> dict:
        if not argv:
            raise ToolValidationError("an extension tool needs a command (an argv list)")
        workdir = Path(cwd).resolve()
        if not workdir.is_dir():
            raise ExtensionError(f"extension directory missing: {workdir}")
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(workdir),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TMPDIR": tempfile.gettempdir(),
        }
        env.update({str(k): str(v) for k, v in (env_extra or {}).items()})
        limit = int(timeout or self.timeout_seconds)
        payload = json.dumps(request)
        started = time.perf_counter()
        try:
            completed = subprocess.run(  # noqa: S603 - argv list, no shell
                argv,
                cwd=str(workdir),
                env=env,
                input=payload,
                capture_output=True,
                text=True,
                timeout=limit,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolTimeoutError(
                f"extension tool timed out after {limit}s: {' '.join(argv)}"
            ) from exc
        except OSError as exc:
            raise ExtensionError(f"cannot start extension tool {argv[0]!r}: {exc.strerror or exc}") from exc
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        stdout = completed.stdout[: self.max_output_bytes]
        stderr = completed.stderr[: self.max_output_bytes]
        if completed.returncode != 0:
            raise ExtensionError(
                f"extension tool exited with {completed.returncode}"
                + (f": {stderr.strip()[:300]}" if stderr.strip() else "")
            )
        text = stdout.strip()
        if not text:
            raise ExtensionError("extension tool printed nothing (expected one JSON object)")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExtensionError(
                f"extension tool did not print JSON: {exc} (first 200 chars: {text[:200]!r})"
            ) from exc
        if not isinstance(parsed, dict):
            raise ExtensionError("extension tool must print a JSON object")
        parsed.setdefault("duration_ms", duration_ms)
        if stderr.strip():
            parsed.setdefault("stderr", stderr.strip()[:2000])
        return parsed


__all__ = ["ExtensionRuntime"]
