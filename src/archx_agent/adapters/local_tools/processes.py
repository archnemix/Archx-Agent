"""LocalToolRuntime processes."""

from __future__ import annotations

import os
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ToolError,
    ToolValidationError,
)
from archx_agent.adapters.local_tools.output import _clip
from archx_agent.helpers.processes import run_spooled


class LocalToolRuntimeProcessesMixin:
    """Processes responsibility for LocalToolRuntime."""

    def run(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        limit = self.timeout_seconds if timeout is None else timeout
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ToolValidationError("timeout must be a positive integer")
        text = (command or "").strip()
        if not text:
            raise ToolValidationError("a command is required")
        try:
            argv = shlex.split(text)
        except ValueError as exc:
            raise ToolValidationError(f"cannot parse the command: {exc}") from exc
        if not argv:
            raise ToolValidationError("a command is required")
        program = Path(argv[0]).name
        if program in set(self.denylist):
            raise ToolError(
                f"{program!r} is on the shell denylist (tools.shell_denylist); "
                "remove it from the list deliberately if you really need it"
            )
        workdir = self.resolve(cwd or ".") if cwd else self._resolved_roots[0]
        if workdir.exists() and not workdir.is_dir():
            raise ToolError(f"cwd is not a directory: {self.relative(workdir)}")
        if not workdir.exists():
            workdir.mkdir(parents=True, exist_ok=True)
        executable = argv[0]
        if shutil.which(executable) is None and not Path(executable).exists():
            raise ToolError(f"command not found: {executable}")
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": self.home or str(workdir),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TMPDIR": tempfile.gettempdir(),
        }
        try:
            result = run_spooled(
                argv,
                cwd=str(workdir),
                env=env,
                timeout=limit,
                max_output_bytes=self.max_output_bytes,
            )
        except OSError as exc:
            raise ToolError(
                f"could not run {executable!r}: {exc.strerror or exc}"
            ) from exc
        stdout, stderr = result.stdout, result.stderr
        timed_out, returncode, duration_ms = (
            result.timed_out,
            result.exit_code,
            result.duration_ms,
        )
        out_text, out_truncated = _clip(stdout, self.max_output_bytes)
        err_text, err_truncated = _clip(stderr, self.max_output_bytes)
        if timed_out:
            stderr_tail = (err_text + f"\n[killed after {limit}s]").strip()
        else:
            stderr_tail = err_text
        return {
            "argv": argv,
            "cwd": self.relative(workdir),
            "exit_code": returncode,
            "stdout": out_text,
            "stderr": stderr_tail,
            "timed_out": timed_out,
            "timeout_seconds": limit,
            "duration_ms": duration_ms,
            "truncated": out_truncated or err_truncated,
        }
