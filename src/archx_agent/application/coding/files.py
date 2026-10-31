"""Files operations for coding sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.coding import CodeChange, CodeSession
from archx_agent.application.coding.patches import _unified_diff

from .records import _Before


class CodingWorkspaceFilesMixin:
    """Files responsibility for CodingWorkspace."""

    def read(
        self,
        session_id: str,
        path: str,
        *,
        start_line: int = 1,
        max_lines: int | None = None,
    ) -> dict[str, Any]:
        session = self._session(session_id)
        absolute = self._resolve(session, path)
        arguments: dict[str, Any] = {"path": absolute}
        if start_line and int(start_line) > 1:
            arguments["start_line"] = int(start_line)
        if max_lines:
            arguments["max_lines"] = int(max_lines)
        run = self._execute(
            "fs.read", arguments, self._context(session, f"code read {path}")
        )
        result = dict(run.result or {})
        result["session_id"] = session_id
        result["display_path"] = self._relative(session, absolute)
        return result

    def list_dir(
        self, session_id: str, path: str = ".", *, limit: int = 200
    ) -> dict[str, Any]:
        session = self._session(session_id)
        absolute = (
            self._resolve(session, path) if path not in {".", ""} else session.root
        )
        run = self._execute(
            "fs.list",
            {"path": absolute, "limit": int(limit)},
            self._context(session, f"code list {path}"),
        )
        return dict(run.result or {})

    def write(
        self,
        session_id: str,
        path: str,
        content: str,
        *,
        note: str | None = None,
    ) -> CodeChange:
        """Create or replace a file, recording a unified diff and attaching it to the task."""
        session = self._session(session_id)
        if not isinstance(content, str):
            raise ValidationError("content must be a string")
        absolute = self._resolve(session, path)
        before = self._before(session, absolute)
        run = self._execute(
            "fs.write",
            {"path": absolute, "content": content, "create_parents": True},
            self._context(session, f"code write {path}"),
        )
        result = dict(run.result or {})
        after_text = content
        action = "modify" if result.get("existed") else "create"
        diff, added, removed = _unified_diff(
            self._relative(session, absolute),
            before.text,
            after_text,
            before_available=before.available,
        )
        return self._record_change(
            session,
            path=absolute,
            action=action,
            diff=diff,
            added=added,
            removed=removed,
            before_sha=before.sha,
            after_sha=str(result.get("sha256") or ""),
            tool_run_id=run.id,
            note=note,
            unavailable=before.reason,
        )

    def delete(
        self, session_id: str, path: str, *, note: str | None = None
    ) -> CodeChange:
        session = self._session(session_id)
        absolute = self._resolve(session, path)
        before = self._before(session, absolute)
        run = self._execute(
            "fs.delete",
            {"path": absolute},
            self._context(session, f"code delete {path}"),
        )
        diff, added, removed = _unified_diff(
            self._relative(session, absolute),
            before.text,
            "",
            before_available=before.available,
        )
        return self._record_change(
            session,
            path=absolute,
            action="delete",
            diff=diff,
            added=added,
            removed=removed,
            before_sha=before.sha,
            after_sha=None,
            tool_run_id=run.id,
            note=note,
            unavailable=before.reason,
        )

    def _before(self, session: CodeSession, absolute: str) -> "_Before":
        """The current text, read through the tool layer so the diff is over what a grant allows.

        If reading is not allowed this does *not* raise: it asks the permission centre whether a
        read would be permitted, without requesting an approval. Editing a file you may write but
        not read is legitimate (a generated config), and turning one `code write` into two pending
        approvals would be noise. The change row then says the diff shows only the new content.
        """
        if not Path(absolute).exists():
            return _Before(text="", sha=None, available=True)
        decision = self.ws.permissions.check(
            "fs.read",
            subject="fs.read",
            task_id=session.task_id,
            project_id=session.project_id,
            consume=False,
            purpose="code: previous content for a diff",
            request_approval_on_denial=False,
        )
        if not decision.allowed:
            return _Before(
                text="",
                sha=None,
                available=False,
                reason="fs.read is not granted, so this diff shows the new content only",
            )
        try:
            run = self._execute(
                "fs.read",
                {"path": absolute},
                self._context(session, "code read before edit"),
            )
        except (ToolError, PermissionDeniedError):
            # Cannot read it (binary, too large): the write still happens if it is allowed, but
            # there is no honest diff to show, and the row says so.
            return _Before(
                text="",
                sha=None,
                available=False,
                reason="the previous content could not be read as text",
            )
        result = dict(run.result or {})
        available = not bool(result.get("truncated"))
        return _Before(
            text=str(result.get("content") or ""),
            sha=str(result.get("sha256") or "") or None,
            available=available,
            reason=""
            if available
            else "the previous content was larger than tools.max_file_bytes",
        )

    def _record_change(
        self,
        session: CodeSession,
        *,
        path: str,
        action: str,
        diff: str,
        added: int,
        removed: int,
        before_sha: str | None,
        after_sha: str | None,
        tool_run_id: str | None,
        note: str | None,
        unavailable: str = "",
    ) -> CodeChange:
        relative = self._relative(session, path)
        if not diff:
            why = unavailable or "there was nothing to compare against"
            diff = f"# {relative}: {action} - {why}\n"
        artifact_id = None
        if session.task_id and getattr(self.ws, "tasks", None) is not None:
            artifact_id = self._attach(
                session,
                self._patch_file(session, relative, diff),
                kind="diff",
                name=f"{relative}.diff",
            )
            try:
                self.ws.tasks.log(
                    session.task_id,
                    "edit",
                    detail=f"{action} {relative} (+{added}/-{removed})",
                )
            except Exception:  # noqa: BLE001 - the ledger is the source of truth
                pass
        return self.manager.record_change(
            session.id,
            path=relative,
            action=action,
            diff=diff,
            before_sha=before_sha,
            after_sha=after_sha,
            added=added,
            removed=removed,
            artifact_id=artifact_id,
            tool_run_id=tool_run_id,
            note=note,
        )

    def _patch_file(self, session: CodeSession, relative: str, diff: str) -> Path:
        folder = self._workspace_dir(session)
        safe = relative.replace("/", "_").replace("\\", "_")[:120] or "file"
        target = folder / f"{iso_now().replace(':', '').replace('-', '')}-{safe}.diff"
        counter = 1
        while target.exists():
            target = folder / f"{target.stem}-{counter}.diff"
            counter += 1
        target.write_text(diff, encoding="utf-8")
        return target

    def _workspace_dir(self, session: CodeSession) -> Path:
        base = Path(self.ws.config.path("paths.artifacts")) / "coding" / session.id
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _attach(
        self, session: CodeSession, path: Path, *, kind: str, name: str
    ) -> str | None:
        try:
            artifact = self.ws.tasks.attach_artifact(
                session.task_id, str(path), kind=kind, name=name
            )
            return artifact.id
        except Exception:  # noqa: BLE001 - losing the artifact must not lose the change
            return None

    def changes(self, session_id: str) -> list[CodeChange]:
        self._session(session_id, require_open=False)
        return self.manager.changes(session_id)

    def diff(self, session_id: str, *, attach: bool = True) -> dict[str, Any]:
        """The session's whole patch, from the first edit to the last."""
        session = self._session(session_id, require_open=False)
        changes = self.manager.changes(session_id)
        body = "".join(change.diff for change in changes)
        artifact_id = None
        if attach and body and session.task_id:
            target = self._workspace_dir(session) / "session.patch"
            target.write_text(body, encoding="utf-8")
            artifact_id = self._attach(
                session, target, kind="patch", name="session.patch"
            )
        return {
            "session_id": session_id,
            "patch": body,
            "files": sorted({change.path for change in changes}),
            "added": sum(change.added for change in changes),
            "removed": sum(change.removed for change in changes),
            "artifact_id": artifact_id,
        }
