"""Rows for experiments: what was asked, what ran, and what came out.

The interesting decision in this module is what is *not* stored: there is no free-form "results"
blob a caller can fill with anything. A run carries the parameters it actually used, the command
it resolved to, its exit code and the metrics that its experiment declared how to read. A run that
produced no readable metrics says so in ``metrics_error`` instead of quietly appearing to have
produced zeroes - a comparison against a missing number is worse than no comparison.

Metrics are also stored as rows (``experiment_metrics``) so that "which run maximised accuracy"
is a query rather than a re-parse of every run's JSON, and so a metric name that appears in some
runs and not others is visible as a gap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

EXPERIMENT_TABLES = ("experiment_specs", "experiment_runs", "experiment_metrics")

RUN_STATUSES = ("passed", "failed", "timeout", "refused", "error")


@dataclass
class Experiment:
    id: str
    name: str
    command: str
    root: str
    status: str = "open"
    hypothesis: str | None = None
    params: list[dict[str, Any]] = field(default_factory=list)
    metrics_source: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def open(self) -> bool:
        return self.status == "open"

    def param_names(self) -> list[str]:
        return [str(entry.get("name")) for entry in self.params]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "hypothesis": self.hypothesis,
            "command": self.command,
            "root": self.root,
            "params": [dict(entry) for entry in self.params],
            "param_names": self.param_names(),
            "metrics_source": dict(self.metrics_source),
            "status": self.status,
            "open": self.status == "open",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class ExperimentRun:
    id: str
    experiment_id: str
    command: str
    status: str
    params: dict[str, Any] = field(default_factory=dict)
    exit_code: int | None = None
    duration_ms: float | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    metrics_error: str | None = None
    task_id: str | None = None
    tool_run_id: str | None = None
    artifact_id: str | None = None
    seed: str | None = None
    note: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "command": self.command,
            "status": self.status,
            "params": dict(self.params),
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "metrics": dict(self.metrics),
            "metrics_error": self.metrics_error,
            "task_id": self.task_id,
            "tool_run_id": self.tool_run_id,
            "artifact_id": self.artifact_id,
            "seed": self.seed,
            "note": self.note,
            "created_at": self.created_at,
        }


def _loads(raw: Any, fallback: Any) -> Any:
    if raw in (None, ""):
        return fallback
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):  # pragma: no cover - a hand-edited row
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _experiment_from_row(row: Mapping[str, Any]) -> Experiment:
    return Experiment(
        id=row["id"],
        name=row["name"],
        command=row["command"],
        root=row["root"],
        status=row["status"],
        hypothesis=row["hypothesis"],
        params=_loads(row["params"], []),
        metrics_source=_loads(row["metrics_source"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        metadata=_loads(row["metadata"], {}),
    )


def _run_from_row(row: Mapping[str, Any]) -> ExperimentRun:
    return ExperimentRun(
        id=row["id"],
        experiment_id=row["experiment_id"],
        command=row["command"],
        status=row["status"],
        params=_loads(row["params"], {}),
        exit_code=row["exit_code"],
        duration_ms=row["duration_ms"],
        metrics=_loads(row["metrics"], {}),
        metrics_error=row["metrics_error"],
        task_id=row["task_id"],
        tool_run_id=row["tool_run_id"],
        artifact_id=row["artifact_id"],
        seed=row["seed"],
        note=row["note"],
        created_at=row["created_at"],
    )


class ExperimentManager(BaseManager):
    """Rows for experiments, their runs and their metrics."""

    tables = EXPERIMENT_TABLES

    def register_handlers(self) -> None:
        self.coordinator.register("experiment.create", self._apply_create)
        self.coordinator.register("experiment.update", self._apply_update)
        self.coordinator.register("experiment.run", self._apply_run)
        self.coordinator.register("experiment.delete", self._apply_delete)

    # -- write handlers ---------------------------------------------------
    def _apply_create(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        item = payload["experiment"]
        tx.execute(
            "INSERT INTO experiment_specs(id, name, hypothesis, command, root, params, metrics_source,"
            " status, created_at, updated_at, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                item["id"], item["name"], item.get("hypothesis"), item["command"], item["root"],
                json_text(item.get("params") or []), json_text(item.get("metrics_source") or {}),
                item["status"], item["created_at"], item["updated_at"],
                json_text(item.get("metadata") or {}),
            ),
        )
        return {"id": item["id"]}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        experiment_id = payload["id"]
        fields = dict(payload.get("fields") or {})
        allowed = {"name", "hypothesis", "status", "params", "metrics_source", "updated_at",
                   "metadata", "command"}
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValidationError(f"cannot update experiment field(s): {', '.join(unknown)}")
        for key in ("params", "metrics_source", "metadata"):
            if key in fields:
                fields[key] = json_text(fields[key] or ([] if key == "params" else {}))
        if not fields:
            return {"id": experiment_id, "changed": 0}
        assignments = ", ".join(f"{name} = ?" for name in fields)
        tx.execute(
            f"UPDATE experiment_specs SET {assignments} WHERE id = ?",
            (*fields.values(), experiment_id),
        )
        return {"id": experiment_id, "changed": len(fields)}

    def _apply_run(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run = payload["run"]
        metrics = run.get("metrics") or {}
        tx.execute(
            "INSERT INTO experiment_runs(id, experiment_id, params, command, status, exit_code,"
            " duration_ms, metrics, metrics_error, task_id, tool_run_id, artifact_id, seed, note,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run["id"], run["experiment_id"], json_text(run.get("params") or {}),
                run["command"], run["status"], run.get("exit_code"), run.get("duration_ms"),
                json_text(metrics), run.get("metrics_error"), run.get("task_id"),
                run.get("tool_run_id"), run.get("artifact_id"), run.get("seed"),
                run.get("note"), run["created_at"],
            ),
        )
        # replace then insert: a replayed write with the same op id must not double the metrics
        tx.execute("DELETE FROM experiment_metrics WHERE run_id = ?", (run["id"],))
        for name, value in metrics.items():
            numeric = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            tx.execute(
                "INSERT INTO experiment_metrics(run_id, name, value, raw) VALUES (?,?,?,?)",
                (run["id"], str(name), numeric, None if numeric is not None else str(value)),
            )
        return {"id": run["id"]}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        experiment_id = payload["id"]
        tx.execute(
            "DELETE FROM experiment_metrics WHERE run_id IN"
            " (SELECT id FROM experiment_runs WHERE experiment_id = ?)",
            (experiment_id,),
        )
        tx.execute("DELETE FROM experiment_runs WHERE experiment_id = ?", (experiment_id,))
        tx.execute("DELETE FROM experiment_specs WHERE id = ?", (experiment_id,))
        return {"id": experiment_id, "deleted": True}

    # -- writes -----------------------------------------------------------
    def create(
        self,
        name: str,
        *,
        command: str,
        root: str,
        hypothesis: str | None = None,
        params: list[dict[str, Any]] | None = None,
        metrics_source: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Experiment:
        now = iso_now()
        experiment = Experiment(
            id=new_id("ex_"),
            name=(name or "").strip()[:200] or "experiment",
            command=command,
            root=root,
            hypothesis=hypothesis,
            params=list(params or []),
            metrics_source=dict(metrics_source or {}),
            status="open",
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        self._write("experiment.create", {"experiment": experiment.to_dict()})
        self.trace(
            "experiment", "experiment.created", status="ok",
            payload={"experiment_id": experiment.id, "name": experiment.name, "root": root},
        )
        return experiment

    def update(self, experiment_id: str, **fields: Any) -> Experiment:
        self.get(experiment_id)
        self._write(
            "experiment.update",
            {"id": experiment_id, "fields": {**fields, "updated_at": iso_now()}},
        )
        return self.get(experiment_id)

    def record_run(
        self,
        experiment_id: str,
        *,
        command: str,
        status: str,
        params: Mapping[str, Any] | None = None,
        exit_code: int | None = None,
        duration_ms: float | None = None,
        metrics: Mapping[str, float] | None = None,
        metrics_error: str | None = None,
        task_id: str | None = None,
        tool_run_id: str | None = None,
        artifact_id: str | None = None,
        seed: str | None = None,
        note: str | None = None,
    ) -> ExperimentRun:
        if status not in RUN_STATUSES:
            raise ValidationError(f"unknown run status: {status}")
        experiment = self.get(experiment_id)
        run = ExperimentRun(
            id=new_id("xr_"),
            experiment_id=experiment_id,
            command=command,
            status=status,
            params=dict(params or {}),
            exit_code=exit_code,
            duration_ms=duration_ms,
            metrics={str(k): float(v) for k, v in (metrics or {}).items()},
            metrics_error=metrics_error,
            task_id=task_id,
            tool_run_id=tool_run_id,
            artifact_id=artifact_id,
            seed=seed,
            note=note,
            created_at=iso_now(),
        )
        self._write("experiment.run", {"run": run.to_dict()})
        self._write(
            "experiment.update", {"id": experiment_id, "fields": {"updated_at": iso_now()}}
        )
        self.trace(
            "experiment", "experiment.run", status="ok" if status == "passed" else "error",
            task_id=task_id,
            payload={
                "experiment_id": experiment_id, "run_id": run.id, "status": status,
                "metrics": dict(run.metrics), "params": dict(run.params),
                "name": experiment.name,
            },
        )
        return run

    def delete(self, experiment_id: str) -> None:
        self.get(experiment_id)
        self._write("experiment.delete", {"id": experiment_id})
        self.trace(
            "experiment", "experiment.deleted", status="ok",
            payload={"experiment_id": experiment_id},
        )

    # -- reads ------------------------------------------------------------
    def get(self, experiment_id: str) -> Experiment:
        row = self.store.query_one("SELECT * FROM experiment_specs WHERE id = ?", (experiment_id,))
        if row is None:
            raise NotFoundError(f"no such experiment: {experiment_id}")
        return _experiment_from_row(row)

    def find(self, experiment_id: str) -> Experiment | None:
        row = self.store.query_one("SELECT * FROM experiment_specs WHERE id = ?", (experiment_id,))
        return _experiment_from_row(row) if row else None

    def list(self, *, status: str | None = None, limit: int = 50) -> list[Experiment]:
        sql = "SELECT * FROM experiment_specs"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        return [_experiment_from_row(row) for row in self.store.query(sql, params)]

    def runs(self, experiment_id: str, *, limit: int = 200) -> list[ExperimentRun]:
        rows = self.store.query(
            "SELECT * FROM experiment_runs WHERE experiment_id = ?"
            " ORDER BY created_at, rowid LIMIT ?",
            (experiment_id, int(limit)),
        )
        return [_run_from_row(row) for row in rows]

    def get_run(self, run_id: str) -> ExperimentRun:
        row = self.store.query_one("SELECT * FROM experiment_runs WHERE id = ?", (run_id,))
        if row is None:
            raise NotFoundError(f"no such experiment run: {run_id}")
        return _run_from_row(row)

    def run_counts(self) -> dict[str, dict[str, int]]:
        """Run counts per experiment in one query, so a list view needs one call not N."""
        rows = self.store.query(
            "SELECT experiment_id, COUNT(*) AS runs,"
            " SUM(CASE WHEN status != 'passed' THEN 1 ELSE 0 END) AS failed"
            " FROM experiment_runs GROUP BY experiment_id"
        )
        return {
            row["experiment_id"]: {"runs": int(row["runs"]), "failed": int(row["failed"] or 0)}
            for row in rows
        }

    def metric_names(self, experiment_id: str) -> list[str]:
        rows = self.store.query(
            "SELECT DISTINCT m.name FROM experiment_metrics m"
            " JOIN experiment_runs r ON r.id = m.run_id"
            " WHERE r.experiment_id = ? ORDER BY m.name",
            (experiment_id,),
        )
        return [row["name"] for row in rows]

    def ranked(self, experiment_id: str, metric: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Runs that have this metric, best first. A run without it is not ranked at all."""
        rows = self.store.query(
            "SELECT r.id, r.params, r.status, m.value FROM experiment_metrics m"
            " JOIN experiment_runs r ON r.id = m.run_id"
            " WHERE r.experiment_id = ? AND m.name = ? AND m.value IS NOT NULL"
            " ORDER BY m.value DESC, r.created_at LIMIT ?",
            (experiment_id, metric, int(limit)),
        )
        return [
            {"run_id": row["id"], "value": row["value"], "params": _loads(row["params"], {}),
             "status": row["status"]}
            for row in rows
        ]

    def stats(self) -> dict[str, Any]:
        return {
            "experiments": self.table_count("experiment_specs"),
            "open": int(
                self.store.scalar("SELECT COUNT(*) FROM experiment_specs WHERE status = 'open'") or 0
            ),
            "runs": self.table_count("experiment_runs"),
            "failed_runs": int(
                self.store.scalar(
                    "SELECT COUNT(*) FROM experiment_runs WHERE status != 'passed'"
                ) or 0
            ),
            "metrics": self.table_count("experiment_metrics"),
        }
