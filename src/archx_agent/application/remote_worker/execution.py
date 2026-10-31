"""Opt-in trusted shell execution on the worker's OS account, not a sandbox."""

from __future__ import annotations

import os
from typing import Any

from archx_agent.helpers.processes import positive_integer, run_spooled
from .protocol import PROTOCOL

OUTPUT_BYTES = 65_536


class WorkerExecutionMixin:
    def exec_refusal(self) -> str | None:
        if not self.allow_exec:
            return "this worker does not run commands: start it with `--allow-exec` if you mean to let another machine execute here"
        return None

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        common = {"protocol": PROTOCOL, "machine": self.name}
        refusal = self.exec_refusal()
        if refusal:
            return {"refused": refusal, **common}
        if not isinstance(request, dict):
            return {"refused": "execution request must be an object", **common}
        command = request.get("command")
        if not isinstance(command, str) or not command.strip() or "\0" in command:
            return {
                "refused": "a nonempty text command without NUL is required",
                **common,
            }
        try:
            limit = min(positive_integer(request.get("timeout", 60), "timeout"), 900)
        except ValueError as exc:
            return {"refused": str(exc), **common}
        relative = request.get("cwd", ".")
        if not isinstance(relative, str):
            return {"refused": "cwd must be a path string", **common}
        cwd = self._inside(relative)
        if cwd is None:
            return {
                "refused": "the working directory must stay inside this worker's work directory",
                **common,
            }
        try:
            result = run_spooled(
                command,
                shell=True,
                cwd=str(cwd),
                timeout=limit,
                max_output_bytes=OUTPUT_BYTES,
                env={
                    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                    "HOME": str(self.workdir),
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                },
            )
        except (OSError, ValueError) as exc:
            return {
                **common,
                "exit_code": 1,
                "timed_out": False,
                "stdout": "",
                "stderr": f"worker execution failed: {type(exc).__name__}",
                "truncated": False,
            }
        return {
            **common,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "stdout": result.stdout[:OUTPUT_BYTES].decode("utf-8", errors="replace"),
            "stderr": result.stderr[:OUTPUT_BYTES].decode("utf-8", errors="replace"),
            "truncated": len(result.stdout) > OUTPUT_BYTES
            or len(result.stderr) > OUTPUT_BYTES,
            "duration_ms": result.duration_ms,
            "cwd": str(cwd.relative_to(self.workdir)) if cwd != self.workdir else ".",
        }
