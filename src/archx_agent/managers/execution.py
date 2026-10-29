"""Rows for *where* a command ran, and what it changed.

M37 recorded results that came back from another machine. This milestone records the other half of
the question: a command, the environment it was executed in, and the files that came back - so that
"it ran in a sandbox" is a row with a backend name on it rather than a claim in a README.

Three tables:

``execution_targets``
    a backend the user chose (``local``, ``remote``, ``docker``, ``wsl``, ``windows-sandbox``,
    ``vmware``, ``virtualbox``), what it needs, and - when it cannot be used - why not. A target is a
    row because the same command on a different target is a different run.

``execution_runs``
    one row per command, with the exact invocation that was executed (the wrapper included), the
    exit code, the duration, and the output as both text and an artifact. ``detached`` marks a run
    whose result cannot be streamed back (Windows Sandbox reports nothing to a parent process), so a
    reader is never told "no output" when the truth is "output not retrievable".

``execution_files``
    the ledger of what crossed the boundary: ``push`` (this machine -> the target) and ``pull`` (the
    target -> this machine), each with both hashes. It exists so a pull can refuse to overwrite an
    edit that happened here while the work was happening there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

EXECUTION_TABLES = ("execution_targets", "execution_runs", "execution_files")

KINDS = ("local", "remote", "docker", "wsl", "windows-sandbox", "vmware", "virtualbox")
STATUSES = ("ok", "failed", "timeout", "refused", "detached", "conflict")


@dataclass
class ExecutionTarget:
    id: str
    kind: str
    name: str
    created_at: str
    endpoint: str | None = None
    spec: dict[str, Any] = field(default_factory=dict)
    status: str = "unknown"
    refusal: str | None = None
    last_probe_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "endpoint": self.endpoint,
            "spec": dict(self.spec),
            "status": self.status,
            "refusal": self.refusal,
            "created_at": self.created_at,
            "last_probe_at": self.last_probe_at,
        }


@dataclass
class ExecutionRun:
    id: str
    kind: str
    command: str
    status: str
    started_at: str
    target_id: str | None = None
    invocation: str | None = None
    cwd: str | None = None
    exit_code: int | None = None
    duration_ms: float | None = None
    stdout: str | None = None
    stderr: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    truncated: bool = False
    detached: bool = False
    note: str | None = None
    remote_job_id: str | None = None
    task_id: str | None = None
    ended_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target_id": self.target_id,
            "kind": self.kind,
            "command": self.command,
            "invocation": self.invocation,
            "cwd": self.cwd,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "truncated": bool(self.truncated),
            "detached": bool(self.detached),
            "note": self.note,
            "remote_job_id": self.remote_job_id,
            "task_id": self.task_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


@dataclass
class ExecutionFile:
    id: str
    path: str
    direction: str
    status: str
    created_at: str
    run_id: str | None = None
    target_id: str | None = None
    sha256_local: str | None = None
    sha256_remote: str | None = None
    bytes: int | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "target_id": self.target_id,
            "path": self.path,
            "direction": self.direction,
            "sha256_local": self.sha256_local,
            "sha256_remote": self.sha256_remote,
            "bytes": self.bytes,
            "status": self.status,
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


def _target_from_row(row: Mapping[str, Any]) -> ExecutionTarget:
    return ExecutionTarget(
        id=row["id"],
        kind=row["kind"],
        name=row["name"],
        endpoint=row.get("endpoint"),
        spec=_loads(row.get("spec"), {}),
        status=row.get("status") or "unknown",
        refusal=row.get("refusal"),
        created_at=row["created_at"],
        last_probe_at=row.get("last_probe_at"),
    )


def _run_from_row(row: Mapping[str, Any]) -> ExecutionRun:
    return ExecutionRun(
        id=row["id"],
        target_id=row.get("target_id"),
        kind=row["kind"],
        command=row["command"],
        invocation=row.get("invocation"),
        cwd=row.get("cwd"),
        status=row["status"],
        exit_code=row.get("exit_code"),
        duration_ms=row.get("duration_ms"),
        stdout=row.get("stdout"),
        stderr=row.get("stderr"),
        stdout_path=row.get("stdout_path"),
        stderr_path=row.get("stderr_path"),
        truncated=bool(row.get("truncated")),
        detached=bool(row.get("detached")),
        note=row.get("note"),
        remote_job_id=row.get("remote_job_id"),
        task_id=row.get("task_id"),
        started_at=row["started_at"],
        ended_at=row.get("ended_at"),
    )


def _file_from_row(row: Mapping[str, Any]) -> ExecutionFile:
    return ExecutionFile(
        id=row["id"],
        run_id=row.get("run_id"),
        target_id=row.get("target_id"),
        path=row["path"],
        direction=row["direction"],
        sha256_local=row.get("sha256_local"),
        sha256_remote=row.get("sha256_remote"),
        bytes=row.get("bytes"),
        status=row["status"],
        note=row.get("note"),
        created_at=row["created_at"],
    )


class ExecutionManager(BaseManager):
    """Where things may run, what ran where, and which files crossed the boundary."""

    tables = EXECUTION_TABLES

    def register_handlers(self) -> None:
        self.coordinator.register("execution.target", self._apply_target)
        self.coordinator.register("execution.target_update", self._apply_target_update)
        self.coordinator.register("execution.run", self._apply_run)
        self.coordinator.register("execution.run_update", self._apply_run_update)
        self.coordinator.register("execution.file", self._apply_file)

    _TARGET_COLUMNS = ("id", "kind", "name", "endpoint", "spec", "status", "refusal",
                       "created_at", "last_probe_at")
    _RUN_COLUMNS = ("id", "target_id", "kind", "command", "invocation", "cwd", "status",
                    "exit_code", "duration_ms", "stdout", "stderr", "stdout_path", "stderr_path",
                    "truncated", "detached", "note", "remote_job_id", "task_id", "started_at",
                    "ended_at")
    _FILE_COLUMNS = ("id", "run_id", "target_id", "path", "direction", "sha256_local",
                     "sha256_remote", "bytes", "status", "note", "created_at")

    def _apply_target(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        target = payload["target"]
        placeholders = ",".join("?" for _ in self._TARGET_COLUMNS)
        values = tuple(
            json_text(target.get(name) or {}) if name == "spec" else target.get(name)
            for name in self._TARGET_COLUMNS
        )
        tx.execute(
            f"INSERT INTO execution_targets({','.join(self._TARGET_COLUMNS)})"
            f" VALUES ({placeholders})",
            values,
        )
        return {"id": target["id"]}

    def _apply_target_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        target = payload["target"]
        assignments = ",".join(f"{name} = ?" for name in self._TARGET_COLUMNS if name != "id")
        values = tuple(
            json_text(target.get(name) or {}) if name == "spec" else target.get(name)
            for name in self._TARGET_COLUMNS if name != "id"
        ) + (target["id"],)
        tx.execute(f"UPDATE execution_targets SET {assignments} WHERE id = ?", values)
        return {"id": target["id"]}

    def _apply_run(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run = payload["run"]
        placeholders = ",".join("?" for _ in self._RUN_COLUMNS)
        values = tuple(
            int(run.get(name)) if name in ("truncated", "detached") else run.get(name)
            for name in self._RUN_COLUMNS
        )
        tx.execute(
            f"INSERT INTO execution_runs({','.join(self._RUN_COLUMNS)}) VALUES ({placeholders})",
            values,
        )
        return {"id": run["id"]}

    def _apply_run_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run = payload["run"]
        assignments = ",".join(f"{name} = ?" for name in self._RUN_COLUMNS if name != "id")
        values = tuple(
            int(run.get(name)) if name in ("truncated", "detached") else run.get(name)
            for name in self._RUN_COLUMNS if name != "id"
        ) + (run["id"],)
        tx.execute(f"UPDATE execution_runs SET {assignments} WHERE id = ?", values)
        return {"id": run["id"]}

    def _apply_file(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        item = payload["file"]
        placeholders = ",".join("?" for _ in self._FILE_COLUMNS)
        tx.execute(
            f"INSERT INTO execution_files({','.join(self._FILE_COLUMNS)}) VALUES ({placeholders})",
            tuple(item.get(name) for name in self._FILE_COLUMNS),
        )
        return {"id": item["id"]}

    # -- targets ----------------------------------------------------------
    def add_target(
        self, *, kind: str, name: str, endpoint: str | None = None,
        spec: dict[str, Any] | None = None, status: str = "probed", refusal: str | None = None,
    ) -> ExecutionTarget:
        if kind not in KINDS:
            raise ValidationError(f"unknown execution backend {kind!r} (this build knows {', '.join(KINDS)})")
        target = ExecutionTarget(
            id=new_id("xt_"), kind=kind, name=name, endpoint=endpoint,
            spec=dict(spec or {}), status=status, refusal=refusal,
            created_at=iso_now(), last_probe_at=iso_now(),
        )
        self._write("execution.target", {"target": target.to_dict()})
        self.trace("execution", "execution.target_added", status="ok",
                   payload={"target_id": target.id, "kind": kind})
        return target

    def target(self, wanted: str) -> ExecutionTarget:
        row = self.store.query_one(
            "SELECT * FROM execution_targets WHERE id = ? OR name = ? ORDER BY rowid DESC LIMIT 1",
            (wanted, wanted),
        )
        if row is None:
            raise NotFoundError(f"no such execution target: {wanted}")
        return _target_from_row(row)

    def targets(self) -> list[ExecutionTarget]:
        return [
            _target_from_row(row)
            for row in self.store.query("SELECT * FROM execution_targets ORDER BY rowid")
        ]

    def update_target(self, target_id: str, **changes: Any) -> ExecutionTarget:
        current = self.target(target_id).to_dict()
        for key, value in changes.items():
            if key not in current:
                raise ValidationError(f"an execution target has no field {key!r}")
            current[key] = value
        self._write("execution.target_update", {"target": current})
        return self.target(target_id)

    # -- runs -------------------------------------------------------------
    def begin(
        self, *, kind: str, command: str, target_id: str | None, cwd: str | None,
        invocation: str | None = None, task_id: str | None = None,
    ) -> ExecutionRun:
        run = ExecutionRun(
            id=new_id("xr_"), kind=kind, command=command, target_id=target_id, cwd=cwd,
            invocation=invocation, status="running", started_at=iso_now(), task_id=task_id,
        )
        self._write("execution.run", {"run": run.to_dict()})
        return run

    def finish(self, run_id: str, **changes: Any) -> ExecutionRun:
        run = self.run_(run_id).to_dict()
        for key, value in changes.items():
            if key not in run:
                raise ValidationError(f"an execution run has no field {key!r}")
            run[key] = value
        run["ended_at"] = run.get("ended_at") or iso_now()
        self._write("execution.run_update", {"run": run})
        return self.run_(run_id)

    def run_(self, wanted: str) -> ExecutionRun:
        row = self.store.query_one(
            "SELECT * FROM execution_runs WHERE id = ? OR id LIKE ?"
            " ORDER BY rowid DESC LIMIT 1",
            (wanted, f"{wanted}%"),
        )
        if row is None:
            raise NotFoundError(f"no such execution run: {wanted}")
        return _run_from_row(row)

    def runs(self, *, target_id: str | None = None, status: str | None = None,
             limit: int = 50) -> list[ExecutionRun]:
        sql = "SELECT * FROM execution_runs"
        clauses: list[str] = []
        params: list[Any] = []
        if target_id:
            clauses.append("target_id = ?")
            params.append(target_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_run_from_row(row) for row in self.store.query(sql, params)]

    # -- files ------------------------------------------------------------
    def record_file(
        self, *, path: str, direction: str, status: str, run_id: str | None = None,
        target_id: str | None = None, sha256_local: str | None = None,
        sha256_remote: str | None = None, size: int | None = None, note: str | None = None,
    ) -> ExecutionFile:
        item = ExecutionFile(
            id=new_id("xf_"), path=path, direction=direction, status=status,
            sha256_local=sha256_local, sha256_remote=sha256_remote, bytes=size,
            note=note, run_id=run_id, target_id=target_id, created_at=iso_now(),
        )
        self._write("execution.file", {"file": item.to_dict()})
        return item

    def files(self, *, target_id: str | None = None, direction: str | None = None,
              limit: int = 200) -> list[ExecutionFile]:
        sql = "SELECT * FROM execution_files"
        clauses: list[str] = []
        params: list[Any] = []
        if target_id:
            clauses.append("target_id = ?")
            params.append(target_id)
        if direction:
            clauses.append("direction = ?")
            params.append(direction)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_file_from_row(row) for row in self.store.query(sql, params)]

    def last_push(self, target_id: str, path: str) -> ExecutionFile | None:
        """What this machine last sent for a path - the base a pull compares against."""
        row = self.store.query_one(
            "SELECT * FROM execution_files WHERE target_id = ? AND path = ? AND direction = 'push'"
            " ORDER BY rowid DESC LIMIT 1",
            (target_id, path),
        )
        return _file_from_row(row) if row else None

    # -- overview ---------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for row in self.store.query(
            "SELECT kind, COUNT(*) AS n FROM execution_runs GROUP BY kind"
        ):
            by_kind[str(row["kind"])] = int(row["n"])
        return {
            "targets": int(self.store.scalar("SELECT COUNT(*) FROM execution_targets") or 0),
            "runs": int(self.store.scalar("SELECT COUNT(*) FROM execution_runs") or 0),
            "files": int(self.store.scalar("SELECT COUNT(*) FROM execution_files") or 0),
            "conflicts": int(
                self.store.scalar(
                    "SELECT COUNT(*) FROM execution_files WHERE status = 'conflict'"
                )
                or 0
            ),
            "by_kind": by_kind,
            "kinds": list(KINDS),
            "statuses": list(STATUSES),
        }
