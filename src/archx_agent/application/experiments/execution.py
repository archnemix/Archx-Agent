"""ExperimentService: execution operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.managers.experiments import Experiment, ExperimentRun
from archx_agent.managers.tools import ToolContext

from .records import _resolve_params, _params_label, _metrics_label

class ExperimentServiceExecutionMixin:
    def _execute(self, name: str, arguments: Mapping[str, Any], context: ToolContext):
        """Run one tool; a refusal becomes a domain error naming the approval."""
        run = self.ws.tools.execute(name, arguments, context=context, requester="experiment")
        if run.status == "denied":
            approval = getattr(run, "approval_id", None)
            if approval:
                raise ApprovalRequiredError(
                    f"{name} needs approval: approve {approval} or grant the capability",
                    approval_id=approval,
                )
            raise PermissionDeniedError(run.error or f"{name} was refused")
        if run.status == "failed":
            raise ToolError(run.error or f"{name} failed")
        return run

    def _root(self, root: str | Path | None) -> str:
        roots = self.ws.tools.roots()
        if not roots:
            raise ToolError(
                "no tool roots are configured, so there is nowhere to run an experiment; "
                "set tools.roots or run inside a project"
            )
        target = Path(root).expanduser() if root else Path(roots[0])
        resolved = self.ws.tools.runtime.resolve(str(target))
        if not resolved.is_dir():
            raise NotFoundError(f"no such directory: {resolved}")
        return str(resolved)

    def _workspace_dir(self, experiment: Experiment) -> Path:
        base = Path(self.ws.config.path("paths.artifacts")) / "experiments" / experiment.id
        base.mkdir(parents=True, exist_ok=True)
        return base

    @staticmethod
    def _attach(task_id: str | None, ws, path: Path, *, kind: str, name: str) -> str | None:
        if not task_id:
            return None
        try:
            return ws.tasks.attach_artifact(task_id, str(path), kind=kind, name=name).id
        except Exception:  # noqa: BLE001 - losing the artifact must not lose the run
            return None

    def run(
        self,
        experiment_id: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: int | None = None,
        seed: str | None = None,
        note: str | None = None,
    ) -> ExperimentRun:
        """Run the experiment's command once, recording the attempt whatever happens."""
        experiment = self.manager.get(experiment_id)
        if experiment.status != "open":
            raise ValidationError(
                f"experiment {experiment.id} is closed; reopen it to run it again"
            )
        resolved = _resolve_params(experiment, params or {})
        command = experiment.command
        for name, value in resolved.items():
            command = command.replace("{" + name + "}", value)

        task = None
        if getattr(self.ws, "tasks", None) is not None:
            # `manual=True`: an experiment outlives the command that made it, exactly like a
            # coding session - the next CLI invocation must not sweep its task to `interrupted`.
            task = self.ws.tasks.create(
                "experiment",
                title=f"{experiment.name}: {_params_label(resolved)}"[:200],
                start=True,
                manual=True,
                tools=["shell.run"],
                metadata={"experiment_id": experiment.id, "params": resolved},
            )
        context = ToolContext(
            task_id=task.id if task else None, purpose=f"experiment {experiment.name}"
        )
        arguments: dict[str, Any] = {"command": command, "cwd": experiment.root}
        if timeout:
            arguments["timeout"] = int(timeout)
        try:
            # Not `_execute`: a command that exits non-zero is *data* here, not an exception. The
            # tool returns the run with its exit code and stdout; only a refusal raises.
            run = self.ws.tools.execute(
                "shell.run", arguments, context=context, requester="experiment"
            )
        except (ApprovalRequiredError, PermissionDeniedError) as exc:
            # A refusal is an attempt: it belongs in the ledger with the reason attached.
            self.manager.record_run(
                experiment.id,
                command=command,
                status="refused",
                params=resolved,
                task_id=task.id if task else None,
                metrics_error="the command was refused before it ran",
                seed=seed,
                note=note,
            )
            if task is not None:
                try:
                    self.ws.tasks.fail(task.id, getattr(exc, "message", None) or str(exc))
                except Exception:  # noqa: BLE001 - the ledger is the source of truth
                    pass
            raise
        if run.status == "denied":
            approval = getattr(run, "approval_id", None)
            self.manager.record_run(
                experiment.id,
                command=command,
                status="refused",
                params=resolved,
                task_id=task.id if task else None,
                metrics_error="the command was refused before it ran",
                seed=seed,
                note=note,
            )
            if task is not None:
                try:
                    self.ws.tasks.fail(task.id, run.error or "the command was refused")
                except Exception:  # noqa: BLE001 - the ledger is the source of truth
                    pass
            if approval:
                raise ApprovalRequiredError(
                    f"shell.run needs approval: approve {approval} or grant the capability",
                    approval_id=approval,
                )
            raise PermissionDeniedError(run.error or "shell.run was refused")
        result = dict(run.result or {})
        exit_code = result.get("exit_code")
        timed_out = bool(result.get("timed_out"))
        if timed_out:
            status = "timeout"
        elif exit_code not in (0, None):
            status = "failed"
        else:
            status = "passed"

        metrics, metrics_error = self._read_metrics(experiment, result, context)
        artifact_id = None
        if (result.get("stdout") or result.get("stderr")) and task is not None:
            artifact_id = self._log_artifact(experiment, run, result, command, metrics, task.id)
        recorded = self.manager.record_run(
            experiment.id,
            command=command,
            status=status,
            params=resolved,
            exit_code=exit_code if isinstance(exit_code, int) else None,
            duration_ms=float(result.get("duration_ms") or run.duration_ms or 0.0),
            metrics=metrics,
            metrics_error=metrics_error,
            task_id=task.id if task else None,
            tool_run_id=run.id,
            artifact_id=artifact_id,
            seed=seed,
            note=note,
        )
        if task is not None:
            self._journal(task.id, recorded, metrics, metrics_error)
        return recorded

    def _journal(
        self,
        task_id: str,
        run: ExperimentRun,
        metrics: Mapping[str, float],
        metrics_error: str | None,
    ) -> None:
        """Write the run onto its task's timeline. Never worth failing a run over."""
        try:
            self.ws.tasks.log(
                task_id, "run",
                detail=f"{run.status}: {run.command[:120]} (exit {run.exit_code}, "
                       f"{int(run.duration_ms or 0)} ms)",
            )
            for name, value in metrics.items():
                self.ws.tasks.log(task_id, "metric", detail=f"{name} = {value:g}")
            if metrics_error:
                self.ws.tasks.log(task_id, "metric", detail=f"not read: {metrics_error}")
            if run.status == "passed":
                self.ws.tasks.complete(
                    task_id, summary=f"passed: {_metrics_label(metrics) or 'no metrics'}"
                )
            else:
                self.ws.tasks.fail(
                    task_id,
                    f"{run.status}: exit {run.exit_code}",
                    unresolved=[f"run {run.id} {run.status}"],
                )
        except Exception:  # noqa: BLE001 - the ledger is the source of truth
            pass
