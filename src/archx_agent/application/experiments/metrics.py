"""ExperimentService: metrics operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.experiments import Experiment
from archx_agent.managers.tools import ToolContext

from .records import _metrics_from_json

class ExperimentServiceMetricsMixin:
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
