"""Experimental Mode: run a declared command with declared parameters, keep the result, compare runs.

The rule this module keeps
--------------------------
**A metric is a metric only if the experiment said where it comes from.** An experiment declares
one of three sources - nothing, the last line of stdout as JSON, or a JSON file the run writes -
and the runner reads exactly that, through the same `fs.read` capability as everything else. When
the source is missing, malformed, or not numeric, the run is recorded with ``metrics_error``
saying so, not with zeroes. A comparison that reads "no answer" as "0.0" is the most common way a
results table lies, and it is the failure this module is built to make impossible.

Where that shows up in the API
------------------------------
* ``compare`` names the runs it could not rank, and why, instead of dropping them silently;
* a substituted parameter must be one shell-safe token, and an undeclared placeholder or an
  unknown parameter is refused *by name* before anything runs;
* every run is a real task with its own log artifact, because a run is work that happened and its
  reproduction commands already exist in the task ledger.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.experiments import Experiment, ExperimentRun
from archx_agent.managers.tools import ToolContext

#: A substituted value has to survive `shlex.split` as one token. Anything else is refused rather
#: than quoted: quoting a value the user did not quote silently changes what the command means.
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:/=+@-]{0,200}$")
_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

METRIC_SOURCES = ("none", "stdout-json", "file")


@dataclass
class ParamSpec:
    """One declared knob: a name, an optional default, and what it means."""

    name: str
    default: Any = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "default": self.default, "description": self.description}


class ExperimentService:
    """Create experiments, run them, and compare the runs honestly."""

    def __init__(self, ws) -> None:
        self.ws = ws

    # -- plumbing ---------------------------------------------------------
    @property
    def manager(self):
        return self.ws.experiments

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

    # -- creation ---------------------------------------------------------
    def create(
        self,
        name: str,
        command: str,
        *,
        root: str | Path | None = None,
        hypothesis: str | None = None,
        params: Sequence[Mapping[str, Any]] | None = None,
        metrics: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Experiment:
        text = (command or "").strip()
        if not text:
            raise ValidationError("an experiment needs a command")
        declared = _parse_params(params or [])
        names = {spec.name for spec in declared}
        placeholders = sorted(set(_PLACEHOLDER.findall(text)))
        undeclared = [token for token in placeholders if token not in names]
        if undeclared:
            raise ValidationError(
                f"the command uses {{{undeclared[0]}}} but no parameter is declared with that "
                f"name (declared: {', '.join(sorted(names)) or 'none'})"
            )
        unused = sorted(names - set(placeholders))
        if unused:
            raise ValidationError(
                f"parameter {unused[0]!r} is declared but the command never uses "
                f"{{{unused[0]}}}; remove it or put it in the command"
            )
        source = _parse_metrics_source(metrics or {"kind": "none"})
        return self.manager.create(
            name,
            command=text,
            root=self._root(root),
            hypothesis=(hypothesis or "").strip() or None,
            params=[spec.to_dict() for spec in declared],
            metrics_source=source,
            metadata=dict(metadata or {}),
        )

    # -- reads ------------------------------------------------------------
    def list(self, *, status: str | None = None, limit: int = 50) -> list[Experiment]:
        return self.manager.list(status=status, limit=limit)

    def get(self, experiment_id: str) -> Experiment:
        return self.manager.get(experiment_id)

    def show(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.manager.get(experiment_id)
        runs = self.manager.runs(experiment_id)
        by_status: dict[str, int] = {}
        for run in runs:
            by_status[run.status] = by_status.get(run.status, 0) + 1
        return {
            "experiment": experiment.to_dict(),
            "runs": [run.to_dict() for run in runs],
            "metric_names": self.manager.metric_names(experiment_id),
            "stats": {
                "runs": len(runs),
                "by_status": by_status,
                "with_metrics": sum(1 for run in runs if run.metrics),
                "without_metrics": sum(1 for run in runs if not run.metrics),
                "task": self._task_summary(experiment),
            },
        }

    def _task_summary(self, experiment: Experiment) -> dict[str, Any] | None:
        run_task = self.manager.runs(experiment.id, limit=1)
        if not run_task or not run_task[-1].task_id:
            return None
        if getattr(self.ws, "tasks", None) is None:
            return None
        found = self.ws.tasks.find(run_task[-1].task_id)
        return found.unwrap().to_dict() if found.ok else None

    def runs(self, experiment_id: str, *, limit: int = 200) -> list[ExperimentRun]:
        self.manager.get(experiment_id)
        return self.manager.runs(experiment_id, limit=limit)

    def run_by_id(self, run_id: str) -> ExperimentRun:
        return self.manager.get_run(run_id)

    # -- the runner -------------------------------------------------------
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

    # -- metrics ----------------------------------------------------------
    def _read_metrics(
        self, experiment: Experiment, result: Mapping[str, Any], context: ToolContext
    ) -> tuple[dict[str, float], str | None]:
        source = experiment.metrics_source or {"kind": "none"}
        kind = source.get("kind", "none")
        if kind == "none":
            return {}, None
        if kind == "stdout-json":
            text = str(result.get("stdout") or "")
            line = next((row.strip() for row in reversed(text.splitlines()) if row.strip()), "")
            if not line:
                return {}, "the command printed nothing, so there was no JSON to read"
            return _metrics_from_json(line, "the last line of stdout")
        if kind == "file":
            path = str(source.get("path") or "metrics.json")
            try:
                read = self._execute(
                    "fs.read", {"path": str(Path(experiment.root) / path)}, context
                )
            except (ApprovalRequiredError, PermissionDeniedError):
                return {}, f"fs.read is not granted, so {path} could not be read"
            except ToolError as exc:
                return {}, f"{path} could not be read: {exc.message}"
            text = str((read.result or {}).get("content") or "")
            if not text.strip():
                return {}, f"{path} exists but is empty"
            return _metrics_from_json(text, path)
        return {}, f"unknown metrics source {kind!r}"

    def _log_artifact(
        self,
        experiment: Experiment,
        run,
        result: Mapping[str, Any],
        command: str,
        metrics: Mapping[str, float],
        task_id: str,
    ) -> str | None:
        stamp = iso_now().replace(":", "").replace("-", "")
        target = self._workspace_dir(experiment) / f"run-{stamp}-{run.id[-6:]}.log"
        body = [f"$ {command}", f"cwd {experiment.root}"]
        if result.get("stdout"):
            body += ["", "--- stdout ---", str(result["stdout"])]
        if result.get("stderr"):
            body += ["", "--- stderr ---", str(result["stderr"])]
        body += ["", f"exit {result.get('exit_code')} in {result.get('duration_ms')} ms"]
        if metrics:
            body += ["", "--- metrics ---"] + [f"{k} = {v:g}" for k, v in metrics.items()]
        target.write_text("\n".join(body), encoding="utf-8")
        return self._attach(task_id, self.ws, target, kind="experiment-log", name=target.name)

    # -- comparison -------------------------------------------------------
    def compare(
        self,
        experiment_id: str,
        *,
        metric: str | None = None,
        minimise: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Line the runs up, name the best one, and say what could not be compared and why."""
        experiment = self.manager.get(experiment_id)
        runs = self.manager.runs(experiment_id, limit=limit)
        names = self.manager.metric_names(experiment_id)
        chosen = metric or (names[0] if names else None)
        if metric is not None and metric not in names:
            raise NotFoundError(
                f"no metric named {metric!r} in this experiment "
                f"(recorded: {', '.join(names) or 'none'})"
            )
        notes: list[str] = []
        comparable = [run for run in runs if chosen and chosen in run.metrics]
        if chosen:
            for run in runs:
                if chosen not in run.metrics:
                    notes.append(f"{run.id} is not ranked: {run.metrics_error or 'no value for this metric'}")
            if len(comparable) < len(runs):
                notes.append(f"{len(comparable)} of {len(runs)} run(s) have a value for {chosen}")
        best = None
        if comparable:
            pick = (
                min(comparable, key=lambda r: r.metrics[chosen])
                if minimise
                else max(comparable, key=lambda r: r.metrics[chosen])
            )
            best = {
                "run_id": pick.id,
                "value": pick.metrics[chosen],
                "params": dict(pick.params),
                "status": pick.status,
            }
        shapes = {tuple(sorted(run.params)) for run in runs}
        if len(shapes) > 1:
            notes.append(
                "the runs do not all carry the same parameter names; compare only the metrics "
                "you mean to compare"
            )
        failed = [run.id for run in runs if run.status != "passed"]
        if failed:
            notes.append(
                f"{len(failed)} run(s) did not pass; their metrics are shown but a failed run "
                "is not a result"
            )
        return {
            "experiment": experiment.to_dict(),
            "metric": chosen,
            "direction": "lowest" if minimise else "highest",
            "runs": [run.to_dict() for run in runs],
            "best": best,
            "notes": notes,
            "metrics": names,
        }

    # -- lifecycle --------------------------------------------------------
    def close(self, experiment_id: str) -> Experiment:
        experiment = self.manager.get(experiment_id)
        if experiment.status != "open":
            raise ValidationError(f"experiment {experiment.id} is already closed")
        return self.manager.update(experiment_id, status="closed")

    def reopen(self, experiment_id: str) -> Experiment:
        experiment = self.manager.get(experiment_id)
        if experiment.status == "open":
            raise ValidationError(f"experiment {experiment.id} is already open")
        return self.manager.update(experiment_id, status="open")

    def delete(self, experiment_id: str) -> None:
        self.manager.delete(experiment_id)

    def stats(self) -> dict[str, Any]:
        return self.manager.stats()


# --------------------------------------------------------------------------
# parsing and substitution
# --------------------------------------------------------------------------
def _resolve_params(experiment: Experiment, supplied: Mapping[str, Any]) -> dict[str, str]:
    """Merge the defaults with what was passed, and refuse anything ambiguous."""
    declared = {str(entry["name"]): entry.get("default") for entry in experiment.params}
    unknown = sorted(set(supplied) - set(declared))
    if unknown:
        raise ValidationError(
            f"{unknown[0]!r} is not a parameter of this experiment "
            f"(declared: {', '.join(sorted(declared)) or 'none'})"
        )
    merged = {**declared, **supplied}
    resolved: dict[str, str] = {}
    for name in sorted(merged):
        value = merged[name]
        if value is None:
            raise ValidationError(f"parameter {name!r} has no value; pass it or give it a default")
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, (int, float)):
            text = repr(value) if isinstance(value, float) else str(value)
        elif isinstance(value, str):
            text = value.strip()
        else:
            raise ValidationError(f"parameter {name!r} must be a number or a string")
        if not _SAFE_VALUE.match(text):
            raise ValidationError(
                f"parameter {name!r} is {value!r}; a substituted value has to be a single "
                "shell-safe token (letters, digits and _ . : / = + @ -)"
            )
        resolved[name] = text
    return resolved


def _parse_params(entries: Sequence[Mapping[str, Any]]) -> list[ParamSpec]:
    specs: list[ParamSpec] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, Mapping):
            raise ValidationError(f"parameter #{index} must be an object")
        extra = sorted(set(entry) - {"name", "default", "description"})
        if extra:
            raise ValidationError(f"parameter #{index} has unknown field(s): {', '.join(extra)}")
        name = str(entry.get("name") or "").strip()
        if not _IDENTIFIER.match(name):
            raise ValidationError(
                f"parameter #{index} needs a name like a Python identifier (got {name!r})"
            )
        if name in seen:
            raise ValidationError(f"two parameters are named {name!r}")
        seen.add(name)
        default = entry.get("default")
        if default is not None and not isinstance(default, (str, int, float, bool)):
            raise ValidationError(f"parameter {name!r} has a default that is not a value")
        specs.append(
            ParamSpec(name=name, default=default, description=str(entry.get("description") or ""))
        )
    return specs


def _parse_metrics_source(source: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise ValidationError('metrics must be an object such as {"kind": "none"}')
    extra = sorted(set(source) - {"kind", "path"})
    if extra:
        raise ValidationError(f"metrics has unknown field(s): {', '.join(extra)}")
    kind = str(source.get("kind") or "none")
    if kind not in METRIC_SOURCES:
        raise ValidationError(
            f"unknown metrics source {kind!r} (known: {', '.join(METRIC_SOURCES)})"
        )
    if kind != "file":
        if source.get("path"):
            raise ValidationError('only a "file" metrics source takes a path')
        return {"kind": kind}
    path = str(source.get("path") or "metrics.json").strip()
    if not path or path.startswith("/") or ".." in Path(path).parts:
        raise ValidationError("a metrics file must be a relative path inside the experiment directory")
    return {"kind": "file", "path": path}


def _metrics_from_json(text: str, where: str) -> tuple[dict[str, float], str | None]:
    """Read a flat object of numbers, or say precisely why it is not one."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"{where} is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return {}, f"{where} must be a JSON object of numbers"
    if not data:
        return {}, f"{where} had no metrics in it"
    metrics: dict[str, float] = {}
    for key, value in data.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return {}, f"{where} has a non-numeric value for {key!r}"
        metrics[str(key)] = float(value)
    return metrics, None


def _params_label(params: Mapping[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(params.items())) or "defaults"


def _metrics_label(metrics: Mapping[str, float]) -> str:
    return ", ".join(f"{key}={value:g}" for key, value in metrics.items())
