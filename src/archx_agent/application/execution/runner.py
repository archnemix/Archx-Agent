"""Workflow execution and outcome recording for execution targets."""

from __future__ import annotations

import shlex
from typing import Any

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.managers.execution import ExecutionTarget
from archx_agent.managers.tools import ToolContext
from archx_agent.application.execution.invocations import (
    build_invocation,
    sandbox_config,
)


class ExecutionServiceRunnerMixin:
    """Runner responsibility for ExecutionService."""

    def run(
        self,
        command: str,
        *,
        target: str | None = None,
        cwd: str | None = None,
        timeout: int | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        resolved = self._resolve(target)
        reasons = self.blockers(resolved)
        if reasons:
            row = self.manager.begin(
                kind=resolved.kind,
                command=command,
                target_id=resolved.id,
                cwd=cwd,
                invocation=None,
                task_id=task_id,
            )
            finished = self.manager.finish(
                row.id, status="refused", note="; ".join(reasons), exit_code=None
            )
            payload = self._view(finished)
            payload["reasons"] = reasons
            return payload

        workdir = cwd or str(self.ws.config.get("execution.project", "") or ".")
        if resolved.kind == "remote":
            return self._run_remote(resolved, command, workdir, timeout, task_id)

        try:
            invocation, meta = build_invocation(resolved, command, workdir)
        except ValidationError as exc:
            row = self.manager.begin(
                kind=resolved.kind,
                command=command,
                target_id=resolved.id,
                cwd=workdir,
                task_id=task_id,
            )
            finished = self.manager.finish(row.id, status="refused", note=str(exc))
            payload = self._view(finished)
            payload["reasons"] = [str(exc)]
            return payload
        if resolved.kind == "windows-sandbox":
            return self._run_windows_sandbox(
                resolved, command, workdir, timeout, task_id, meta
            )

        limit = int(timeout or self.ws.config.get("execution.timeout", 60) or 60)
        row = self.manager.begin(
            kind=resolved.kind,
            command=command,
            target_id=resolved.id,
            cwd=workdir,
            invocation=invocation,
            task_id=task_id,
        )
        try:
            result = self.ws.tools.execute(
                "shell.run",
                {"command": invocation, "cwd": workdir, "timeout": limit},
                context=ToolContext(purpose=f"exec {resolved.name}: {command[:60]}"),
                requester="execution",
            )
        except (ApprovalRequiredError, PermissionDeniedError, ToolError) as exc:
            # The permission centre refused, so nothing ran. That is a row with the reason and the
            # approval id in it, not an exception that loses the attempt.
            approval = getattr(exc, "approval_id", None)
            detail = str(exc) if not approval else f"{exc}"
            finished = self.manager.finish(row.id, status="refused", note=detail)
            payload = self._view(finished)
            payload["reasons"] = [detail]
            payload["approval_id"] = approval
            return payload
        if result.status == "denied":
            approval = getattr(result, "approval_id", None)
            detail = result.error or "shell.run was refused"
            finished = self.manager.finish(row.id, status="refused", note=detail)
            payload = self._view(finished)
            payload["reasons"] = [detail]
            payload["approval_id"] = approval
            return payload
        payload = dict(result.result or {})
        status = (
            "timeout"
            if payload.get("timed_out")
            else ("ok" if int(payload.get("exit_code") or 0) == 0 else "failed")
        )
        artifact_paths = self._write_outputs(row.id, payload)
        finished = self.manager.finish(
            row.id,
            status=status,
            exit_code=payload.get("exit_code"),
            duration_ms=payload.get("duration_ms"),
            stdout=str(payload.get("stdout") or ""),
            stderr=str(payload.get("stderr") or ""),
            stdout_path=artifact_paths.get("stdout"),
            stderr_path=artifact_paths.get("stderr"),
            truncated=bool(payload.get("truncated")),
            note=meta.get("note"),
        )
        return self._view(finished)

    def _write_outputs(self, run_id: str, payload: dict[str, Any]) -> dict[str, str]:
        """Keep stdout and stderr as artifacts, so a run's evidence outlives the terminal."""
        paths: dict[str, str] = {}
        for stream in ("stdout", "stderr"):
            text = str(payload.get(stream) or "")
            if not text:
                continue
            try:
                written = self._execute(
                    "fs.write",
                    {
                        "path": f"{run_id}.{stream}.txt",
                        "content": text,
                        "create_parents": True,
                    },
                    f"execution {stream} {run_id}",
                )
            except (ToolError, PermissionDeniedError):
                # Losing the copy must not lose the run: the row keeps the text either way.
                continue
            paths[stream] = str((written.result or {}).get("path") or "")
        return paths

    def _run_windows_sandbox(
        self,
        target: ExecutionTarget,
        command: str,
        workdir: str,
        timeout: int | None,
        task_id: str | None,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        probe = self.probe("windows-sandbox")
        config = sandbox_config(target, command, host_dir=workdir)
        row = self.manager.begin(
            kind=target.kind,
            command=command,
            target_id=target.id,
            cwd=workdir,
            invocation="WindowsSandbox.exe <generated>.wsb",
            task_id=task_id,
        )
        if not probe["available"]:
            finished = self.manager.finish(
                row.id,
                status="refused",
                note="; ".join(probe["why_not"]),
                detached=True,
            )
            payload = self._view(finished)
            payload["reasons"] = probe["why_not"]
            return payload
        written = self._execute(
            "fs.write",
            {"path": f"{row.id}.wsb", "content": config, "create_parents": True},
            f"windows sandbox config {row.id}",
        )
        wsb = str((written.result or {}).get("path") or f"{row.id}.wsb")
        launch = f"WindowsSandbox.exe {shlex.quote(workdir)}/{wsb}"
        self.ws.tools.execute(
            "shell.run",
            {"command": launch, "cwd": workdir, "timeout": int(timeout or 30)},
            context=ToolContext(purpose=f"windows sandbox launch {row.id}"),
            requester="execution",
        )
        finished = self.manager.finish(
            row.id,
            status="detached",
            detached=True,
            note=(
                f"{meta.get('note')}; the generated config is {wsb} and the output lands in "
                f"{workdir}/archx-exec.log when the sandbox writes it"
            ),
        )
        return self._view(finished)
