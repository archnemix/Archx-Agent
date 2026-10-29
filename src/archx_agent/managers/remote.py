"""Rows for work handed to another machine, and the evidence it came back with.

A remote result is a claim made by a machine you are not sitting at, so the table is built around
the only question that matters: *can this result be checked?* The v8 schema reserved
``remote_jobs`` (``provider``, ``status``, ``config``, ``estimate``, ``actual``, ``outputs``,
``approved_by``); v27 adopts it with ``ALTER TABLE`` and adds the columns that make a result
checkable:

``endpoint`` / ``machine`` / ``protocol``
    who computed it, at which address, speaking which version of the protocol;

``bundle_sha256``
    the exact input, hashed before it left - so a result can be traced to an input rather than to
    "the dataset, probably";

``claimed_sha256`` / ``received_sha256``
    what the far end said the artifact was, and what this machine measured when it arrived. They
    are separate columns because the whole point is that they can disagree.

``remote_attempts``
    one row per attempt to talk to an endpoint. A dispatch that never arrived is a finding, in the
    same spirit as M34's refused probes and M36's refused runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

REMOTE_TABLES = ("remote_jobs", "remote_attempts")

STATUSES = ("draft", "dispatched", "running", "received", "verified", "failed", "refused")

#: The version of the worker protocol. A worker that speaks another version is refused rather than
#: guessed at: two machines that disagree about the shape of a job should say so immediately.
PROTOCOL = "archx-remote/1"


@dataclass
class RemoteJob:
    id: str
    provider: str
    status: str
    created_at: str
    kind: str = "training"
    dataset_id: str | None = None
    endpoint: str | None = None
    machine: str | None = None
    protocol: str | None = None
    bundle_sha256: str | None = None
    bundle_path: str | None = None
    claimed_sha256: str | None = None
    received_sha256: str | None = None
    artifact_path: str | None = None
    verified_at: str | None = None
    verify_note: str | None = None
    remote_job_id: str | None = None
    received_at: str | None = None
    refusal: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    estimate: dict[str, Any] = field(default_factory=dict)
    actual: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    approved_by: str | None = None
    completed_at: str | None = None
    error: str | None = None
    task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "status": self.status,
            "kind": self.kind,
            "dataset_id": self.dataset_id,
            "endpoint": self.endpoint,
            "machine": self.machine,
            "protocol": self.protocol,
            "bundle_sha256": self.bundle_sha256,
            "bundle_path": self.bundle_path,
            "claimed_sha256": self.claimed_sha256,
            "received_sha256": self.received_sha256,
            "artifact_path": self.artifact_path,
            "verified_at": self.verified_at,
            "verify_note": self.verify_note,
            "remote_job_id": self.remote_job_id,
            "received_at": self.received_at,
            "refusal": self.refusal,
            "config": dict(self.config),
            "estimate": dict(self.estimate),
            "actual": dict(self.actual),
            "outputs": dict(self.outputs),
            "approved_by": self.approved_by,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "task_id": self.task_id,
        }


@dataclass
class RemoteAttempt:
    id: str
    action: str
    status: str
    created_at: str
    job_id: str | None = None
    detail: str | None = None
    endpoint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "action": self.action,
            "status": self.status,
            "detail": self.detail,
            "endpoint": self.endpoint,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


def _loads(raw: Any, fallback: Any) -> Any:
    if raw in (None, ""):
        return fallback
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):  # pragma: no cover - a hand-edited row
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _job_from_row(row: Mapping[str, Any]) -> RemoteJob:
    return RemoteJob(
        id=row["id"],
        provider=row["provider"],
        status=row["status"],
        kind=row.get("kind") or "training",
        dataset_id=row.get("dataset_id"),
        endpoint=row.get("endpoint"),
        machine=row.get("machine"),
        protocol=row.get("protocol"),
        bundle_sha256=row.get("bundle_sha256"),
        bundle_path=row.get("bundle_path"),
        claimed_sha256=row.get("claimed_sha256"),
        received_sha256=row.get("received_sha256"),
        artifact_path=row.get("artifact_path"),
        verified_at=row.get("verified_at"),
        verify_note=row.get("verify_note"),
        remote_job_id=row.get("remote_job_id"),
        received_at=row.get("received_at"),
        refusal=row.get("refusal"),
        config=_loads(row.get("config"), {}),
        estimate=_loads(row.get("estimate"), {}),
        actual=_loads(row.get("actual"), {}),
        outputs=_loads(row.get("outputs"), {}),
        approved_by=row.get("approved_by"),
        created_at=row["created_at"],
        completed_at=row.get("completed_at"),
        error=row.get("error"),
        task_id=row.get("task_id"),
    )


def _attempt_from_row(row: Mapping[str, Any]) -> RemoteAttempt:
    return RemoteAttempt(
        id=row["id"],
        job_id=row.get("job_id"),
        action=row["action"],
        status=row["status"],
        detail=row.get("detail"),
        endpoint=row.get("endpoint"),
        created_at=row["created_at"],
        metadata=_loads(row.get("metadata"), {}),
    )


class RemoteManager(BaseManager):
    """Rows for remote jobs, the bundle they sent, and every attempt to talk to an endpoint."""

    tables = REMOTE_TABLES

    def register_handlers(self) -> None:
        self.coordinator.register("remote.job", self._apply_job)
        self.coordinator.register("remote.job_update", self._apply_job_update)
        self.coordinator.register("remote.attempt", self._apply_attempt)

    # -- write handlers ---------------------------------------------------
    _COLUMNS = (
        "id", "provider", "status", "config", "estimate", "actual", "outputs", "created_at",
        "completed_at", "error", "approved_by", "task_id", "kind", "dataset_id", "endpoint",
        "machine", "protocol", "bundle_sha256", "bundle_path", "claimed_sha256",
        "received_sha256", "artifact_path", "verified_at", "verify_note", "remote_job_id",
        "received_at", "refusal",
    )
    _JSON = ("config", "estimate", "actual", "outputs")

    def _apply_job(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        job = payload["job"]
        placeholders = ",".join("?" for _ in self._COLUMNS)
        values = tuple(
            json_text(job.get(name) or {}) if name in self._JSON else job.get(name)
            for name in self._COLUMNS
        )
        tx.execute(
            f"INSERT INTO remote_jobs({','.join(self._COLUMNS)}) VALUES ({placeholders})", values
        )
        return {"id": job["id"]}

    def _apply_job_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        job = payload["job"]
        assignments = ",".join(
            f"{name} = ?" for name in self._COLUMNS if name != "id"
        )
        values = tuple(
            json_text(job.get(name) or {}) if name in self._JSON else job.get(name)
            for name in self._COLUMNS if name != "id"
        ) + (job["id"],)
        tx.execute(f"UPDATE remote_jobs SET {assignments} WHERE id = ?", values)
        return {"id": job["id"]}

    def _apply_attempt(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        attempt = payload["attempt"]
        tx.execute(
            "INSERT INTO remote_attempts(id, job_id, action, status, detail, endpoint, created_at,"
            " metadata) VALUES (?,?,?,?,?,?,?,?)",
            (
                attempt["id"], attempt.get("job_id"), attempt["action"], attempt["status"],
                attempt.get("detail"), attempt.get("endpoint"), attempt["created_at"],
                json_text(attempt.get("metadata") or {}),
            ),
        )
        return {"id": attempt["id"]}

    # -- jobs -------------------------------------------------------------
    def create(
        self,
        *,
        provider: str,
        kind: str = "training",
        dataset_id: str | None = None,
        endpoint: str | None = None,
        bundle_sha256: str | None = None,
        bundle_path: str | None = None,
        config: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> RemoteJob:
        job = RemoteJob(
            id=new_id("rj_"),
            provider=provider,
            status="draft",
            kind=kind,
            dataset_id=dataset_id,
            endpoint=endpoint,
            bundle_sha256=bundle_sha256,
            bundle_path=bundle_path,
            config=dict(config or {}),
            task_id=task_id,
            created_at=iso_now(),
        )
        self._write("remote.job", {"job": job.to_dict()})
        self.trace(
            "remote", "remote.created", status="ok", task_id=task_id,
            payload={"job_id": job.id, "provider": provider, "endpoint": endpoint},
        )
        return job

    def update(self, job_id: str, *, status: str, **changes: Any) -> RemoteJob:
        if status not in STATUSES:
            raise ValidationError(f"unknown remote status: {status}")
        current = self.get(job_id)
        row = current.to_dict()
        row["status"] = status
        for key, value in changes.items():
            if key not in row:
                raise ValidationError(f"remote job has no field {key!r}")
            if value is not None:
                row[key] = value
        self._write("remote.job_update", {"job": row})
        self.trace(
            "remote", f"remote.{status}", status="ok",
            payload={"job_id": job_id, "endpoint": row.get("endpoint")},
        )
        return self.get(job_id)

    def get(self, wanted: str) -> RemoteJob:
        row = self.store.query_one(
            "SELECT * FROM remote_jobs WHERE id = ? OR id LIKE ?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (wanted, f"{wanted}%"),
        )
        if row is None:
            raise NotFoundError(f"no such remote job: {wanted}")
        return _job_from_row(row)

    def jobs(self, *, status: str | None = None, limit: int = 50) -> list[RemoteJob]:
        sql = "SELECT * FROM remote_jobs"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_job_from_row(row) for row in self.store.query(sql, params)]

    # -- attempts ---------------------------------------------------------
    def record_attempt(
        self,
        *,
        action: str,
        status: str,
        job_id: str | None = None,
        detail: str | None = None,
        endpoint: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RemoteAttempt:
        attempt = {
            "id": new_id("ra_"),
            "job_id": job_id,
            "action": action,
            "status": status,
            "detail": detail,
            "endpoint": endpoint,
            "created_at": iso_now(),
            "metadata": metadata or {},
        }
        self._write("remote.attempt", {"attempt": attempt})
        return RemoteAttempt(
            id=attempt["id"], job_id=job_id, action=action, status=status,
            detail=detail, endpoint=endpoint, created_at=attempt["created_at"],
            metadata=attempt["metadata"],
        )

    def attempts(self, *, job_id: str | None = None, limit: int = 50) -> list[RemoteAttempt]:
        sql = "SELECT * FROM remote_attempts"
        params: list[Any] = []
        if job_id:
            sql += " WHERE job_id = ?"
            params.append(job_id)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_attempt_from_row(row) for row in self.store.query(sql, params)]

    # -- overview ---------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        jobs = int(self.store.scalar("SELECT COUNT(*) FROM remote_jobs") or 0)
        by_status: dict[str, int] = {}
        for row in self.store.query(
            "SELECT status, COUNT(*) AS n FROM remote_jobs GROUP BY status"
        ):
            by_status[str(row["status"])] = int(row["n"])
        unverified = int(
            self.store.scalar(
                "SELECT COUNT(*) FROM remote_jobs WHERE status = 'received'"
                " AND (verified_at IS NULL OR received_sha256 != claimed_sha256)"
            )
            or 0
        )
        return {
            "jobs": jobs,
            "by_status": by_status,
            "attempts": int(self.store.scalar("SELECT COUNT(*) FROM remote_attempts") or 0),
            "unverified": unverified,
            "protocol": PROTOCOL,
            "statuses": list(STATUSES),
        }
