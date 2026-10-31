"""Rows for training runs: what was attempted, what it measured, and what it refused.

The v8 schema reserved ``training_jobs`` for exactly this, so the table is adopted with
``ALTER TABLE`` rather than redefined: a home that already holds rows keeps them and gains the
columns this milestone needs (``kind``, ``seed``, ``artifact_path``, ``artifact_sha256``,
``refusal``, ``version_id``, ``notes``).

Three kinds of row live here, and the difference between them is the point:

* a **completed** run trained a real model on this machine and wrote an artifact whose hash is
  recorded, with its metrics as rows;
* a **failed** run started and broke, and the error is kept;
* a **refused** run never started, and the ``refusal`` column holds the whole reason chain - the
  same standard M34 set for speech: what cannot be trained here is said out loud, in the same
  table, rather than hidden behind a disabled button.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

TRAINING_TABLES = ("training_jobs", "training_metrics")

#: Methods this build can actually run: both are dependency-free and deterministic on a CPU.
RUNNABLE_METHODS = ("ngram", "centroid")

#: Methods that mean "fine-tune a transformer". None of them can run here, and `blockers` says why.
FINETUNE_METHODS = ("lora", "qlora", "full")

METHODS = RUNNABLE_METHODS + FINETUNE_METHODS

STATUSES = ("queued", "running", "completed", "failed", "refused")


@dataclass
class TrainingJob:
    id: str
    method: str
    status: str
    created_at: str
    kind: str = "ngram"
    base_model: str | None = None
    dataset_id: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    preflight: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    checkpoints: list[Any] = field(default_factory=list)
    seed: int = 0
    artifact_path: str | None = None
    artifact_sha256: str | None = None
    refusal: str | None = None
    version_id: str | None = None
    notes: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    task_id: str | None = None
    #: Where the run executed: ``local`` (this machine's CPU) or ``remote`` (an M37 worker).
    target: str = "local"
    remote_job_id: str | None = None

    @property
    def ran(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "method": self.method,
            "kind": self.kind,
            "status": self.status,
            "base_model": self.base_model,
            "dataset_id": self.dataset_id,
            "config": dict(self.config),
            "preflight": dict(self.preflight),
            "metrics": dict(self.metrics),
            "checkpoints": list(self.checkpoints),
            "seed": self.seed,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "refusal": self.refusal,
            "version_id": self.version_id,
            "notes": self.notes,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "task_id": self.task_id,
            "target": self.target,
            "remote_job_id": self.remote_job_id,
            "created_at": self.created_at,
        }


@dataclass
class TrainingMetric:
    id: int
    job_id: str
    split: str
    name: str
    value: float | None
    created_at: str
    raw: str | None = None
    step: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "split": self.split,
            "name": self.name,
            "value": self.value,
            "raw": self.raw,
            "step": self.step,
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


def _job_from_row(row: Mapping[str, Any]) -> TrainingJob:
    return TrainingJob(
        id=row["id"],
        method=row["method"],
        status=row["status"],
        kind=row.get("kind") or row["method"],
        base_model=row["base_model"],
        dataset_id=row["dataset_id"],
        config=_loads(row["config"], {}),
        preflight=_loads(row["preflight"], {}),
        metrics=_loads(row["metrics"], {}),
        checkpoints=_loads(row["checkpoints"], []),
        seed=int(row["seed"] or 0),
        artifact_path=row["artifact_path"],
        artifact_sha256=row["artifact_sha256"],
        refusal=row["refusal"],
        version_id=row["version_id"],
        notes=row["notes"] or "",
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        error=row["error"],
        task_id=row["task_id"],
        target=row["target"] if "target" in row.keys() else "local",
        remote_job_id=row["remote_job_id"] if "remote_job_id" in row.keys() else None,
        created_at=row["created_at"],
    )


def _metric_from_row(row: Mapping[str, Any]) -> TrainingMetric:
    return TrainingMetric(
        id=int(row["id"]),
        job_id=row["job_id"],
        split=row["split"],
        name=row["name"],
        value=row["value"],
        raw=row["raw"],
        step=row["step"],
        created_at=row["created_at"],
    )


class TrainingManager(BaseManager):
    """Rows for training runs, their metrics and their refusals."""

    tables = TRAINING_TABLES

    def register_handlers(self) -> None:
        self.coordinator.register("training.job", self._apply_job)
        self.coordinator.register("training.job_update", self._apply_job_update)
        self.coordinator.register("training.metric", self._apply_metric)

    # -- write handlers ---------------------------------------------------
    def _apply_job(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        job = payload["job"]
        tx.execute(
            "INSERT INTO training_jobs(id, method, base_model, dataset_id, status, config,"
            " preflight, metrics, checkpoints, created_at, started_at, completed_at, error,"
            " task_id, kind, seed, artifact_path, artifact_sha256, refusal, version_id, notes,"
            " target, remote_job_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job["id"], job["method"], job.get("base_model"), job.get("dataset_id"),
                job["status"], json_text(job.get("config") or {}),
                json_text(job.get("preflight") or {}), json_text(job.get("metrics") or {}),
                json_text(job.get("checkpoints") or []), job["created_at"],
                job.get("started_at"), job.get("completed_at"), job.get("error"),
                job.get("task_id"), job.get("kind") or job["method"], int(job.get("seed") or 0),
                job.get("artifact_path"), job.get("artifact_sha256"), job.get("refusal"),
                job.get("version_id"), job.get("notes") or "",
                job.get("target") or "local", job.get("remote_job_id"),
            ),
        )
        return {"id": job["id"]}

    def _apply_job_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        job = payload["job"]
        tx.execute(
            "UPDATE training_jobs SET status = ?, preflight = ?, metrics = ?, checkpoints = ?,"
            " started_at = ?, completed_at = ?, error = ?, artifact_path = ?, artifact_sha256 = ?,"
            " refusal = ?, version_id = ?, notes = ?, target = ?, remote_job_id = ? WHERE id = ?",
            (
                job["status"], json_text(job.get("preflight") or {}),
                json_text(job.get("metrics") or {}), json_text(job.get("checkpoints") or []),
                job.get("started_at"), job.get("completed_at"), job.get("error"),
                job.get("artifact_path"), job.get("artifact_sha256"), job.get("refusal"),
                job.get("version_id"), job.get("notes") or "",
                job.get("target") or "local", job.get("remote_job_id"), job["id"],
            ),
        )
        return {"id": job["id"]}

    def _apply_metric(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        metric = payload["metric"]
        rowid = tx.execute(
            "INSERT INTO training_metrics(job_id, split, name, value, raw, step, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                metric["job_id"], metric["split"], metric["name"], metric.get("value"),
                metric.get("raw"), metric.get("step"), metric["created_at"],
            ),
        )
        return {"id": rowid}

    # -- jobs -------------------------------------------------------------
    def create(
        self,
        *,
        method: str,
        dataset_id: str | None,
        config: dict[str, Any] | None = None,
        seed: int = 0,
        base_model: str | None = None,
        kind: str | None = None,
        notes: str = "",
        task_id: str | None = None,
        target: str = "local",
        remote_job_id: str | None = None,
    ) -> TrainingJob:
        if method not in METHODS:
            raise ValidationError(
                f"unknown training method {method!r} (this build knows {', '.join(METHODS)})"
            )
        job = TrainingJob(
            id=new_id("tj_"),
            method=method,
            kind=kind or method,
            status="queued",
            base_model=base_model,
            dataset_id=dataset_id,
            config=dict(config or {}),
            seed=int(seed),
            notes=notes,
            task_id=task_id,
            target=target,
            remote_job_id=remote_job_id,
            created_at=iso_now(),
        )
        self._write("training.job", {"job": job.to_dict()})
        self.trace(
            "training", "training.created", status="ok", task_id=task_id,
            payload={"job_id": job.id, "method": method, "dataset_id": dataset_id},
        )
        return job

    def update(
        self,
        job_id: str,
        *,
        status: str,
        preflight: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        error: str | None = None,
        artifact_path: str | None = None,
        artifact_sha256: str | None = None,
        refusal: str | None = None,
        version_id: str | None = None,
        notes: str | None = None,
        target: str | None = None,
        remote_job_id: str | None = None,
    ) -> TrainingJob:
        current = self.get(job_id)
        if status not in STATUSES:
            raise ValidationError(f"unknown training status: {status}")
        row = current.to_dict()
        row.update({
            "status": status,
            "preflight": current.preflight if preflight is None else preflight,
            "metrics": current.metrics if metrics is None else metrics,
            "started_at": current.started_at if started_at is None else started_at,
            "completed_at": current.completed_at if completed_at is None else completed_at,
            "error": error if error is not None else current.error,
            "artifact_path": artifact_path or current.artifact_path,
            "artifact_sha256": artifact_sha256 or current.artifact_sha256,
            "refusal": refusal if refusal is not None else current.refusal,
            "version_id": version_id or current.version_id,
            "notes": current.notes if notes is None else notes,
            "target": current.target if target is None else target,
            "remote_job_id": remote_job_id or current.remote_job_id,
        })
        self._write("training.job_update", {"job": row})
        self.trace(
            "training", f"training.{status}", status="ok",
            payload={"job_id": job_id, "method": current.method},
        )
        return self.get(job_id)

    def get(self, wanted: str) -> TrainingJob:
        row = self.store.query_one(
            "SELECT * FROM training_jobs WHERE id = ? ORDER BY created_at DESC LIMIT 1", (wanted,)
        )
        if row is None:
            raise NotFoundError(f"no such training job: {wanted}")
        return _job_from_row(row)

    def resolve(self, wanted: str) -> TrainingJob:
        """An id, or the newest job whose id starts with the fragment - a CLI convenience."""
        row = self.store.query_one(
            "SELECT * FROM training_jobs WHERE id = ? OR id LIKE ?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (wanted, f"{wanted}%"),
        )
        if row is None:
            raise NotFoundError(f"no such training job: {wanted}")
        return _job_from_row(row)

    def jobs(
        self, *, status: str | None = None, dataset_id: str | None = None, limit: int = 50
    ) -> list[TrainingJob]:
        sql = "SELECT * FROM training_jobs"
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if dataset_id:
            clauses.append("dataset_id = ?")
            params.append(dataset_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_job_from_row(row) for row in self.store.query(sql, params)]

    # -- metrics ----------------------------------------------------------
    def record_metrics(
        self, job_id: str, metrics: dict[str, float], *, split: str, step: int | None = None
    ) -> list[TrainingMetric]:
        written: list[TrainingMetric] = []
        for name, value in metrics.items():
            payload = {
                "job_id": job_id,
                "split": split,
                "name": name,
                "value": None if value is None else float(value),
                "raw": None,
                "step": step,
                "created_at": iso_now(),
            }
            self._write("training.metric", {"metric": payload})
            written.append(
                TrainingMetric(
                    id=0, job_id=job_id, split=split, name=name,
                    value=payload["value"], raw=None, step=step, created_at=payload["created_at"],
                )
            )
        return written

    def metrics(self, job_id: str, *, split: str | None = None) -> list[TrainingMetric]:
        sql = "SELECT * FROM training_metrics WHERE job_id = ?"
        params: list[Any] = [job_id]
        if split:
            sql += " AND split = ?"
            params.append(split)
        sql += " ORDER BY id"
        return [_metric_from_row(row) for row in self.store.query(sql, params)]

    def latest_metric(self, job_id: str, name: str, *, split: str) -> float | None:
        value = self.store.scalar(
            "SELECT value FROM training_metrics WHERE job_id = ? AND name = ? AND split = ?"
            " ORDER BY id DESC LIMIT 1",
            (job_id, name, split),
        )
        return None if value is None else float(value)

    # -- overview ---------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        jobs = int(self.store.scalar("SELECT COUNT(*) FROM training_jobs") or 0)
        by_status: dict[str, int] = {}
        for row in self.store.query(
            "SELECT status, COUNT(*) AS n FROM training_jobs GROUP BY status"
        ):
            by_status[str(row["status"])] = int(row["n"])
        metrics = int(self.store.scalar("SELECT COUNT(*) FROM training_metrics") or 0)
        return {
            "jobs": jobs,
            "by_status": by_status,
            "metrics": metrics,
            "methods": list(METHODS),
            "runnable": list(RUNNABLE_METHODS),
            "finetune": list(FINETUNE_METHODS),
        }
