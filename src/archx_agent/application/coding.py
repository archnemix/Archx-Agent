"""The coding workspace: edit, run and test code, with every step going through the tool layer.

The rule this module exists to keep
-----------------------------------
**A coding session is not a way around the permission centre.** Every file read, every write and
every command goes through :meth:`ToolManager.execute`, which means the same capabilities, the same
grants and the same approvals as `archx-agent tools run fs.write`. There is no private back door
for the editor: if `fs.write` is not granted, `code write` is refused, and the refusal names the
approval rather than half-writing the file.

What that buys
--------------
* **Edits are reviewable.** Each one is a row with a unified diff, the checksums either side of
  it, and an artifact attached to the session's task. `code diff` prints the session's whole patch.
* **Commands are recorded.** The runner stores the command as typed, the argv that actually ran,
  the directory, the exit code, the duration and the output - and refusals too, because "this was
  attempted and denied" is evidence.
* **Sessions are reproducible.** A run can be replayed by id (`code rerun`), and the session's
  task is an ordinary task, so `tasks reproduce` works on it unchanged.

Session roots
-------------
A session opens on a directory *inside the tool roots*. That is not a formality: the tools resolve
every path against those roots, so the session's boundary is the same boundary as everything else,
and a path that escapes it is refused by the tool runtime rather than by a second implementation
of the same rule here.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.coding import CodeChange, CodeRun, CodeSession
from archx_agent.managers.tools import ToolContext

#: The file a session reads its named checks from. Strict data, in the project, reviewable.
CHECKS_FILE = "archx.checks.json"
_CHECK_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


@dataclass
class Check:
    """One named command a project says is worth running."""

    name: str
    command: str
    timeout: int | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "timeout": self.timeout,
            "description": self.description,
        }


class CodingWorkspace:
    """Sessions, edits and runs. Constructed per access from the workspace, like the others."""

    def __init__(self, ws) -> None:
        self.ws = ws

    # -- plumbing ---------------------------------------------------------
    @property
    def manager(self):
        return self.ws.coding

    def _context(self, session: CodeSession, purpose: str) -> ToolContext:
        return ToolContext(
            task_id=session.task_id,
            project_id=session.project_id,
            purpose=purpose,
        )

    def _execute(self, name: str, arguments: Mapping[str, Any], context: ToolContext):
        """Run one tool. A refusal becomes a domain error naming the approval, not a half-write."""
        run = self.ws.tools.execute(name, arguments, context=context, requester="coding")
        if run.status == "denied":
            approval = getattr(run, "approval_id", None)
            reason = run.error or f"{name} was refused"
            if approval:
                raise ApprovalRequiredError(
                    f"{name} needs approval: approve {approval} or grant the capability",
                    approval_id=approval,
                )
            raise PermissionDeniedError(reason)
        if run.status == "failed":
            raise ToolError(run.error or f"{name} failed")
        return run

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

    # -- sessions ---------------------------------------------------------
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
                "code", "code.session", status="ok", task_id=task.id,
                payload={"session_id": session.id, "linked": True},
            )
            self.ws.tasks.log(session.task_id, "code", detail=f"session {session.id} on {session_root}")
        return session

    def sessions(self, *, status: str | None = None, limit: int = 50) -> list[CodeSession]:
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
                self.ws.tasks.complete(session.task_id, summary=note or f"closed {session_id}")
            except Exception:  # noqa: BLE001 - a closed session must not hinge on the task
                pass
        return closed

    # -- reads ------------------------------------------------------------
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
        run = self._execute("fs.read", arguments, self._context(session, f"code read {path}"))
        result = dict(run.result or {})
        result["session_id"] = session_id
        result["display_path"] = self._relative(session, absolute)
        return result

    def list_dir(self, session_id: str, path: str = ".", *, limit: int = 200) -> dict[str, Any]:
        session = self._session(session_id)
        absolute = self._resolve(session, path) if path not in {".", ""} else session.root
        run = self._execute(
            "fs.list", {"path": absolute, "limit": int(limit)},
            self._context(session, f"code list {path}"),
        )
        return dict(run.result or {})

    # -- edits ------------------------------------------------------------
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
            self._relative(session, absolute), before.text, after_text,
            before_available=before.available,
        )
        return self._record_change(
            session, path=absolute, action=action, diff=diff, added=added, removed=removed,
            before_sha=before.sha, after_sha=str(result.get("sha256") or ""),
            tool_run_id=run.id, note=note, unavailable=before.reason,
        )

    def delete(self, session_id: str, path: str, *, note: str | None = None) -> CodeChange:
        session = self._session(session_id)
        absolute = self._resolve(session, path)
        before = self._before(session, absolute)
        run = self._execute(
            "fs.delete", {"path": absolute}, self._context(session, f"code delete {path}"),
        )
        diff, added, removed = _unified_diff(
            self._relative(session, absolute), before.text, "",
            before_available=before.available,
        )
        return self._record_change(
            session, path=absolute, action="delete", diff=diff, added=added, removed=removed,
            before_sha=before.sha, after_sha=None, tool_run_id=run.id, note=note,
            unavailable=before.reason,
        )

    @dataclass
    class _Before:
        text: str
        sha: str | None
        available: bool
        reason: str = ""

    def _before(self, session: CodeSession, absolute: str) -> "_Before":
        """The current text, read through the tool layer so the diff is over what a grant allows.

        If reading is not allowed this does *not* raise: it asks the permission centre whether a
        read would be permitted, without requesting an approval. Editing a file you may write but
        not read is legitimate (a generated config), and turning one `code write` into two pending
        approvals would be noise. The change row then says the diff shows only the new content.
        """
        if not Path(absolute).exists():
            return CodingWorkspace._Before(text="", sha=None, available=True)
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
            return CodingWorkspace._Before(
                text="", sha=None, available=False,
                reason="fs.read is not granted, so this diff shows the new content only",
            )
        try:
            run = self._execute(
                "fs.read", {"path": absolute}, self._context(session, "code read before edit"),
            )
        except (ToolError, PermissionDeniedError):
            # Cannot read it (binary, too large): the write still happens if it is allowed, but
            # there is no honest diff to show, and the row says so.
            return CodingWorkspace._Before(
                text="", sha=None, available=False,
                reason="the previous content could not be read as text",
            )
        result = dict(run.result or {})
        available = not bool(result.get("truncated"))
        return CodingWorkspace._Before(
            text=str(result.get("content") or ""),
            sha=str(result.get("sha256") or "") or None,
            available=available,
            reason="" if available else "the previous content was larger than tools.max_file_bytes",
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
                session, self._patch_file(session, relative, diff), kind="diff",
                name=f"{relative}.diff",
            )
            try:
                self.ws.tasks.log(
                    session.task_id, "edit",
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

    def _attach(self, session: CodeSession, path: Path, *, kind: str, name: str) -> str | None:
        try:
            artifact = self.ws.tasks.attach_artifact(session.task_id, str(path), kind=kind, name=name)
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
            artifact_id = self._attach(session, target, kind="patch", name="session.patch")
        return {
            "session_id": session_id,
            "patch": body,
            "files": sorted({change.path for change in changes}),
            "added": sum(change.added for change in changes),
            "removed": sum(change.removed for change in changes),
            "artifact_id": artifact_id,
        }

    # -- the runner -------------------------------------------------------
    def run(
        self,
        session_id: str,
        command: str,
        *,
        timeout: int | None = None,
        check_name: str | None = None,
        cwd: str | None = None,
        replayed_from: str | None = None,
    ) -> CodeRun:
        """Run a command in the session root, recording the attempt whatever happens."""
        session = self._session(session_id)
        text = (command or "").strip()
        if not text:
            raise ValidationError("a command is required")
        workdir = self._resolve(session, cwd) if cwd else session.root
        when = iso_now()
        arguments: dict[str, Any] = {"command": text, "cwd": workdir}
        if timeout:
            arguments["timeout"] = int(timeout)
        context = self._context(session, f"code run {text[:80]}")
        try:
            run = self.ws.tools.execute("shell.run", arguments, context=context, requester="coding")
        except PermissionDeniedError as exc:
            # The tool layer records the refusal on its own ledger and raises; the coding ledger
            # records it too, so "what did I try to run here" is answerable from either side.
            self.manager.record_run(
                session.id,
                command=text,
                cwd=self._relative(session, workdir) or ".",
                status="refused",
                check_name=check_name,
                argv=[],
                tool_run_id=getattr(getattr(exc, "run", None), "id", None),
                stderr=getattr(exc, "message", None) or str(exc),
                replayed_from=replayed_from,
            )
            raise
        result = dict(run.result or {})

        exit_code = result.get("exit_code")
        timed_out = bool(result.get("timed_out"))
        if timed_out:
            status = "timeout"
        elif run.status == "failed" or exit_code not in (0, None):
            status = "failed"
        else:
            status = "passed"

        artifact_id = None
        if session.task_id and (result.get("stdout") or result.get("stderr")):
            artifact_id = self._log_artifact(session, run, result, text)
        recorded = self.manager.record_run(
            session.id,
            command=text,
            cwd=self._relative(session, workdir) or ".",
            status=status,
            check_name=check_name,
            argv=[str(part) for part in (result.get("argv") or [])],
            exit_code=exit_code if isinstance(exit_code, int) else None,
            duration_ms=float(result.get("duration_ms") or run.duration_ms or 0.0),
            timeout_seconds=int(result.get("timeout_seconds") or timeout or 0) or None,
            timed_out=timed_out,
            stdout=str(result.get("stdout") or "")[:20000],
            stderr=str(result.get("stderr") or "")[:20000],
            artifact_id=artifact_id,
            tool_run_id=run.id,
            replayed_from=replayed_from,
        )
        if session.task_id:
            try:
                self.ws.tasks.log(
                    session.task_id, "run",
                    detail=f"{status}: {text[:120]} (exit {recorded.exit_code}, "
                           f"{int(recorded.duration_ms or 0)} ms)",
                )
            except Exception:  # noqa: BLE001
                pass
            if status == "failed":
                try:
                    self.ws.tasks.add_question(
                        session.task_id, f"{text[:80]} exited {recorded.exit_code}; fix or accept it?"
                    )
                except Exception:  # noqa: BLE001 - a question is never worth failing a run
                    pass
        return recorded

    def _log_artifact(self, session: CodeSession, run, result: dict[str, Any], command: str) -> str | None:
        folder = self._workspace_dir(session)
        stamp = iso_now().replace(":", "").replace("-", "")
        target = folder / f"run-{stamp}-{run.id[-6:]}.log"
        body = [f"$ {command}", f"cwd {result.get('cwd')}"]
        if result.get("stdout"):
            body += ["", "--- stdout ---", str(result["stdout"])]
        if result.get("stderr"):
            body += ["", "--- stderr ---", str(result["stderr"])]
        body.append("")
        body.append(f"exit {result.get('exit_code')} in {result.get('duration_ms')} ms")
        target.write_text("\n".join(body), encoding="utf-8")
        return self._attach(session, target, kind="log", name=target.name)

    def rerun(self, run_id: str) -> CodeRun:
        """Run the same command again, in the same session, as a new row."""
        previous = self.manager.get_run(run_id)
        return self.run(
            previous.session_id,
            previous.command,
            timeout=_timeout_of(previous),
            check_name=previous.check_name,
            replayed_from=previous.id,
        )

    # -- named checks -----------------------------------------------------
    def checks(self, session_id: str) -> dict[str, Any]:
        """What this project says is worth running, read from its own manifest."""
        session = self._session(session_id, require_open=False)
        absolute = self._resolve(session, CHECKS_FILE)
        if not Path(absolute).exists():
            return {
                "session_id": session_id,
                "checks": [],
                "source": None,
                "reason": (
                    f"no {CHECKS_FILE} in the session root; a check is a name and a command, "
                    f'for example {{"checks": [{{"name": "test", "command": "python -m pytest -q"}}]}}'
                ),
            }
        run = self._execute(
            "fs.read", {"path": absolute}, self._context(session, "code checks"),
        )
        raw = str((run.result or {}).get("content") or "")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"{CHECKS_FILE} is not valid JSON: {exc}") from exc
        parsed = _parse_checks(data)
        return {
            "session_id": session_id,
            "checks": [check.to_dict() for check in parsed],
            "source": CHECKS_FILE,
            "reason": f"{len(parsed)} check(s) declared in {CHECKS_FILE}",
        }

    def test(self, session_id: str, name: str = "test") -> CodeRun:
        """Run one named check. The default name is `test`, because that is what it usually is."""
        parsed = {check.name: check for check in self._manifest(session_id)}
        if name not in parsed:
            known = ", ".join(sorted(parsed)) or "none"
            raise NotFoundError(
                f"no check named {name!r} in {CHECKS_FILE} (declared: {known})"
            )
        check = parsed[name]
        return self.run(
            session_id, check.command, timeout=check.timeout, check_name=check.name
        )

    def _manifest(self, session_id: str) -> list[Check]:
        session = self._session(session_id, require_open=False)
        absolute = self._resolve(session, CHECKS_FILE)
        if not Path(absolute).exists():
            return []
        run = self._execute("fs.read", {"path": absolute}, self._context(session, "code checks"))
        try:
            data = json.loads(str((run.result or {}).get("content") or ""))
        except json.JSONDecodeError as exc:
            raise ValidationError(f"{CHECKS_FILE} is not valid JSON: {exc}") from exc
        return _parse_checks(data)

    def runs(self, session_id: str, *, limit: int = 50) -> list[CodeRun]:
        self._session(session_id, require_open=False)
        return self.manager.runs(session_id, limit=limit)

    def run_by_id(self, run_id: str) -> CodeRun:
        return self.manager.get_run(run_id)

    def stats(self) -> dict[str, Any]:
        return self.manager.stats()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _unified_diff(
    relative: str, before: str, after: str, *, before_available: bool = True
) -> tuple[str, int, int]:
    """A patch a human can read, and the line counts that go with it."""
    if not before_available:
        return "", 0, 0
    old = before.splitlines(keepends=True)
    new = after.splitlines(keepends=True)
    # A file that did not end in a newline would otherwise produce a last line without one,
    # which most patch tools accept but which reads as a mistake in a diff.
    if old and not old[-1].endswith("\n"):
        old[-1] += "\n"
    if new and not new[-1].endswith("\n"):
        new[-1] += "\n"
    lines = list(
        difflib.unified_diff(old, new, fromfile=f"a/{relative}", tofile=f"b/{relative}", n=3)
    )
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    return "".join(lines), added, removed


def _parse_checks(data: Any) -> list[Check]:
    """Strict: an unknown field is a typo, and a typo in a test command is a wasted afternoon."""
    if not isinstance(data, dict):
        raise ValidationError(f"{CHECKS_FILE} must be an object with a \"checks\" list")
    unknown = sorted(set(data) - {"checks", "version"})
    if unknown:
        raise ValidationError(f"{CHECKS_FILE} has unknown field(s): {', '.join(unknown)}")
    entries = data.get("checks")
    if not isinstance(entries, list):
        raise ValidationError(f"{CHECKS_FILE} needs a \"checks\" list")
    checks: list[Check] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValidationError(f"check #{index + 1} must be an object")
        extra = sorted(set(entry) - {"name", "command", "timeout", "description"})
        if extra:
            raise ValidationError(f"check #{index + 1} has unknown field(s): {', '.join(extra)}")
        name = str(entry.get("name") or "").strip()
        command = str(entry.get("command") or "").strip()
        if not _CHECK_NAME.match(name):
            raise ValidationError(
                f"check #{index + 1} needs a name of a-z, 0-9, '-' or '_' (got {name!r})"
            )
        if name in seen:
            raise ValidationError(f"two checks are named {name!r}")
        seen.add(name)
        if not command:
            raise ValidationError(f"check {name!r} has no command")
        timeout = entry.get("timeout")
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            raise ValidationError(f"check {name!r} has a timeout that is not a positive integer")
        checks.append(
            Check(
                name=name,
                command=command,
                timeout=timeout,
                description=str(entry.get("description") or ""),
            )
        )
    return checks


def _timeout_of(run: CodeRun) -> int | None:
    """The timeout a run used, so a replay is subject to the same bound."""
    return run.timeout_seconds
