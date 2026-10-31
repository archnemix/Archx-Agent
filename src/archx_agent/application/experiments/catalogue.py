"""ExperimentService: catalogue operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.managers.experiments import Experiment, ExperimentRun

from .records import _PLACEHOLDER, _parse_params, _parse_metrics_source

class ExperimentServiceCatalogueMixin:
    @property
    def manager(self):
        return self.ws.experiments

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
