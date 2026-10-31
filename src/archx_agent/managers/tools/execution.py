"""Execution operations for tool execution."""

from __future__ import annotations

from typing import Any, Mapping

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolValidationError,
)
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.permissions import PermissionDecision
from archx_agent.managers.tools.records import ToolSpec, ToolContext, ToolRun
from archx_agent.managers.tools.validation import _coerce
from archx_agent.managers.tools.outcomes import _result_ok, _failure_reason, _elapsed_ms


class ToolManagerExecutionMixin:
    """Execution responsibility for ToolManager."""

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        dry_run: bool = False,
        context: ToolContext | None = None,
        requester: str = "tool",
        permission_subject: str | None = None,
    ) -> ToolRun:
        """Run a tool.

        ``permission_subject`` defaults to the tool's own name. The MCP server passes a
        different subject, so a grant for the tool does not automatically authorise a
        remote caller that happens to ask for it.
        """
        spec = self.spec(name)
        context = context or ToolContext()
        args = _coerce(dict(arguments or {}), spec)
        if dry_run and not spec.supports_dry_run:
            raise ToolValidationError(
                f"{spec.name} cannot be dry-run (it has no preview)"
            )

        run = ToolRun(
            id=new_id("tr_"),
            tool=spec.name,
            status="running",
            arguments=args,
            started_at=iso_now(),
            dry_run=dry_run,
        )

        blocked = self._preflight(spec, args)
        if blocked is not None:
            return self._refuse(
                run, spec, blocked, context, approval_id=None, refused_by="denylist"
            )

        decision: PermissionDecision | None = None
        if spec.capability:
            decision = self.permissions.check(
                spec.capability,
                subject=permission_subject or spec.name,
                conversation_id=context.conversation_id,
                task_id=context.task_id,
                project_id=context.project_id,
                consume=True,
                purpose=context.purpose or f"{spec.name} via {requester}",
            )
            if not decision.allowed:
                return self._refuse(
                    run,
                    spec,
                    decision.reason,
                    context,
                    approval_id=decision.approval_id,
                    refused_by="permission",
                )

        self._write(
            "tool.record",
            {
                "run": {
                    **run.to_dict(),
                    "task_id": context.task_id,
                    "permission_id": decision.grant_id if decision else None,
                    "approval_id": decision.approval_id if decision else None,
                }
            },
        )
        event_id = self.trace(
            "tool_call",
            spec.name,
            status="running",
            conversation_id=context.conversation_id,
            task_id=context.task_id,
            project_id=context.project_id,
            payload={
                "run_id": run.id,
                "tool": spec.name,
                "arguments": args,
                "capability": spec.capability,
                "grant_id": decision.grant_id if decision else None,
                "dry_run": dry_run,
            },
        )
        run.permission_id = decision.grant_id if decision else None
        run.decision = decision.reason if decision else "no capability needed"

        failure: Exception | None = None
        try:
            result = self._dispatch(spec, args, dry_run=dry_run)
            run.result = result
            run.truncated = bool(result.get("truncated"))
            run.status = "succeeded" if _result_ok(spec, result) else "failed"
            if run.status == "failed" and not run.error:
                run.error = _failure_reason(spec, result)
        except Exception as exc:  # noqa: BLE001 - the run must be closed before re-raising
            failure = exc
            run.status = "failed"
            run.error = getattr(exc, "message", None) or str(exc)
            run.result = None
        run.ended_at = iso_now()
        run.duration_ms = _elapsed_ms(run.started_at, run.ended_at)
        self._write(
            "tool.finish",
            {
                "id": run.id,
                "status": run.status,
                "result": run.result,
                "ended_at": run.ended_at,
                "duration_ms": run.duration_ms,
                "error": run.error,
                "permission_id": run.permission_id,
                "approval_id": None,
                "trace_event_id": event_id,
                "truncated": run.truncated,
            },
        )
        self.trace(
            "tool_call",
            spec.name,
            status=run.status,
            conversation_id=context.conversation_id,
            task_id=context.task_id,
            project_id=context.project_id,
            duration_ms=run.duration_ms,
            parent_id=event_id,
            error=run.error,
            payload={
                "run_id": run.id,
                "tool": spec.name,
                "dry_run": dry_run,
                "result": run.result,
                "permission_id": run.permission_id,
            },
        )
        self._record_file_change(spec, args, run, context)
        self._link_task(spec, context, run)
        run.seq = self.get_run(run.id).get("seq")
        if failure is not None:
            failure.run = run  # type: ignore[attr-defined]
            raise failure
        return run

    def _preflight(self, spec: ToolSpec, args: dict[str, Any]) -> str | None:
        if spec.name == "shell.run":
            import shlex
            from pathlib import Path

            command = str(args.get("command") or "")
            try:
                argv = shlex.split(command)
            except ValueError:
                return None  # the runtime reports the parse error
            if argv:
                program = Path(argv[0]).name
                denylist = {
                    str(x) for x in (self._cfg("tools.shell_denylist", []) or [])
                }
                if program in denylist:
                    return (
                        f"{program!r} is on the shell denylist (tools.shell_denylist); "
                        "this cannot be approved"
                    )
        return None

    def _refuse(
        self,
        run: ToolRun,
        spec: ToolSpec,
        reason: str,
        context: ToolContext,
        *,
        approval_id: str | None,
        refused_by: str,
    ) -> ToolRun:
        run.status = "denied"
        run.error = reason
        run.approval_id = approval_id
        run.ended_at = iso_now()
        run.duration_ms = _elapsed_ms(run.started_at, run.ended_at)
        event_id = self.trace(
            "permission",
            "denied" if refused_by == "permission" else "blocked",
            status="denied",
            conversation_id=context.conversation_id,
            task_id=context.task_id,
            project_id=context.project_id,
            error=reason,
            payload={
                "run_id": run.id,
                "tool": spec.name,
                "capability": spec.capability,
                "arguments": run.arguments,
                "reason": reason,
                "approval_id": approval_id,
                "refused_by": refused_by,
            },
        )
        self._write(
            "tool.record",
            {
                "run": {
                    **run.to_dict(),
                    "task_id": context.task_id,
                    "trace_event_id": event_id,
                }
            },
        )
        self.trace(
            "tool_call",
            spec.name,
            status="denied",
            conversation_id=context.conversation_id,
            task_id=context.task_id,
            project_id=context.project_id,
            parent_id=event_id,
            error=reason,
            payload={
                "run_id": run.id,
                "approval_id": approval_id,
                "refused_by": refused_by,
            },
        )
        self._link_task(spec, context, run)
        run.seq = self.get_run(run.id).get("seq")
        message = f"{spec.name}: {reason}"
        if approval_id:
            exc: PermissionDeniedError = ApprovalRequiredError(message)
        else:
            exc = PermissionDeniedError(message)
        exc.approval_id = approval_id  # type: ignore[attr-defined]
        exc.run = run  # type: ignore[attr-defined]
        exc.capability = spec.capability  # type: ignore[attr-defined]
        raise exc
