"""M31 - the coding workspace: editing, running and testing code under the permission centre.

These tests are written from the outside: a workspace on a temporary home, a session on a
temporary project, and then the four things a coding workspace must actually do - read, write,
run, test - checked against what happened on disk, in the rows and in the task.

The permission tests are the point of the milestone, so they come first in spirit even though they
are second in the file: a session that could write without a grant would make the whole feature a
hole in the model rather than a use of it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from archx_agent.managers.schema import SCHEMA_VERSION


@pytest.fixture()
def project(tmp_path):
    """A directory that is inside the tool roots, so a session may open on it."""
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "hello.py").write_text("def greet(name):\n    return f'hi {name}'\n")
    return folder


@pytest.fixture()
def ws(tmp_path, project):
    with open_workspace(
        home=str(tmp_path / "home"),
        overrides={"tools.roots": [str(project)]},
        env={"ARCHX_ALLOW_SIMULATED": "1"},
    ) as workspace:
        yield workspace


@pytest.fixture()
def granted(ws):
    """A workspace with one open session, and every capability the workspace uses granted."""
    session = ws.code.open(title="demo")
    for capability in ("fs.read", "fs.write", "fs.delete", "shell.run"):
        ws.permissions.grant(capability, subject="*", duration="persistent", confirm=True)
    return ws, session.id


def grant(ws, capability, **kwargs):
    options = {"subject": "*", "duration": "persistent", "confirm": True}
    options.update(kwargs)
    return ws.permissions.grant(capability, **options)


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------
class TestTheSchema:
    def test_the_coding_tables_are_part_of_the_schema(self, ws):
        assert SCHEMA_VERSION >= 21
        for table in ("code_sessions", "code_changes", "code_runs"):
            assert ws.store.scalar(
                f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{table}'"
            ) == 1, table

    def test_a_fresh_workspace_has_no_sessions(self, ws):
        assert ws.coding.stats() == {
            "sessions": 0, "open": 0, "changes": 0, "runs": 0, "failed_runs": 0,
        }


# --------------------------------------------------------------------------
# opening
# --------------------------------------------------------------------------
class TestOpeningASession:
    def test_a_session_binds_a_directory_and_a_task(self, ws, project):
        session = ws.code.open(title="fix the greeting")
        assert session.status == "open"
        assert Path(session.root) == project.resolve()
        assert session.task_id, "a session without a task has nowhere to record anything"
        task = ws.tasks.get(session.task_id)
        assert task.type == "coding"
        assert task.title == "code: fix the greeting"
        assert task.status == "running"

    def test_the_title_defaults_to_the_directory_name(self, ws):
        session = ws.code.open()
        assert session.title == "project"

    def test_opening_outside_the_tool_roots_is_refused(self, ws, tmp_path):
        with pytest.raises(Exception) as caught:
            ws.code.open(root=str(tmp_path / "elsewhere"))
        assert "outside" in str(caught.value).lower() or "no such directory" in str(caught.value).lower()

    def test_a_directory_that_does_not_exist_is_refused_with_its_name(self, ws, project):
        with pytest.raises(NotFoundError) as caught:
            ws.code.open(root=str(project / "nope"))
        assert "no such directory" in str(caught.value)
        assert "create it first" in str(caught.value)

    def test_sessions_are_listed_newest_first_and_by_status(self, ws):
        first = ws.code.open(title="one")
        second = ws.code.open(title="two")
        ws.code.close(first.id)
        assert [s.id for s in ws.code.sessions()][:2] == [second.id, first.id]
        assert [s.id for s in ws.code.sessions(status="open")] == [second.id]
        assert [s.id for s in ws.code.sessions(status="closed")] == [first.id]


# --------------------------------------------------------------------------
# the permission centre
# --------------------------------------------------------------------------
class TestNothingHappensWithoutAGrant:
    def test_reading_without_a_grant_is_refused_and_names_the_approval(self, ws):
        session = ws.code.open()
        with pytest.raises(ApprovalRequiredError) as caught:
            ws.code.read(session.id, "hello.py")
        assert caught.value.approval_id.startswith("ap_")
        assert "fs.read" in str(caught.value)

    def test_writing_without_a_grant_does_not_touch_the_file(self, ws, project):
        session = ws.code.open()
        before = (project / "hello.py").read_bytes()
        with pytest.raises(ApprovalRequiredError):
            ws.code.write(session.id, "hello.py", "print('replaced')\n")
        assert (project / "hello.py").read_bytes() == before
        assert ws.coding.changes(session.id) == []

    def test_running_without_a_grant_does_not_start_a_process(self, ws, project):
        session = ws.code.open()
        marker = project / "ran.txt"
        with pytest.raises(ApprovalRequiredError):
            ws.code.run(session.id, f"{sys.executable} -c \"open('ran.txt','w').write('x')\"")
        assert not marker.exists()

    def test_the_refusal_is_recorded_as_a_run_row(self, ws):
        """A denied command is evidence, and evidence is the whole point of the ledger."""
        session = ws.code.open()
        with pytest.raises(PermissionDeniedError):
            ws.code.run(session.id, "echo hi")
        runs = ws.coding.runs(session.id)
        assert len(runs) == 1
        assert runs[0].status == "refused"
        assert "shell.run" in runs[0].stderr

    def test_approving_the_request_then_running_succeeds(self, ws):
        session = ws.code.open()
        with pytest.raises(ApprovalRequiredError) as caught:
            ws.code.run(session.id, "echo approved")
        approval_id = caught.value.approval_id
        ws.permissions.approve(approval_id, reason="test")
        run = ws.code.run(session.id, "echo approved")
        assert run.status == "passed"
        assert "approved" in run.stdout

    def test_writing_without_a_read_grant_asks_once_and_says_the_diff_is_partial(self, ws, project):
        """One edit must not become two approval requests, and the row must not pretend."""
        session = ws.code.open()
        grant(ws, "fs.write", duration="once")
        change = ws.code.write(session.id, "hello.py", "print('new')\n")
        assert change.action == "modify"
        assert change.added == 0 and change.removed == 0
        assert "fs.read is not granted" in change.diff
        pending = ws.permissions.pending()
        assert [a.capability for a in pending] == [], [a.to_dict() for a in pending]
        assert "print('new')" in (project / "hello.py").read_text()

    def test_a_once_grant_is_spent_by_the_first_write(self, ws, project):
        session = ws.code.open()
        grant(ws, "fs.write", duration="once")
        ws.code.write(session.id, "one.txt", "first\n")
        with pytest.raises(ApprovalRequiredError):
            ws.code.write(session.id, "two.txt", "second\n")
        assert (project / "one.txt").exists()
        assert not (project / "two.txt").exists()


# --------------------------------------------------------------------------
# editing
# --------------------------------------------------------------------------
class TestEditing:
    def test_a_write_without_a_read_grant_asks_for_one_approval_not_two(self, ws, project):
        """The diff is worth having, but not at the price of a second approval request."""
        session = ws.code.open()
        with pytest.raises(ApprovalRequiredError):
            ws.code.write(session.id, "hello.py", "print('hi')\n")
        asked = {row.capability for row in ws.permissions.pending()}
        assert asked == {"fs.write"}, asked
        assert (project / "hello.py").read_text().startswith("def greet")

    def test_a_write_allowed_without_a_read_says_the_diff_is_partial(self, ws, project):
        session = ws.code.open()
        ws.permissions.grant("fs.write", subject="*", duration="persistent", confirm=True)
        change = ws.code.write(session.id, "hello.py", "print('hi')\n")
        assert change.action == "modify"
        assert "fs.read is not granted" in change.diff
        assert not ws.permissions.pending()
        assert (project / "hello.py").read_text() == "print('hi')\n"

    def test_a_new_file_is_a_create_with_a_patch(self, granted):
        ws, sid = granted
        change = ws.code.write(sid, "new.py", "print('hello')\n")
        assert change.action == "create"
        assert change.after_sha
        assert change.before_sha is None
        assert change.added == 1 and change.removed == 0
        assert change.diff.startswith("--- a/new.py")
        assert "+print('hello')" in change.diff

    def test_modifying_a_file_shows_the_line_that_changed(self, granted, project):
        ws, sid = granted
        change = ws.code.write(
            sid, "hello.py",
            "def greet(name):\n    return f'hello {name}'\n",
        )
        assert change.action == "modify"
        assert change.added == 1 and change.removed == 1
        assert "-    return f'hi {name}'" in change.diff
        assert "+    return f'hello {name}'" in change.diff
        assert "hello" in (project / "hello.py").read_text()

    def test_the_edit_is_attached_to_the_task_as_an_artifact(self, granted):
        ws, sid = granted
        change = ws.code.write(sid, "hello.py", "x = 1\n")
        assert change.artifact_id
        artifacts = ws.tasks.artifacts(ws.code.session(sid).task_id)
        assert any(a.kind == "diff" and a.name == "hello.py.diff" for a in artifacts)
        stored = [a for a in artifacts if a.id == change.artifact_id][0]
        assert "+x = 1" in Path(stored.path).read_text()

    def test_deleting_records_a_removal_diff(self, granted, project):
        ws, sid = granted
        change = ws.code.delete(sid, "hello.py")
        assert change.action == "delete"
        assert change.removed == 2
        assert not (project / "hello.py").exists()
        assert change.after_sha is None

    def test_an_edit_outside_the_session_root_is_refused(self, granted, tmp_path):
        ws, sid = granted
        with pytest.raises(ValidationError) as caught:
            ws.code.write(sid, "../escape.py", "nope\n")
        assert "outside the session root" in str(caught.value)
        assert not (tmp_path / "escape.py").exists()

    def test_content_that_is_not_text_is_refused(self, granted):
        ws, sid = granted
        with pytest.raises(ValidationError):
            ws.code.write(sid, "x.py", {"not": "text"})

    def test_the_whole_session_is_one_patch(self, granted):
        ws, sid = granted
        ws.code.write(sid, "a.py", "one\n")
        ws.code.write(sid, "b.py", "two\n")
        ws.code.write(sid, "a.py", "one\ntwo\n")
        patch = ws.code.diff(sid)
        assert patch["files"] == ["a.py", "b.py"]
        assert patch["added"] == 3
        assert "--- a/a.py" in patch["patch"] and "--- a/b.py" in patch["patch"]
        assert patch["artifact_id"], "the session patch should be attachable"

    def test_a_closed_session_refuses_edits(self, granted):
        ws, sid = granted
        ws.code.close(sid, note="done")
        with pytest.raises(ValidationError) as caught:
            ws.code.write(sid, "late.py", "no\n")
        assert "closed" in str(caught.value)


# --------------------------------------------------------------------------
# the runner
# --------------------------------------------------------------------------
class TestTheRunner:
    def test_a_successful_command_records_its_exit_and_output(self, granted):
        ws, sid = granted
        run = ws.code.run(sid, "echo hello there")
        assert run.status == "passed"
        assert run.exit_code == 0
        assert run.stdout.strip() == "hello there"
        assert run.argv == ["echo", "hello", "there"]
        assert run.duration_ms >= 0
        assert run.cwd == "."

    def test_a_failing_command_is_recorded_as_failed_and_asks_a_question(self, granted):
        ws, sid = granted
        run = ws.code.run(sid, f"{sys.executable} -c \"import sys; sys.exit(3)\"")
        assert run.status == "failed"
        assert run.exit_code == 3
        task = ws.tasks.get(ws.code.session(sid).task_id)
        assert task.status == "running"
        assert any("exited 3" in q for q in task.unresolved)

    def test_a_timeout_is_a_timeout_not_a_failure(self, granted):
        ws, sid = granted
        run = ws.code.run(
            sid, f"{sys.executable} -c \"import time; time.sleep(10)\"", timeout=1
        )
        assert run.status == "timeout"
        assert run.timed_out is True
        assert run.timeout_seconds == 1

    def test_the_command_runs_in_the_session_root(self, granted, project):
        ws, sid = granted
        (project / "sub").mkdir()
        run = ws.code.run(sid, "pwd", cwd="sub")
        assert run.cwd == "sub"
        assert str(project.resolve() / "sub") in run.stdout

    def test_the_run_is_a_tool_run_too(self, granted, ws=None):
        ws, sid = granted
        run = ws.code.run(sid, "echo recorded")
        assert run.tool_run_id
        tool_run = ws.tools.get_run(run.tool_run_id)
        assert tool_run["tool_name"] == "shell.run"
        assert tool_run["status"] == "succeeded"

    def test_output_is_kept_as_an_artifact(self, granted):
        ws, sid = granted
        run = ws.code.run(sid, "echo kept")
        assert run.artifact_id
        artifacts = ws.tasks.artifacts(ws.code.session(sid).task_id)
        log = [a for a in artifacts if a.id == run.artifact_id][0]
        assert "kept" in Path(log.path).read_text()

    def test_a_command_that_cannot_start_is_refused_cleanly(self, granted):
        ws, sid = granted
        with pytest.raises(Exception) as caught:
            ws.code.run(sid, "definitely-not-a-real-program-xyz")
        assert "not found" in str(caught.value).lower()

    def test_a_command_cannot_reach_outside_the_roots(self, granted, project):
        """The session root is inside the tool roots; `cwd` cannot climb out of either."""
        ws, sid = granted
        with pytest.raises(ValidationError):
            ws.code.run(sid, "pwd", cwd="../..")

    def test_a_dry_run_of_the_runner_is_not_a_thing(self, granted):
        """There is no preview of a command; pretending otherwise would be a lie about a process."""
        ws, sid = granted
        with pytest.raises(Exception):
            ws.tools.execute("shell.run", {"command": "echo x"}, dry_run=True)

    def test_a_run_can_be_replayed_and_says_where_it_came_from(self, granted):
        ws, sid = granted
        first = ws.code.run(sid, "echo again")
        again = ws.code.rerun(first.id)
        assert again.command == first.command
        assert again.replayed_from == first.id
        assert again.status == "passed"
        assert len(ws.coding.runs(sid)) == 2


# --------------------------------------------------------------------------
# named checks
# --------------------------------------------------------------------------
class TestNamedChecks:
    def _manifest(self, project, checks):
        (project / "archx.checks.json").write_text(json.dumps({"checks": checks}))

    def test_without_a_manifest_the_answer_says_what_one_looks_like(self, granted):
        ws, sid = granted
        listing = ws.code.checks(sid)
        assert listing["checks"] == []
        assert "archx.checks.json" in listing["reason"]
        assert '"name": "test"' in listing["reason"]

    def test_the_manifest_declares_the_checks(self, granted, project):
        ws, sid = granted
        self._manifest(project, [
            {"name": "test", "command": "python -m pytest -q", "timeout": 30},
            {"name": "lint", "command": "python -m compileall .", "description": "syntax"},
        ])
        listing = ws.code.checks(sid)
        assert [c["name"] for c in listing["checks"]] == ["test", "lint"]
        assert listing["checks"][0]["timeout"] == 30

    def test_a_check_runs_and_is_recorded_under_its_name(self, granted, project):
        ws, sid = granted
        self._manifest(project, [{"name": "greet", "command": "echo checked"}])
        run = ws.code.test(sid, "greet")
        assert run.status == "passed"
        assert run.check_name == "greet"
        assert run.stdout.strip() == "checked"
        assert ws.coding.last_run(sid, "greet").id == run.id

    def test_an_unknown_check_names_the_ones_that_exist(self, granted, project):
        ws, sid = granted
        self._manifest(project, [{"name": "lint", "command": "echo x"}])
        with pytest.raises(NotFoundError) as caught:
            ws.code.test(sid, "test")
        assert "lint" in str(caught.value)

    @pytest.mark.parametrize(
        "payload,message",
        [
            ({"checks": "nope"}, "checks"),
            ({"checks": [{"name": "Test", "command": "x"}]}, "name"),
            ({"checks": [{"name": "a", "command": ""}]}, "no command"),
            ({"checks": [{"name": "a", "command": "x"}, {"name": "a", "command": "y"}]}, "two checks"),
            ({"checks": [{"name": "a", "command": "x", "extra": 1}]}, "unknown field"),
            ({"checks": [{"name": "a", "command": "x", "timeout": 0}]}, "timeout"),
            ({"checks": [], "surprise": True}, "unknown field"),
        ],
    )
    def test_the_manifest_is_strict_data(self, granted, project, payload, message):
        ws, sid = granted
        (project / "archx.checks.json").write_text(json.dumps(payload))
        with pytest.raises(ValidationError) as caught:
            ws.code.checks(sid)
        assert message in str(caught.value)

    def test_a_manifest_that_is_not_json_says_so(self, granted, project):
        ws, sid = granted
        (project / "archx.checks.json").write_text("{oops")
        with pytest.raises(ValidationError) as caught:
            ws.code.test(sid, "test")
        assert "not valid JSON" in str(caught.value)


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------
class TestTheRecord:
    def test_show_counts_what_happened(self, granted):
        ws, sid = granted
        ws.code.write(sid, "a.py", "one\n")
        ws.code.write(sid, "a.py", "one\ntwo\n")
        ws.code.run(sid, "echo ok")
        shown = ws.code.show(sid)
        assert shown["stats"] == {"changes": 2, "added": 2, "removed": 0, "runs": 1, "failed": 0}
        assert shown["task"]["id"] == ws.code.session(sid).task_id

    def test_the_task_timeline_reads_like_a_session(self, granted):
        ws, sid = granted
        ws.code.write(sid, "a.py", "one\n")
        ws.code.run(sid, "echo ok")
        session = ws.code.session(sid)
        kinds = [entry["kind"] for entry in ws.tasks.timeline(session.task_id)]
        assert "edit" in kinds and "run" in kinds and "created" in kinds

    def test_closing_completes_the_task(self, granted):
        ws, sid = granted
        session = ws.code.close(sid, note="shipped")
        assert session.status == "closed" and session.closed_at
        task = ws.tasks.get(session.task_id)
        assert task.status == "completed"
        details = [entry.get("detail") or "" for entry in ws.tasks.timeline(task.id)]
        assert any("shipped" in detail for detail in details)

    def test_closing_twice_is_refused_in_words(self, granted):
        ws, sid = granted
        ws.code.close(sid)
        with pytest.raises(ValidationError) as caught:
            ws.code.close(sid)
        assert "already closed" in str(caught.value)

    def test_a_closed_session_is_still_readable(self, granted):
        ws, sid = granted
        ws.code.write(sid, "a.py", "one\n")
        ws.code.close(sid)
        shown = ws.code.show(sid)
        assert shown["session"]["status"] == "closed"
        assert shown["changes"][0]["path"] == "a.py"

    def test_a_session_survives_the_process_that_opened_it(self, tmp_path, project):
        """A coding session is used across many commands, so its task must not be swept as
        "a running task whose process died" the moment the first command exits."""
        home = str(tmp_path / "home")
        overrides = {"tools.roots": [str(project)]}
        with open_workspace(home=home, overrides=overrides) as first:
            session = first.code.open(title="long lived")
        with open_workspace(home=home, overrides=overrides) as second:
            task = second.tasks.get(session.task_id)
            assert task.status == "running", task.status
            assert task.metadata.get("manual") is True
            # and closing it later still completes it
            second.code.close(session.id, note="done after a restart")
            assert second.tasks.get(session.task_id).status == "completed"

    def test_an_unknown_session_is_a_404_not_a_crash(self, ws):
        with pytest.raises(NotFoundError):
            ws.code.show("cs_nope")

    def test_a_reproduction_can_be_captured_for_a_session_task(self, granted):
        """A coding task is an ordinary task, so the reproducer already understands it."""
        ws, sid = granted
        ws.code.write(sid, "a.py", "one\n")
        ws.code.run(sid, "echo reproducible")
        task_id = ws.code.session(sid).task_id
        assessment = ws.reproduction.assess(task_id)
        assert assessment["fidelity"] in {"exact", "partial"}
        commands = "\n".join(assessment["commands"])
        # the write and the command are both replayable from the task alone
        assert "tools run fs.write" in commands
        assert "echo reproducible" in commands
        assert f"tasks show {task_id}" in commands


# --------------------------------------------------------------------------
# the GUI is a client of the same service
# --------------------------------------------------------------------------
@pytest.fixture()
def gui(tmp_path, project):
    """The GUI api over a workspace whose tool roots are the project."""
    from archx_agent.interfaces.gui.server import GuiApi

    with open_workspace(
        home=str(tmp_path / "home"),
        overrides={"tools.roots": [str(project)]},
        env={"ARCHX_ALLOW_SIMULATED": "1"},
    ) as workspace:
        yield GuiApi(workspace), workspace


def http(api, method, path, *, body=None):
    """Dispatch one request the way the socket does, without a socket."""
    from archx_agent.interfaces.gui.server import Request, split_target

    parsed_path, query, _token = split_target(path)
    request = Request(
        method=method,
        path=parsed_path,
        query=query,
        headers={"x-archx-token": api.token, "x-archx-request": "gui"},
        body=body,
    )
    response = api.dispatch(request)
    payload = response.payload
    if isinstance(payload, dict) and set(payload) == {"ok", "data"}:
        payload = payload["data"]
    return response.status, payload


class TestTheGuiIsTheSameService:
    def test_a_session_opened_in_the_page_is_one_the_cli_can_list(self, gui):
        api, ws = gui
        status, opened = http(api, "POST", "/api/code/sessions", body={"title": "from the page"})
        assert status == 200
        assert ws.coding.get_session(opened["id"]).title == "from the page"
        status, listing = http(api, "GET", "/api/code/sessions")
        assert status == 200
        assert [s["id"] for s in listing["sessions"]] == [opened["id"]]
        assert listing["roots"] == [str(ws.tools.roots()[0])]

    def test_a_write_from_the_page_is_a_row_and_a_file(self, gui, project):
        api, ws = gui
        _, opened = http(api, "POST", "/api/code/sessions", body={})
        grant(ws, "fs.read")
        grant(ws, "fs.write")
        status, change = http(
            api, "POST", f"/api/code/sessions/{opened['id']}/write",
            body={"path": "made.py", "content": "value = 1\n"},
        )
        assert status == 200
        assert change["action"] == "create"
        assert (project / "made.py").read_text() == "value = 1\n"
        _, shown = http(api, "GET", f"/api/code/sessions/{opened['id']}")
        assert shown["changes"][0]["path"] == "made.py"

    def test_a_refused_write_is_403_with_the_approval_named(self, gui):
        api, ws = gui
        _, opened = http(api, "POST", "/api/code/sessions", body={})
        status, error = http(
            api, "POST", f"/api/code/sessions/{opened['id']}/write",
            body={"path": "x.py", "content": "x\n"},
        )
        assert status == 403
        assert error["error"]["code"] in {"approval_required", "permission_denied"}
        assert "approve" in error["error"]["message"]

    def test_reading_a_file_over_http_returns_its_text(self, gui):
        api, ws = gui
        _, opened = http(api, "POST", "/api/code/sessions", body={})
        grant(ws, "fs.read")
        status, file = http(api, "GET", f"/api/code/sessions/{opened['id']}/file?path=hello.py")
        assert status == 200
        assert "def greet" in file["content"]
        status, listing = http(api, "GET", f"/api/code/sessions/{opened['id']}/tree")
        assert status == 200
        assert "hello.py" in [entry["name"] for entry in listing["entries"]]

    def test_a_run_from_the_page_is_recorded_like_a_cli_run(self, gui):
        api, ws = gui
        _, opened = http(api, "POST", "/api/code/sessions", body={})
        grant(ws, "shell.run")
        status, run = http(
            api, "POST", f"/api/code/sessions/{opened['id']}/run", body={"command": "echo from the page"}
        )
        assert status == 200
        assert run["status"] == "passed"
        assert run["stdout"].strip() == "from the page"
        assert ws.coding.get_run(run["id"]).command == "echo from the page"

    def test_a_failing_command_is_a_200_with_a_failed_row(self, gui):
        """The request succeeded; the command did not. Those are different things."""
        api, ws = gui
        _, opened = http(api, "POST", "/api/code/sessions", body={})
        grant(ws, "shell.run")
        status, run = http(
            api, "POST", f"/api/code/sessions/{opened['id']}/run",
            body={"command": f"{sys.executable} -c \"import sys; sys.exit(4)\""},
        )
        assert status == 200
        assert run["status"] == "failed" and run["exit_code"] == 4

    def test_bad_bodies_are_400s(self, gui):
        api, ws = gui
        _, opened = http(api, "POST", "/api/code/sessions", body={})
        sid = opened["id"]
        for path, body, note in (
            (f"/api/code/sessions/{sid}/write", {"path": "x.py", "content": {"a": 1}}, "content"),
            (f"/api/code/sessions/{sid}/write", {"content": "x"}, "path"),
            (f"/api/code/sessions/{sid}/run", {"command": "echo x", "timeout": "soon"}, "timeout"),
            (f"/api/code/sessions/{sid}/run", {"command": "echo x", "timeout": -1}, "timeout"),
        ):
            status, error = http(api, "POST", path, body=body)
            assert status == 400, (path, body, status)
            assert note in error["error"]["message"]

    def test_an_unknown_check_is_a_404(self, gui):
        api, ws = gui
        _, opened = http(api, "POST", "/api/code/sessions", body={})
        status, error = http(api, "POST", f"/api/code/sessions/{opened['id']}/test", body={"check": "nope"})
        assert status == 404
        assert error["error"]["code"] == "not_found"

    def test_a_closed_session_refuses_later_writes_with_a_400(self, gui, project):
        api, ws = gui
        _, opened = http(api, "POST", "/api/code/sessions", body={})
        grant(ws, "fs.write")
        http(api, "POST", f"/api/code/sessions/{opened['id']}/close", body={"note": "done"})
        status, error = http(
            api, "POST", f"/api/code/sessions/{opened['id']}/write",
            body={"path": "late.py", "content": "no\n"},
        )
        assert status == 400
        assert "closed" in error["error"]["message"]
        assert not (project / "late.py").exists()

    def test_an_unknown_session_is_a_404(self, gui):
        api, _ws = gui
        status, error = http(api, "GET", "/api/code/sessions/cs_nope")
        assert status == 404
        assert error["error"]["code"] == "not_found"

    def test_the_route_table_knows_the_coding_routes(self, gui):
        api, _ws = gui
        shapes = {(route.method, route.pattern.pattern) for route in api.routes()}
        for expected in (
            ("GET", "^/api/code/sessions$"),
            ("POST", "^/api/code/sessions$"),
            ("GET", "^/api/code/sessions/(?P<session_id>[^/]+)$"),
            ("POST", "^/api/code/sessions/(?P<session_id>[^/]+)/run$"),
        ):
            assert expected in shapes

    def test_the_page_offers_the_code_panel(self):
        from archx_agent.interfaces.gui.server import ASSETS

        html = (ASSETS / "index.html").read_text()
        assert 'data-view="code"' in html
        assert 'id="view-code"' in html
        assert 'id="code-file"' not in html, "the editor is built by the script, not declared twice"
        assert 'id="code-open-form"' in html
