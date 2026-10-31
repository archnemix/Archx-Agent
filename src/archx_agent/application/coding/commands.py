"""Commands operations for coding sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.coding import CodeRun, CodeSession
from archx_agent.application.coding.constants import CHECKS_FILE
from archx_agent.application.coding.records import Check
from archx_agent.application.coding.checks import _parse_checks, _timeout_of


class CodingWorkspaceCommandsMixin:
    """Commands responsibility for CodingWorkspace."""

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
        arguments: dict[str, Any] = {"command": text, "cwd": workdir}
        if timeout:
            arguments["timeout"] = int(timeout)
        context = self._context(session, f"code run {text[:80]}")
        try:
            run = self.ws.tools.execute(
                "shell.run", arguments, context=context, requester="coding"
            )
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
                    session.task_id,
                    "run",
                    detail=f"{status}: {text[:120]} (exit {recorded.exit_code}, "
                    f"{int(recorded.duration_ms or 0)} ms)",
                )
            except Exception:  # noqa: BLE001
                pass
            if status == "failed":
                try:
                    self.ws.tasks.add_question(
                        session.task_id,
                        f"{text[:80]} exited {recorded.exit_code}; fix or accept it?",
                    )
                except Exception:  # noqa: BLE001 - a question is never worth failing a run
                    pass
        return recorded

    def _log_artifact(
        self, session: CodeSession, run, result: dict[str, Any], command: str
    ) -> str | None:
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
            "fs.read",
            {"path": absolute},
            self._context(session, "code checks"),
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
        run = self._execute(
            "fs.read", {"path": absolute}, self._context(session, "code checks")
        )
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
