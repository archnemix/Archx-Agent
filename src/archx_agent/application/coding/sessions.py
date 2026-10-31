"""Sessions operations for coding sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    NotFoundError,
    ToolError,
    ValidationError,
)
from archx_agent.managers.coding import CodeSession
from archx_agent.application.coding.constants import CHECKS_FILE


class CodingWorkspaceSessionsMixin:
    """Sessions responsibility for CodingWorkspace."""

    def _session(self, session_id: str, *, require_open: bool = True) -> CodeSession:
        session = self.manager.get_session(session_id)
        if require_open and not session.open:
            raise ValidationError(
                f"code session {session.id} is closed; open a new one to keep working"
            )
        return session

    def _resolve(self, session: CodeSession, path: str) -> str:
        """An absolute path inside the session root, resolved by the tool runtime's own rules."""
        candidate = Path(str(path or "").strip())
        if not str(candidate):
            raise ValidationError("a path is required")
        root = Path(session.root)
        target = candidate if candidate.is_absolute() else root / candidate
        try:
            resolved = target.resolve()
        except OSError as exc:  # pragma: no cover - pathological path
            raise ValidationError(f"cannot resolve {path}: {exc}") from exc
        root_resolved = root.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise ValidationError(
                f"{path} is outside the session root ({root_resolved}); "
                "open a session on that directory instead"
            )
        # The runtime is the authority on the tool roots as a whole; asking it keeps one rule.
        self.ws.tools.runtime.resolve(str(resolved))
        return str(resolved)

    @staticmethod
    def _relative(session: CodeSession, absolute: str) -> str:
        try:
            return str(Path(absolute).relative_to(Path(session.root).resolve()))
        except ValueError:  # pragma: no cover - _resolve guarantees containment
            return absolute

    def _commit_root(self, root: str | None) -> str:
        roots = self.ws.tools.roots()
        if not roots:
            raise ToolError(
                "no tool roots are configured, so there is nowhere to open a session; "
                "set tools.roots or run inside a project"
            )
        target = Path(root).expanduser() if root else Path(roots[0])
        resolved = self.ws.tools.runtime.resolve(str(target))
        if not resolved.is_dir():
            raise NotFoundError(
                f"no such directory: {resolved} (create it first, or open on an existing one)"
            )
        return str(resolved)

    def open(
        self,
        root: str | Path | None = None,
        *,
        title: str | None = None,
        note: str | None = None,
        project_id: str | None = None,
    ) -> CodeSession:
        """Open a session on a directory, with a task of its own to record it."""
        session_root = self._commit_root(str(root) if root is not None else None)
        label = (title or "").strip() or Path(session_root).name or "coding session"
        task = None
        if getattr(self.ws, "tasks", None) is not None:
            # `manual=True` because this task spans more than one command: the user works in the
            # session across many CLI invocations, so the process that created the task exiting is
            # not the task ending. Without it, the second command would open the workspace, sweep
            # the first process's "running" task to `interrupted`, and lose the record.
            task = self.ws.tasks.create(
                "coding",
                title=f"code: {label}",
                start=True,
                manual=True,
                project_id=project_id,
                tools=["fs.read", "fs.write", "fs.delete", "shell.run"],
                inputs=[],
                metadata={"root": session_root, "code_session": True},
            )
        session = self.manager.create_session(
            title=label,
            root=session_root,
            task_id=task.id if task else None,
            project_id=project_id,
            note=note,
            metadata={"checks_file": CHECKS_FILE},
        )
        if task is not None:
            self.manager.trace(
                "code",
                "code.session",
                status="ok",
                task_id=task.id,
                payload={"session_id": session.id, "linked": True},
            )
            self.ws.tasks.log(
                session.task_id,
                "code",
                detail=f"session {session.id} on {session_root}",
            )
        return session

    def sessions(
        self, *, status: str | None = None, limit: int = 50
    ) -> list[CodeSession]:
        return self.manager.sessions(status=status, limit=limit)

    def session(self, session_id: str) -> CodeSession:
        return self.manager.get_session(session_id)

    def show(self, session_id: str) -> dict[str, Any]:
        """One session with everything worth seeing: changes, runs, checks, the task."""
        session = self._session(session_id, require_open=False)
        changes = self.manager.changes(session_id)
        runs = self.manager.runs(session_id)
        return {
            "session": session.to_dict(),
            "changes": [change.to_dict() for change in changes],
            "runs": [run.to_dict() for run in runs],
            "stats": {
                "changes": len(changes),
                "added": sum(change.added for change in changes),
                "removed": sum(change.removed for change in changes),
                "runs": len(runs),
                "failed": sum(1 for run in runs if run.status != "passed"),
            },
            "task": self._task_summary(session),
        }

    def _task_summary(self, session: CodeSession) -> dict[str, Any] | None:
        if not session.task_id or getattr(self.ws, "tasks", None) is None:
            return None
        found = self.ws.tasks.find(session.task_id)
        return found.unwrap().to_dict() if found.ok else None

    def close(self, session_id: str, note: str | None = None) -> CodeSession:
        session = self._session(session_id, require_open=False)
        closed = self.manager.close_session(session_id, note=note)
        if session.task_id and getattr(self.ws, "tasks", None) is not None:
            try:
                self.ws.tasks.complete(
                    session.task_id, summary=note or f"closed {session_id}"
                )
            except Exception:  # noqa: BLE001 - a closed session must not hinge on the task
                pass
        return closed
