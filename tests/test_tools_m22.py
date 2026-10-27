"""M22: tool registry + permission centre.

The tests are grouped as the milestone is built: capability/scope rules first,
then approvals, then real tool execution against real files and real processes,
then the integration seams (registries, traces, run records) and the failure
modes (escapes, denylist, timeouts, consumed grants).
"""

from __future__ import annotations

import os
import sys

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PathEscapesRootError,
    PermissionDeniedError,
    ToolError,
    ToolNotFoundError,
    ToolValidationError,
    ValidationError,
)
from archx_agent.managers.permissions import CAPABILITIES, DURATIONS, PermissionManager
from archx_agent.managers.tools import BUILTIN_TOOLS, ToolContext, ToolManager, ToolSpec


@pytest.fixture()
def ws(tmp_path):
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


@pytest.fixture()
def root(ws):
    return ws.tool_roots()[0]


def _grant(ws, capability, *, subject=None, duration="persistent", **kwargs):
    return ws.permissions.grant(
        capability, subject=subject or capability, duration=duration, confirm=True, **kwargs
    )


def _attempt(ws, name, arguments, **kwargs):
    try:
        return ws.tools.execute(name, arguments, **kwargs)
    except Exception as exc:  # noqa: BLE001 - tests assert on the exception
        return exc


# --------------------------------------------------------------------------
# capabilities and grants
# --------------------------------------------------------------------------
class TestCapabilitiesAndGrants:
    def test_every_protected_tool_declares_a_known_capability(self):
        for spec in BUILTIN_TOOLS.values():
            if spec.capability is not None:
                assert spec.capability in CAPABILITIES, spec.name

    def test_unknown_capability_is_rejected_with_the_known_list(self, ws):
        with pytest.raises(ValidationError) as exc:
            ws.permissions.grant("fs.teleport", subject="x", duration="once")
        assert "fs.teleport" in exc.value.message
        assert "fs.read" in exc.value.message

    def test_grant_needs_a_subject(self, ws):
        with pytest.raises(ValidationError, match="subject"):
            ws.permissions.grant("fs.read", subject="  ", duration="once")

    def test_scoped_durations_require_their_context(self, ws):
        with pytest.raises(ValidationError, match="conversation"):
            ws.permissions.grant("fs.read", subject="fs.read", duration="conversation")
        with pytest.raises(ValidationError, match="task"):
            ws.permissions.grant("fs.read", subject="fs.read", duration="task")
        with pytest.raises(ValidationError, match="project"):
            ws.permissions.grant("fs.read", subject="fs.read", duration="project")

    def test_default_duration_is_a_single_use(self, ws):
        grant = ws.permissions.grant("fs.read", subject="fs.read")
        assert grant.scope == "once"
        first = ws.permissions.check("fs.read", subject="fs.read", consume=True)
        assert first.allowed
        second = ws.permissions.check("fs.read", subject="fs.read", consume=True,
                                      request_approval_on_denial=False)
        assert not second.allowed
        assert "not granted" in second.reason

    def test_single_use_grant_counts_its_use_and_is_revoked(self, ws):
        grant = _grant(ws, "fs.read", duration="once")
        ws.permissions.check("fs.read", subject="fs.read", consume=True)
        stored = ws.permissions.get(grant.id).ok_or_raise()
        assert stored.use_count == 1
        assert stored.revoked_by == "system:consumed"
        assert stored.last_used_at

    def test_conversation_grant_does_not_leak_into_another_conversation(self, ws):
        _grant(ws, "fs.read", duration="conversation", conversation_id="conv-a")
        here = ws.permissions.check("fs.read", subject="fs.read", conversation_id="conv-a",
                                    request_approval_on_denial=False)
        elsewhere = ws.permissions.check("fs.read", subject="fs.read", conversation_id="conv-b",
                                         request_approval_on_denial=False)
        assert here.allowed and not elsewhere.allowed

    def test_conversation_grant_does_not_apply_without_a_conversation(self, ws):
        _grant(ws, "fs.read", duration="conversation", conversation_id="conv-a")
        decision = ws.permissions.check("fs.read", subject="fs.read", request_approval_on_denial=False)
        assert not decision.allowed

    def test_task_and_project_grants_are_scope_checked(self, ws):
        _grant(ws, "fs.write", duration="task", task_id="task-1")
        _grant(ws, "fs.write", duration="project", project_id="proj-1", subject="other-tool")
        assert ws.permissions.check("fs.write", subject="fs.write", task_id="task-1",
                                    request_approval_on_denial=False).allowed
        assert not ws.permissions.check("fs.write", subject="fs.write", task_id="task-2",
                                        request_approval_on_denial=False).allowed
        assert ws.permissions.check("fs.write", subject="other-tool", project_id="proj-1",
                                    request_approval_on_denial=False).allowed
        assert not ws.permissions.check("fs.write", subject="other-tool", project_id="proj-2",
                                        request_approval_on_denial=False).allowed

    def test_wildcard_subject_covers_any_tool(self, ws):
        ws.permissions.grant("fs.read", subject="*", duration="once")
        assert ws.permissions.check("fs.read", subject="anything", request_approval_on_denial=False).allowed

    def test_grant_cannot_be_used_for_a_different_capability(self, ws):
        _grant(ws, "fs.read", duration="persistent")
        assert not ws.permissions.check("fs.write", subject="fs.read",
                                        request_approval_on_denial=False).allowed

    def test_denied_capabilities_beats_a_grant(self, ws):
        ws.config.set("permissions.denied_capabilities", ["fs.write"])
        _grant(ws, "fs.write", duration="persistent")
        decision = ws.permissions.check("fs.write", subject="fs.write", request_approval_on_denial=False)
        assert not decision.allowed
        assert "denied_capabilities" in decision.reason

    def test_time_boxed_grant_expires_and_prune_revokes_it(self, ws):
        grant = _grant(ws, "fs.read", duration="persistent", hours=1)
        assert grant.expires_at
        ws.store.execute(
            "UPDATE permission_grants SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00.000Z", grant.id),
        )
        assert not ws.permissions.check("fs.read", subject="fs.read",
                                        request_approval_on_denial=False).allowed
        assert ws.permissions.prune_expired() == 1
        assert ws.permissions.get(grant.id).ok_or_raise().revoked_by == "system:expiry"

    def test_grant_hours_are_bounded_by_config(self, ws):
        ws.config.set("permissions.max_grant_hours", 2)
        with pytest.raises(ValidationError, match="max_grant_hours"):
            _grant(ws, "fs.read", duration="persistent", hours=5)

    def test_persistent_grant_without_confirm_is_refused_not_downgraded(self, ws):
        with pytest.raises(ValidationError, match="--confirm"):
            ws.permissions.grant("fs.read", subject="fs.read", duration="persistent")
        assert ws.permissions.grants() == []

    def test_confirm_keeps_a_persistent_grant(self, ws):
        grant = ws.permissions.grant("fs.read", subject="fs.read", duration="persistent", confirm=True)
        assert grant.scope == "persistent"

    def test_revoke_twice_is_refused(self, ws):
        grant = _grant(ws, "fs.read", duration="persistent")
        ws.permissions.revoke(grant.id, reason="done")
        with pytest.raises(ValidationError, match="already revoked"):
            ws.permissions.revoke(grant.id)

    def test_revoked_grant_no_longer_allows(self, ws):
        grant = _grant(ws, "fs.read", duration="persistent")
        assert ws.permissions.check("fs.read", subject="fs.read",
                                    request_approval_on_denial=False).allowed
        ws.permissions.revoke(grant.id)
        assert not ws.permissions.check("fs.read", subject="fs.read",
                                        request_approval_on_denial=False).allowed

    def test_missing_grant_is_a_not_found_error(self, ws):
        assert isinstance(ws.permissions.get("pg_nope").error, NotFoundError)


# --------------------------------------------------------------------------
# approvals
# --------------------------------------------------------------------------
class TestApprovals:
    def test_ungranted_check_queues_one_request_per_operation(self, ws):
        first = ws.permissions.check("fs.write", subject="fs.write")
        second = ws.permissions.check("fs.write", subject="fs.write")
        assert not first.allowed and not second.allowed
        assert first.approval_id == second.approval_id
        assert len(ws.permissions.pending()) == 1

    def test_approval_grants_exactly_the_requested_capability(self, ws):
        decision = ws.permissions.check("fs.read", subject="fs.read")
        approval, grant = ws.permissions.approve(decision.approval_id)
        assert grant.capability == "fs.read"
        assert grant.subject == "fs.read"
        assert grant.scope == approval.scope
        assert grant.granted_by == f"approval:{approval.id}"
        assert not ws.permissions.check("fs.write", subject="fs.read",
                                        request_approval_on_denial=False).allowed

    def test_approve_twice_is_refused(self, ws):
        decision = ws.permissions.check("fs.read", subject="fs.read")
        ws.permissions.approve(decision.approval_id)
        with pytest.raises(ValidationError, match="already approved"):
            ws.permissions.approve(decision.approval_id)

    def test_approve_has_no_way_to_widen_the_request(self, ws):
        import inspect

        parameters = set(inspect.signature(PermissionManager.approve).parameters)
        assert "capability" not in parameters
        assert "subject" not in parameters
        assert "scope" not in parameters
        assert "duration" not in parameters

    def test_denying_creates_no_grant_and_a_new_request_next_time(self, ws):
        decision = ws.permissions.check("fs.read", subject="fs.read")
        denied = ws.permissions.deny(decision.approval_id, reason="not now")
        assert denied.status == "denied"
        assert ws.permissions.grants(capability="fs.read") == []
        again = ws.permissions.check("fs.read", subject="fs.read")
        assert again.approval_id != decision.approval_id

    def test_pending_approvals_expire(self, ws):
        decision = ws.permissions.check("fs.read", subject="fs.read")
        ws.store.execute(
            "UPDATE approval_requests SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00.000Z", decision.approval_id),
        )
        assert ws.permissions.pending() == []
        assert ws.permissions.get_approval(decision.approval_id).ok_or_raise().status == "expired"

    def test_expired_request_cannot_be_approved(self, ws):
        decision = ws.permissions.check("fs.read", subject="fs.read")
        ws.store.execute(
            "UPDATE approval_requests SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00.000Z", decision.approval_id),
        )
        with pytest.raises(ValidationError, match="expired"):
            ws.permissions.approve(decision.approval_id)
        assert ws.permissions.grants(capability="fs.read") == []

    def test_pending_queue_is_capped(self, ws):
        ws.config.set("permissions.max_pending_approvals", 1)
        ws.permissions.check("fs.read", subject="fs.read")
        second = ws.permissions.check("fs.write", subject="fs.write")
        assert not second.allowed
        assert second.approval_id is None
        assert "max_pending_approvals" in second.reason

    def test_approvals_can_be_disabled(self, ws):
        ws.config.set("permissions.approvals_enabled", False)
        decision = ws.permissions.check("fs.read", subject="fs.read")
        assert not decision.allowed
        assert decision.approval_id is None
        assert ws.permissions.pending() == []

    def test_check_command_does_not_queue_anything(self, ws):
        ws.permissions.check("fs.read", subject="fs.read", request_approval_on_denial=False)
        assert ws.permissions.pending() == []

    def test_approval_for_one_subject_does_not_cover_another(self, ws):
        decision = ws.permissions.check("fs.read", subject="fs.read")
        ws.permissions.approve(decision.approval_id)
        assert not ws.permissions.check("fs.read", subject="fs.list",
                                        request_approval_on_denial=False).allowed


# --------------------------------------------------------------------------
# tool registry
# --------------------------------------------------------------------------
class TestRegistry:
    def test_builtin_tools_are_listed_with_risk_and_capability(self, ws):
        names = {spec.name for spec in ws.tools.specs()}
        assert {"fs.read", "fs.write", "fs.delete", "fs.list", "shell.run"} <= names
        registry = {row["name"]: row for row in ws.tools.registry()}
        assert registry["fs.write"]["risk"] == "medium"
        assert registry["fs.delete"]["supports_dry_run"] is True
        assert registry["archx.info"]["protected"] is False

    def test_unknown_tool_is_a_clear_error(self, ws):
        with pytest.raises(ToolNotFoundError, match="fs.read"):
            ws.tools.execute("fs.teleport", {})

    def test_duplicate_registration_is_refused(self, ws):
        with pytest.raises(ToolValidationError, match="already registered"):
            ws.tools.register_spec(BUILTIN_TOOLS["fs.read"])

    def test_tool_with_unknown_capability_is_refused(self, ws):
        spec = ToolSpec(
            name="http.request", summary="nope", capability="net.telepathy", risk="low", inputs={}
        )
        with pytest.raises(ToolValidationError, match="unknown capability"):
            ws.tools.register_spec(spec)

    def test_unknown_argument_names_the_accepted_ones(self, ws):
        with pytest.raises(ToolValidationError) as exc:
            ws.tools.execute("fs.read", {"pth": "x"})
        assert "pth" in exc.value.message
        assert "path" in exc.value.message

    def test_missing_required_argument_is_named(self, ws):
        with pytest.raises(ToolValidationError, match="requires path"):
            ws.tools.execute("fs.read", {})

    def test_string_integers_are_coerced_and_wrong_types_refused(self, ws):
        _grant(ws, "fs.read")
        # the argument was accepted (the failure is the missing file, not the type)
        with pytest.raises(ToolError, match="no such file"):
            ws.tools.execute("fs.read", {"path": "missing.txt", "max_lines": "3"})
        with pytest.raises(ToolValidationError, match="expects int"):
            ws.tools.execute("fs.read", {"path": "x", "max_lines": "three"})

    def test_dry_run_on_a_tool_without_preview_is_refused(self, ws):
        with pytest.raises(ToolValidationError, match="cannot be dry-run"):
            ws.tools.execute("fs.read", {"path": "x"}, dry_run=True)


# --------------------------------------------------------------------------
# real file operations
# --------------------------------------------------------------------------
class TestFileTools:
    def test_write_is_refused_until_approved_then_creates_the_file(self, ws, root):
        with pytest.raises(ApprovalRequiredError) as exc:
            ws.tools.execute("fs.write", {"path": "notes/hello.txt", "content": "hello world"})
        approval_id = exc.value.approval_id
        assert approval_id and not os.path.exists(os.path.join(root, "notes", "hello.txt"))
        ws.permissions.approve(approval_id)
        run = ws.tools.execute("fs.write", {"path": "notes/hello.txt", "content": "hello world"})
        assert run.status == "succeeded"
        assert open(os.path.join(root, "notes", "hello.txt")).read() == "hello world"

    def test_write_result_reports_the_hash_of_what_was_written(self, ws, root):
        _grant(ws, "fs.write")
        run = ws.tools.execute("fs.write", {"path": "a.txt", "content": "abc"})
        import hashlib

        assert run.result["sha256"] == hashlib.sha256(b"abc").hexdigest()
        assert run.result["existed"] is False

    def test_second_write_reports_the_previous_hash(self, ws):
        _grant(ws, "fs.write")
        ws.tools.execute("fs.write", {"path": "a.txt", "content": "one"})
        run = ws.tools.execute("fs.write", {"path": "a.txt", "content": "two"})
        assert run.result["existed"] is True
        assert run.result["previous_sha256"] != run.result["sha256"]

    def test_append_mode_keeps_the_existing_content(self, ws, root):
        _grant(ws, "fs.write")
        ws.tools.execute("fs.write", {"path": "log.txt", "content": "one\n"})
        ws.tools.execute("fs.write", {"path": "log.txt", "content": "two\n", "append": True})
        assert open(os.path.join(root, "log.txt")).read() == "one\ntwo\n"

    def test_dry_run_writes_nothing(self, ws, root):
        _grant(ws, "fs.write")
        run = ws.tools.execute("fs.write", {"path": "preview.txt", "content": "hi"}, dry_run=True)
        assert run.status == "succeeded" and run.dry_run
        assert run.result["dry_run"] is True
        assert not os.path.exists(os.path.join(root, "preview.txt"))

    def test_read_returns_content_hash_and_line_window(self, ws):
        _grant(ws, "fs.write")
        _grant(ws, "fs.read")
        ws.tools.execute("fs.write", {"path": "lines.txt", "content": "a\nb\nc\nd"})
        run = ws.tools.execute("fs.read", {"path": "lines.txt", "start_line": 2, "max_lines": 2})
        assert run.result["content"] == "b\nc"
        assert run.result["total_lines"] == 4

    def test_read_refuses_a_binary_file(self, ws, root):
        _grant(ws, "fs.read")
        with open(os.path.join(root, "blob.bin"), "wb") as fh:
            fh.write(b"\x00\x01\x02binary")
        with pytest.raises(ToolError, match="binary"):
            ws.tools.execute("fs.read", {"path": "blob.bin"})
        assert ws.tools.runs(tool="fs.read")[0]["status"] == "failed"

    def test_read_of_a_missing_file_is_a_failed_run_not_a_crash(self, ws):
        _grant(ws, "fs.read")
        assert isinstance(_attempt(ws, "fs.read", {"path": "nope.txt"}), ToolError)
        assert ws.tools.runs(tool="fs.read")[0]["status"] == "failed"

    def test_list_reports_entries_and_kinds(self, ws):
        _grant(ws, "fs.write")
        _grant(ws, "fs.read", subject="fs.list")
        ws.tools.execute("fs.write", {"path": "sub/one.txt", "content": "x"})
        run = ws.tools.execute("fs.list", {"path": "sub"})
        assert [e["name"] for e in run.result["entries"]] == ["one.txt"]
        assert run.result["entries"][0]["kind"] == "file"

    def test_delete_needs_its_own_capability(self, ws):
        _grant(ws, "fs.write")
        _grant(ws, "fs.read")
        ws.tools.execute("fs.write", {"path": "gone.txt", "content": "x"})
        with pytest.raises(ApprovalRequiredError) as exc:
            ws.tools.execute("fs.delete", {"path": "gone.txt"})
        assert exc.value.capability == "fs.delete"

    def test_delete_dry_run_then_real_delete(self, ws, root):
        _grant(ws, "fs.write")
        _grant(ws, "fs.delete")
        ws.tools.execute("fs.write", {"path": "gone.txt", "content": "x"})
        preview = ws.tools.execute("fs.delete", {"path": "gone.txt"}, dry_run=True)
        assert preview.result["deleted"] is False
        assert os.path.exists(os.path.join(root, "gone.txt"))
        real = ws.tools.execute("fs.delete", {"path": "gone.txt"})
        assert real.result["deleted"] is True
        assert not os.path.exists(os.path.join(root, "gone.txt"))

    def test_traversal_is_refused(self, ws):
        _grant(ws, "fs.read")
        with pytest.raises(PathEscapesRootError):
            ws.tools.execute("fs.read", {"path": "../../etc/passwd"})

    def test_absolute_path_outside_the_roots_is_refused(self, ws):
        _grant(ws, "fs.read")
        with pytest.raises(PathEscapesRootError):
            ws.tools.execute("fs.read", {"path": "/etc/passwd"})

    def test_symlink_escape_is_refused(self, ws, root, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        os.symlink(outside, os.path.join(root, "link.txt"))
        _grant(ws, "fs.read")
        with pytest.raises(PathEscapesRootError):
            ws.tools.execute("fs.read", {"path": "link.txt"})

    def test_oversized_write_is_refused_by_the_limit(self, ws):
        with open_workspace(
            home=str(ws.config.home), env={}, overrides={"tools.max_file_bytes": 1024}
        ) as reopened:
            _grant(reopened, "fs.write")
            with pytest.raises(ToolError, match="max_file_bytes"):
                reopened.tools.execute("fs.write", {"path": "big.txt", "content": "x" * 2048})

    def test_directory_delete_is_refused(self, ws):
        _grant(ws, "fs.delete")
        os.makedirs(os.path.join(ws.tool_roots()[0], "adir"), exist_ok=True)
        with pytest.raises(ToolError, match="directory"):
            ws.tools.execute("fs.delete", {"path": "adir"})


# --------------------------------------------------------------------------
# process execution
# --------------------------------------------------------------------------
class TestShellTool:
    def test_shell_needs_a_grant_and_then_runs(self, ws):
        with pytest.raises(ApprovalRequiredError):
            ws.tools.execute("shell.run", {"command": "echo hi"})
        approval_id = ws.permissions.pending()[0].id
        ws.permissions.approve(approval_id)
        run = ws.tools.execute("shell.run", {"command": "echo hi"})
        assert run.status == "succeeded"
        assert run.result["stdout"].strip() == "hi"
        assert run.result["exit_code"] == 0

    def test_nonzero_exit_is_a_failed_run_with_the_code(self, ws):
        _grant(ws, "shell.run")
        run = ws.tools.execute("shell.run", {"command": "false"})
        assert run.status == "failed"
        assert run.result["exit_code"] == 1
        assert "exited with 1" in run.error

    def test_timeout_kills_the_process(self, ws):
        _grant(ws, "shell.run")
        run = ws.tools.execute("shell.run", {"command": "sleep 5", "timeout": 1})
        assert run.status == "failed"
        assert run.result["timed_out"] is True
        assert "killed after" in run.result["stderr"]

    def test_denylisted_program_cannot_be_approved(self, ws):
        with pytest.raises(PermissionDeniedError) as exc:
            ws.tools.execute("shell.run", {"command": "sudo ls"})
        assert getattr(exc.value, "approval_id", None) is None
        assert "denylist" in exc.value.message
        assert ws.permissions.pending() == []

    def test_missing_program_is_a_clear_error(self, ws):
        _grant(ws, "shell.run")
        with pytest.raises(ToolError, match="command not found"):
            ws.tools.execute("shell.run", {"command": "definitely-not-a-real-binary-xyz"})

    def test_child_process_does_not_inherit_secrets(self, ws, monkeypatch):
        monkeypatch.setenv("ARCHX_TEST_TOKEN", "super-secret-value")
        _grant(ws, "shell.run")
        run = ws.tools.execute("shell.run", {"command": "env"})
        assert run.status == "succeeded"
        assert "super-secret-value" not in run.result["stdout"]
        assert "ARCHX_TEST_TOKEN" not in run.result["stdout"]

    def test_shell_metacharacters_are_not_interpreted(self, ws):
        _grant(ws, "shell.run")
        run = ws.tools.execute("shell.run", {"command": "echo one; echo two"})
        assert run.status == "succeeded"
        assert run.result["argv"] == ["echo", "one;", "echo", "two"]
        assert "two" in run.result["stdout"]

    def test_cwd_outside_the_roots_is_refused(self, ws):
        _grant(ws, "shell.run")
        with pytest.raises(PathEscapesRootError):
            ws.tools.execute("shell.run", {"command": "pwd", "cwd": "/etc"})


# --------------------------------------------------------------------------
# run records, traces, integration seams
# --------------------------------------------------------------------------
class TestRunsAndTrace:
    def test_denied_attempts_are_recorded_with_the_approval_id(self, ws):
        with pytest.raises(ApprovalRequiredError) as exc:
            ws.tools.execute("fs.write", {"path": "x.txt", "content": "x"})
        row = ws.tools.runs(tool="fs.write")[0]
        assert row["status"] == "denied"
        assert row["approval_id"] == exc.value.approval_id
        assert "not granted" in row["error"]

    def test_run_sequence_increases_and_is_ordered(self, ws):
        _grant(ws, "fs.write")
        _grant(ws, "fs.read")
        _grant(ws, "fs.delete")
        ws.tools.execute("fs.write", {"path": "seq.txt", "content": "x"})
        ws.tools.execute("fs.read", {"path": "seq.txt"})
        ws.tools.execute("fs.delete", {"path": "seq.txt"})
        rows = ws.tools.runs(limit=10)
        assert [row["seq"] for row in rows] == [3, 2, 1]
        assert [row["tool_name"] for row in rows] == ["fs.delete", "fs.read", "fs.write"]

    def test_single_use_grant_is_consumed_even_when_the_tool_fails(self, ws):
        decision = ws.permissions.check("fs.read", subject="fs.read")
        ws.permissions.approve(decision.approval_id)
        with pytest.raises(ToolError):
            ws.tools.execute("fs.read", {"path": "missing.txt"})
        with pytest.raises(ApprovalRequiredError):
            ws.tools.execute("fs.read", {"path": "missing.txt"})

    def test_tool_without_a_capability_runs_without_a_grant(self, ws):
        run = ws.tools.execute("archx.info", {})
        assert run.status == "succeeded"
        assert run.result["home"]
        assert run.result["tool_limits"]["roots"]

    def test_dry_run_is_recorded_in_the_run_row(self, ws):
        _grant(ws, "fs.write")
        ws.tools.execute("fs.write", {"path": "d.txt", "content": "x"}, dry_run=True)
        assert ws.tools.runs(tool="fs.write")[0]["dry_run"] == 1

    def test_file_change_is_traced_with_hashes(self, ws):
        _grant(ws, "fs.write")
        run = ws.tools.execute("fs.write", {"path": "traced.txt", "content": "x"})
        ws.events.flush()
        events = ws.events.query(kind="file_change", limit=10)
        assert events
        payload = events[0].payload
        assert payload["path"] == "traced.txt"
        assert payload["sha256"] == run.result["sha256"]

    def test_permission_decisions_are_traced_both_ways(self, ws):
        _grant(ws, "fs.read")
        ws.permissions.check("fs.read", subject="fs.read", request_approval_on_denial=False)
        ws.permissions.check("fs.write", subject="fs.write", request_approval_on_denial=False)
        ws.events.flush()
        events = ws.events.query(kind="permission", limit=50)
        statuses = {e.status for e in events if e.name == "check"}
        assert {"ok", "denied"} <= statuses

    def test_tool_call_events_record_the_outcome(self, ws):
        _grant(ws, "fs.write")
        ws.tools.execute("fs.write", {"path": "e.txt", "content": "x"})
        ws.events.flush()
        events = ws.events.query(kind="tool_call", limit=20)
        assert any(e.status == "succeeded" for e in events)

    def test_context_is_carried_to_the_permission_check(self, ws):
        _grant(ws, "fs.read", duration="conversation", conversation_id="conv-9")
        with pytest.raises(ToolError):
            ws.tools.execute(
                "fs.read",
                {"path": "missing.txt"},
                context=ToolContext(conversation_id="conv-9", purpose="test"),
            )
        run = ws.tools.runs(tool="fs.read")[0]
        assert run["status"] == "failed"
        # the conversation grant applied: no approval row was created
        assert [a for a in ws.permissions.approvals(status="pending") if a.subject == "fs.read"] == []

    def test_registry_counts_active_grants(self, ws):
        before = {row["name"]: row["active_grants"] for row in ws.tools.registry()}
        assert before["fs.write"] == 0
        _grant(ws, "fs.write")
        after = {row["name"]: row["active_grants"] for row in ws.tools.registry()}
        assert after["fs.write"] == 1

    def test_durations_are_the_documented_set(self):
        assert set(DURATIONS) == {"once", "task", "conversation", "project", "persistent"}

    def test_tool_manager_survives_a_reopen(self, tmp_path):
        home = str(tmp_path / "reopen")
        with open_workspace(home=home, env={}) as first:
            first.permissions.grant("fs.write", subject="fs.write", duration="persistent", confirm=True)
            run = first.tools.execute("fs.write", {"path": "kept.txt", "content": "kept"})
            assert run.status == "succeeded"
        with open_workspace(home=home, env={}) as second:
            again = second.tools.execute("fs.write", {"path": "kept2.txt", "content": "kept"})
            assert again.status == "succeeded"
            assert {r["tool_name"] for r in second.tools.runs()} == {"fs.write"}


# --------------------------------------------------------------------------
# authority: nothing self-grants
# --------------------------------------------------------------------------
class TestAuthority:
    def test_tool_cannot_pass_itself_a_capability_argument(self, ws):
        _grant(ws, "fs.write")
        with pytest.raises(ToolValidationError, match="capability"):
            ws.tools.execute(
                "fs.write", {"path": "x.txt", "content": "y", "capability": "fs.delete"}
            )

    def test_tool_manager_exposes_no_grant_api(self, ws):
        for name in ("grant", "approve", "allow", "authorize"):
            assert not hasattr(ws.tools, name)

    def test_registry_spec_cannot_be_mutated_after_registration(self, ws):
        spec = ws.tools.spec("fs.write")
        with pytest.raises(Exception):
            spec.capability = "fs.read"  # frozen dataclass

    def test_a_denial_leaves_no_grant_behind(self, ws):
        with pytest.raises(ApprovalRequiredError):
            ws.tools.execute("fs.write", {"path": "x.txt", "content": "y"})
        assert ws.permissions.grants(include_expired=True) == []
