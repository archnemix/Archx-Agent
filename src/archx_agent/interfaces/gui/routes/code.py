"""HTTP endpoints for code. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.interfaces.gui.protocol import ApiError, Request, route, _positive_int


class CodeRoutes:
    @route(
        "GET",
        "/api/code/sessions",
        "Coding sessions, with what each one changed and ran.",
    )
    def get_code_sessions(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        status = request.q("status")
        if status not in (None, "", "open", "closed"):
            raise ApiError(400, "validation", "status must be open or closed")
        sessions = self.ws.code.sessions(
            status=status or None, limit=request.q_int("limit", 20)
        )
        return {
            "sessions": [
                {**session.to_dict(), "stats": self._code_stats(session.id)}
                for session in sessions
            ],
            "roots": self.ws.tools.roots(),
            "stats": self.ws.code.stats(),
        }

    def _code_stats(self, session_id: str) -> dict[str, Any]:
        changes = self.ws.coding.changes(session_id)
        runs = self.ws.coding.runs(session_id)
        return {
            "changes": len(changes),
            "added": sum(change.added for change in changes),
            "removed": sum(change.removed for change in changes),
            "runs": len(runs),
            "failed": sum(1 for run in runs if run.status != "passed"),
        }

    @route(
        "POST",
        "/api/code/sessions",
        "Open a session on a directory inside the tool roots.",
    )
    def post_code_session(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        session = self.ws.code.open(
            request.identifier("root"),
            title=request.text("title", required=False),
            note=request.text("note", required=False),
        )
        return {**session.to_dict(), "stats": self._code_stats(session.id)}

    @route(
        "GET", "/api/code/sessions/{session_id}", "One session: edits, runs, the task."
    )
    def get_code_session(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.code.show(unquote(match.group("session_id")))

    @route(
        "POST", "/api/code/sessions/{session_id}/read", "Read a file (needs fs.read)."
    )
    def post_code_read(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        return self.ws.code.read(
            session_id,
            request.text("path", required=True) or "",
            start_line=_positive_int(request, "start_line", 1),
            max_lines=_positive_int(request, "max_lines"),
        )

    @route(
        "GET",
        "/api/code/sessions/{session_id}/file",
        "Read a file with a query string.",
    )
    def get_code_file(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        path = request.q("path") or ""
        if not path:
            raise ApiError(400, "validation", "a path is required")
        return self.ws.code.read(
            session_id, path, max_lines=request.q_int("max_lines", 0, lo=0) or None
        )

    @route(
        "GET",
        "/api/code/sessions/{session_id}/tree",
        "List a directory (needs fs.read).",
    )
    def get_code_tree(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        path = request.q("path") or "."
        return self.ws.code.list_dir(
            session_id, path, limit=request.q_int("limit", 200)
        )

    @route(
        "POST",
        "/api/code/sessions/{session_id}/write",
        "Create or replace a file (needs fs.write).",
    )
    def post_code_write(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        content = request.payload().get("content")
        if not isinstance(content, str):
            raise ApiError(400, "validation", "content must be text")
        change = self.ws.code.write(
            session_id,
            request.text("path", required=True) or "",
            content,
            note=request.text("note", required=False),
        )
        return change.to_dict()

    @route(
        "POST",
        "/api/code/sessions/{session_id}/delete",
        "Delete a file (needs fs.delete).",
    )
    def post_code_delete(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        change = self.ws.code.delete(
            session_id,
            request.text("path", required=True) or "",
            note=request.text("note", required=False),
        )
        return change.to_dict()

    @route(
        "POST",
        "/api/code/sessions/{session_id}/run",
        "Run a command in the session root.",
    )
    def post_code_run(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        command = request.text("command", required=True) or ""
        timeout = request.payload().get("timeout")
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            raise ApiError(400, "validation", "timeout must be a positive integer")
        run = self.ws.code.run(
            session_id,
            command,
            timeout=timeout,
            cwd=request.text("cwd", required=False),
        )
        return run.to_dict()

    @route(
        "POST",
        "/api/code/sessions/{session_id}/test",
        "Run a named check from archx.checks.json.",
    )
    def post_code_test(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session_id = unquote(match.group("session_id"))
        name = request.text("check", required=False) or "test"
        return self.ws.code.test(session_id, name).to_dict()

    @route(
        "GET",
        "/api/code/sessions/{session_id}/checks",
        "The checks this project declares.",
    )
    def get_code_checks(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.code.checks(unquote(match.group("session_id")))

    @route("GET", "/api/code/sessions/{session_id}/diff", "The session's whole patch.")
    def get_code_diff(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.code.diff(
            unquote(match.group("session_id")), attach=request.q_bool("attach", True)
        )

    @route(
        "POST",
        "/api/code/sessions/{session_id}/close",
        "Close a session; the record stays.",
    )
    def post_code_close(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        session = self.ws.code.close(
            unquote(match.group("session_id")),
            note=request.text("note", required=False),
        )
        return session.to_dict()

    @route("POST", "/api/code/runs/{run_id}/rerun", "Run a recorded command again.")
    def post_code_rerun(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.code.rerun(unquote(match.group("run_id"))).to_dict()
