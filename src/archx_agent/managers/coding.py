"""Rows for the coding workspace: sessions, the edits made in them, and the runner's ledger.

The manager stores; :class:`archx_agent.application.coding.CodingWorkspace` decides. That split
is the same one every other domain here uses, and it matters for this one in particular: the
service is the only place that touches the filesystem, and it does so exclusively through the
tool layer, so a coding session cannot do anything a grant would not allow.

Three tables:

``code_sessions``
    A directory, a task and a status. Closing a session is explicit and does not delete it - the
    diffs and runs stay readable, which is the whole point of keeping them.

``code_changes``
    One row per edit, carrying a unified diff and the checksums on either side of it. The file on
    disk is the truth; this is the account of how it got there.

``code_runs``
    The runner's ledger. The command as typed, the argv that actually ran, the directory, the
    exit code, the duration and the output. A refusal is recorded too, because "this was
    attempted and the permission centre said no" is the evidence a permission system must keep.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

CODING_TABLES = ("code_sessions", "code_changes", "code_runs")

SESSION_STATUSES = ("open", "closed")
CHANGE_ACTIONS = ("create", "modify", "delete")
RUN_STATUSES = ("passed", "failed", "timeout", "error", "refused")


@dataclass
class CodeSession:
    id: str
    title: str
    root: str
    status: str
    task_id: str | None = None
    project_id: str | None = None
    note: str | None = None
    created_at: str = ""
    updated_at: str = ""
    closed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def open(self) -> bool:
        return self.status == "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "root": self.root,
            "status": self.status,
            "open": self.open,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "closed_at": self.closed_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class CodeChange:
    id: str
    session_id: str
    path: str
    action: str
    diff: str
    before_sha: str | None = None
    after_sha: str | None = None
    added: int = 0
    removed: int = 0
    artifact_id: str | None = None
    tool_run_id: str | None = None
    note: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "path": self.path,
            "action": self.action,
            "before_sha": self.before_sha,
            "after_sha": self.after_sha,
            "added": self.added,
            "removed": self.removed,
            "diff": self.diff,
            "artifact_id": self.artifact_id,
            "tool_run_id": self.tool_run_id,
            "note": self.note,
            "created_at": self.created_at,
        }


@dataclass
class CodeRun:
    id: str
    session_id: str
    command: str
    cwd: str
    status: str
    check_name: str | None = None
    argv: list[str] = field(default_factory=list)
    exit_code: int | None = None
    duration_ms: float | None = None
    timeout_seconds: int | None = None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    artifact_id: str | None = None
    tool_run_id: str | None = None
    replayed_from: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "check_name": self.check_name,
            "command": self.command,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "timeout_seconds": self.timeout_seconds,
            "timed_out": self.timed_out,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "artifact_id": self.artifact_id,
            "tool_run_id": self.tool_run_id,
            "replayed_from": self.replayed_from,
            "created_at": self.created_at,
        }


def _session_from_row(row: Mapping[str, Any]) -> CodeSession:
    try:
        metadata = json.loads(row["metadata"] or "{}")
    except (TypeError, ValueError):  # pragma: no cover - a hand-edited row
        metadata = {}
    return CodeSession(
        id=row["id"],
        title=row["title"],
        root=row["root"],
        status=row["status"],
        task_id=row["task_id"],
        project_id=row["project_id"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        closed_at=row["closed_at"],
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def _change_from_row(row: Mapping[str, Any]) -> CodeChange:
    return CodeChange(
        id=row["id"],
        session_id=row["session_id"],
        path=row["path"],
        action=row["action"],
        diff=row["diff"],
        before_sha=row["before_sha"],
        after_sha=row["after_sha"],
        added=int(row["added"] or 0),
        removed=int(row["removed"] or 0),
        artifact_id=row["artifact_id"],
        tool_run_id=row["tool_run_id"],
        note=row["note"],
        created_at=row["created_at"],
    )


def _run_from_row(row: Mapping[str, Any]) -> CodeRun:
    try:
        argv = json.loads(row["argv"] or "[]")
    except (TypeError, ValueError):  # pragma: no cover
        argv = []
    return CodeRun(
        id=row["id"],
        session_id=row["session_id"],
        command=row["command"],
        cwd=row["cwd"],
        status=row["status"],
        check_name=row["check_name"],
        argv=[str(part) for part in argv] if isinstance(argv, list) else [],
        exit_code=row["exit_code"],
        duration_ms=row["duration_ms"],
        timeout_seconds=row["timeout_seconds"],
        timed_out=bool(row["timed_out"]),
        stdout=row["stdout"] or "",
        stderr=row["stderr"] or "",
        artifact_id=row["artifact_id"],
        tool_run_id=row["tool_run_id"],
        replayed_from=row["replayed_from"],
        created_at=row["created_at"],
    )


class CodeManager(BaseManager):
    """Rows for coding sessions, their edits and their runs."""

    tables = CODING_TABLES

    def register_handlers(self) -> None:
        self.coordinator.register("coding.session", self._apply_session)
        self.coordinator.register("coding.session_update", self._apply_session_update)
        self.coordinator.register("coding.change", self._apply_change)
        self.coordinator.register("coding.run", self._apply_run)

    # -- write handlers ---------------------------------------------------
    def _apply_session(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        session: dict[str, Any] = payload["session"]
        tx.execute(
            "INSERT INTO code_sessions(id, title, root, status, task_id, project_id, note,"
            " created_at, updated_at, closed_at, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                session["id"], session["title"], session["root"], session["status"],
                session.get("task_id"), session.get("project_id"), session.get("note"),
                session["created_at"], session["updated_at"], session.get("closed_at"),
                json_text(session.get("metadata") or {}),
            ),
        )
        return {"id": session["id"]}

    def _apply_session_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload["id"]
        fields = dict(payload.get("fields") or {})
        if not fields:
            return {"id": session_id, "changed": 0}
        allowed = {"title", "status", "note", "closed_at", "updated_at", "task_id", "metadata"}
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValidationError(f"cannot update code session field(s): {', '.join(unknown)}")
        if "metadata" in fields:
            fields["metadata"] = json_text(fields["metadata"] or {})
        assignments = ", ".join(f"{name} = ?" for name in fields)
        tx.execute(
            f"UPDATE code_sessions SET {assignments} WHERE id = ?",
            (*fields.values(), session_id),
        )
        return {"id": session_id, "changed": len(fields)}

    def _apply_change(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        change: dict[str, Any] = payload["change"]
        tx.execute(
            "INSERT INTO code_changes(id, session_id, path, action, before_sha, after_sha,"
            " added, removed, diff, artifact_id, tool_run_id, note, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                change["id"], change["session_id"], change["path"], change["action"],
                change.get("before_sha"), change.get("after_sha"), int(change.get("added") or 0),
                int(change.get("removed") or 0), change.get("diff") or "",
                change.get("artifact_id"), change.get("tool_run_id"), change.get("note"),
                change["created_at"],
            ),
        )
        return {"id": change["id"]}

    def _apply_run(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        run: dict[str, Any] = payload["run"]
        tx.execute(
            "INSERT INTO code_runs(id, session_id, check_name, command, argv, cwd, status,"
            " exit_code, duration_ms, timeout_seconds, timed_out, stdout, stderr, artifact_id,"
            " tool_run_id, replayed_from, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run["id"], run["session_id"], run.get("check_name"), run["command"],
                json_text(run.get("argv") or []), run["cwd"], run["status"],
                run.get("exit_code"), run.get("duration_ms"), run.get("timeout_seconds"),
                1 if run.get("timed_out") else 0,
                run.get("stdout") or "", run.get("stderr") or "", run.get("artifact_id"),
                run.get("tool_run_id"), run.get("replayed_from"), run["created_at"],
            ),
        )
        return {"id": run["id"]}

    # -- writes -----------------------------------------------------------
    def create_session(
        self,
        *,
        title: str,
        root: str,
        task_id: str | None = None,
        project_id: str | None = None,
        note: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CodeSession:
        now = iso_now()
        session = CodeSession(
            id=new_id("cs_"),
            title=_clean_title(title),
            root=root,
            status="open",
            task_id=task_id,
            project_id=project_id,
            note=note,
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        self._write("coding.session", {"session": session.to_dict()})
        self.trace(
            "code", "code.session", status="ok", task_id=task_id, project_id=project_id,
            payload={"session_id": session.id, "root": root, "title": session.title},
        )
        return session

    def touch(self, session_id: str, **fields: Any) -> CodeSession:
        self.get_session(session_id)
        payload = {"id": session_id, "fields": {**fields, "updated_at": iso_now()}}
        self._write("coding.session_update", payload)
        return self.get_session(session_id)

    def close_session(self, session_id: str, note: str | None = None) -> CodeSession:
        session = self.get_session(session_id)
        if not session.open:
            raise ValidationError(f"code session {session.id} is already closed")
        now = iso_now()
        self._write(
            "coding.session_update",
            {"id": session_id, "fields": {"status": "closed", "closed_at": now,
                                          "updated_at": now, "note": note or session.note}},
        )
        self.trace(
            "code", "code.closed", status="ok", task_id=session.task_id,
            payload={"session_id": session_id, "note": note or ""},
        )
        return self.get_session(session_id)

    def record_change(
        self,
        session_id: str,
        *,
        path: str,
        action: str,
        diff: str,
        before_sha: str | None = None,
        after_sha: str | None = None,
        added: int = 0,
        removed: int = 0,
        artifact_id: str | None = None,
        tool_run_id: str | None = None,
        note: str | None = None,
    ) -> CodeChange:
        if action not in CHANGE_ACTIONS:
            raise ValidationError(f"unknown change action: {action}")
        session = self.get_session(session_id)
        change = CodeChange(
            id=new_id("cc_"),
            session_id=session_id,
            path=path,
            action=action,
            diff=diff,
            before_sha=before_sha,
            after_sha=after_sha,
            added=int(added),
            removed=int(removed),
            artifact_id=artifact_id,
            tool_run_id=tool_run_id,
            note=note,
            created_at=iso_now(),
        )
        self._write("coding.change", {"change": change.to_dict()})
        self.touch(session_id)
        self.trace(
            "code", "code.change", status="ok", task_id=session.task_id,
            project_id=session.project_id,
            payload={
                "session_id": session_id, "change_id": change.id, "path": path,
                "action": action, "added": change.added, "removed": change.removed,
            },
        )
        return change

    def record_run(
        self,
        session_id: str,
        *,
        command: str,
        cwd: str,
        status: str,
        check_name: str | None = None,
        argv: Sequence[str] = (),
        exit_code: int | None = None,
        duration_ms: float | None = None,
        timeout_seconds: int | None = None,
        timed_out: bool = False,
        stdout: str = "",
        stderr: str = "",
        artifact_id: str | None = None,
        tool_run_id: str | None = None,
        replayed_from: str | None = None,
    ) -> CodeRun:
        if status not in RUN_STATUSES:
            raise ValidationError(f"unknown run status: {status}")
        session = self.get_session(session_id)
        run = CodeRun(
            id=new_id("cr_"),
            session_id=session_id,
            command=command,
            cwd=cwd,
            status=status,
            check_name=check_name,
            argv=[str(part) for part in argv],
            exit_code=exit_code,
            duration_ms=duration_ms,
            timeout_seconds=timeout_seconds,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
            artifact_id=artifact_id,
            tool_run_id=tool_run_id,
            replayed_from=replayed_from,
            created_at=iso_now(),
        )
        self._write("coding.run", {"run": run.to_dict()})
        self.touch(session_id)
        self.trace(
            "code", "code.run", status="ok" if status == "passed" else "error",
            task_id=session.task_id, project_id=session.project_id,
            payload={
                "session_id": session_id, "run_id": run.id, "command": command,
                "status": status, "exit_code": exit_code, "duration_ms": duration_ms,
                "check": check_name,
            },
        )
        return run

    # -- reads ------------------------------------------------------------
    def get_session(self, session_id: str) -> CodeSession:
        row = self.store.query_one("SELECT * FROM code_sessions WHERE id = ?", (session_id,))
        if row is None:
            raise NotFoundError(f"no such code session: {session_id}")
        return _session_from_row(row)

    def find_session(self, session_id: str) -> CodeSession | None:
        row = self.store.query_one("SELECT * FROM code_sessions WHERE id = ?", (session_id,))
        return _session_from_row(row) if row else None

    def sessions(
        self, *, status: str | None = None, limit: int = 50, root: str | None = None
    ) -> list[CodeSession]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if root:
            clauses.append("root = ?")
            params.append(root)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.store.query(
            f"SELECT * FROM code_sessions{where} ORDER BY created_at DESC, id DESC LIMIT ?",
            (*params, int(limit)),
        )
        return [_session_from_row(row) for row in rows]

    def latest_open(self, root: str | None = None) -> CodeSession | None:
        sessions = self.sessions(status="open", limit=1, root=root)
        return sessions[0] if sessions else None

    def changes(self, session_id: str, *, limit: int = 100) -> list[CodeChange]:
        rows = self.store.query(
            "SELECT * FROM code_changes WHERE session_id = ? ORDER BY created_at, id LIMIT ?",
            (session_id, int(limit)),
        )
        return [_change_from_row(row) for row in rows]

    def runs(self, session_id: str, *, limit: int = 100) -> list[CodeRun]:
        rows = self.store.query(
            "SELECT * FROM code_runs WHERE session_id = ? ORDER BY created_at, id LIMIT ?",
            (session_id, int(limit)),
        )
        return [_run_from_row(row) for row in rows]

    def find_run(self, run_id: str) -> CodeRun | None:
        row = self.store.query_one("SELECT * FROM code_runs WHERE id = ?", (run_id,))
        return _run_from_row(row) if row else None

    def get_run(self, run_id: str) -> CodeRun:
        run = self.find_run(run_id)
        if run is None:
            raise NotFoundError(f"no such code run: {run_id}")
        return run

    def last_run(self, session_id: str, check_name: str | None = None) -> CodeRun | None:
        if check_name:
            row = self.store.query_one(
                "SELECT * FROM code_runs WHERE session_id = ? AND check_name = ?"
                " ORDER BY created_at DESC, id DESC LIMIT 1",
                (session_id, check_name),
            )
        else:
            row = self.store.query_one(
                "SELECT * FROM code_runs WHERE session_id = ?"
                " ORDER BY created_at DESC, id DESC LIMIT 1",
                (session_id,),
            )
        return _run_from_row(row) if row else None

    def stats(self) -> dict[str, Any]:
        open_sessions = int(
            self.store.scalar("SELECT COUNT(*) FROM code_sessions WHERE status = 'open'") or 0
        )
        return {
            "sessions": self.table_count("code_sessions"),
            "open": open_sessions,
            "changes": self.table_count("code_changes"),
            "runs": self.table_count("code_runs"),
            "failed_runs": int(
                self.store.scalar("SELECT COUNT(*) FROM code_runs WHERE status != 'passed'") or 0
            ),
        }


def _clean_title(title: str | None) -> str:
    text = (title or "").strip()
    return (text or "coding session")[:200]
