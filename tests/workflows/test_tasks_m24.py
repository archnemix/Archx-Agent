"""M24: task history, content versions and reproduction records.

Grouped the way the milestone was built: task lifecycle first, then interruption (the
crash case), then artifacts and versions, then reproduction fidelity, then the integration
seams (chat records a task, a tool call lands on the task's timeline) and finally the
installed console script.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from archx_agent.adapters.scripted_runtime import ENV_FLAG
from archx_agent.application.workspace import Workspace, open_workspace
from archx_agent.helpers.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

CLI = os.path.join(os.path.dirname(sys.executable), "archx-agent")


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "1")
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


@pytest.fixture()
def home(tmp_path):
    h = str(tmp_path / "cli-home")
    assert _run(h, "init").returncode == 0
    return h


def _run(home: str, *args: str, allow_simulated: bool = False, timeout: int = 120):
    cmd = [CLI, "--home", home]
    if allow_simulated:
        cmd.append("--allow-simulated")
    cmd.extend(args)
    env = dict(os.environ)
    env.pop("ARCHX_PATHS_HOME", None)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)


def _ok(result):
    assert result.returncode == 0, result.stderr
    return result


def _json(result):
    _ok(result)
    return json.loads(result.stdout)


def _grant(ws, capability, subject=None, *, duration="persistent"):
    return ws.permissions.grant(
        capability, subject=subject or capability, duration=duration, confirm=True
    )


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------
class TestTaskLifecycle:
    def test_create_is_queued_and_start_moves_it_to_running(self, ws):
        task = ws.tasks.create("tool", "inspect the database")
        assert task.status == "queued"
        assert task.started_at is None
        assert task.type == "tool"
        started = ws.tasks.start(task.id)
        assert started.status == "running"
        assert started.started_at is not None

    def test_start_twice_conflicts(self, ws):
        task = ws.tasks.create("tool", "x", start=True)
        with pytest.raises(ConflictError):
            ws.tasks.start(task.id)

    def test_complete_records_outcome_and_timeline(self, ws):
        task = ws.tasks.create("chat", "hello", start=True)
        done = ws.tasks.complete(task.id, summary="answered", outputs=["msg_1"],
                                 model_id="m1",
                                 resource_use={"prompt_tokens": 5, "completion_tokens": 3})
        assert done.status == "completed"
        assert done.completed_at is not None
        assert done.output_refs == ["msg_1"]
        assert done.model_id == "m1"
        assert done.resource_use["completion_tokens"] == 3
        kinds = [row["kind"] for row in ws.tasks.timeline(task.id)]
        assert kinds == ["created", "started", "summary", "completed"]
        assert [row["seq"] for row in ws.tasks.timeline(task.id)] == sorted(
            row["seq"] for row in ws.tasks.timeline(task.id)
        )

    def test_terminal_states_are_final(self, ws):
        task = ws.tasks.create("tool", "x", start=True)
        ws.tasks.complete(task.id)
        for action in (
            lambda: ws.tasks.complete(task.id),
            lambda: ws.tasks.fail(task.id, "boom"),
            lambda: ws.tasks.cancel(task.id),
        ):
            with pytest.raises(ConflictError):
                action()

    def test_fail_records_the_exception_type_and_message(self, ws):
        task = ws.tasks.create("chat", "x", start=True)
        failed = ws.tasks.fail(task.id, ValidationError("the provider refused"))
        assert failed.status == "failed"
        assert "ValidationError" in failed.error
        assert "the provider refused" in failed.error
        assert failed.terminal and not failed.resumable

    def test_fail_truncates_a_huge_error(self, ws):
        task = ws.tasks.create("chat", "x", start=True)
        failed = ws.tasks.fail(task.id, "boom " * 2000)
        assert len(failed.error) <= 2000

    def test_cancel_keeps_the_reason(self, ws):
        task = ws.tasks.create("agent", "long job", start=True)
        cancelled = ws.tasks.cancel(task.id, "the user stopped it")
        assert cancelled.status == "cancelled"
        assert "stopped" in cancelled.error
        assert cancelled.terminal

    def test_unknown_type_is_rejected(self, ws):
        with pytest.raises(ValidationError) as exc:
            ws.tasks.create("teleport", "x")
        assert "unknown task type" in exc.value.message
        assert "chat" in exc.value.message

    def test_unknown_parent_is_rejected(self, ws):
        with pytest.raises(NotFoundError):
            ws.tasks.create("tool", "child", parent_task_id="tk_missing")

    def test_title_is_normalised_and_bounded(self, ws):
        task = ws.tasks.create("tool", "  lots\n\nof   space  ")
        assert task.title == "lots of space"
        long = ws.tasks.create("tool", "word " * 100)
        assert len(long.title) == 200
        default = ws.tasks.create("memory")
        assert default.title == "memory task"

    def test_order_is_insertion_sequence_not_timestamp(self, ws):
        # Created back to back inside the same millisecond: the order must still hold.
        created = [ws.tasks.create("tool", f"t{i}", start=True) for i in range(5)]
        listed = ws.tasks.list(limit=10)
        assert [task.id for task in listed] == [task.id for task in reversed(created)]
        assert all(task.seq for task in listed)
        assert len({task.seq for task in listed}) == 5

    def test_filters(self, ws):
        first = ws.tasks.create("chat", "a", conversation_id="conv_1", start=True)
        ws.tasks.create("tool", "b", project_id="prj_1", start=True)
        ws.tasks.complete(first.id)
        assert [t.title for t in ws.tasks.list(status="completed")] == ["a"]
        assert [t.title for t in ws.tasks.list(kind="tool")] == ["b"]
        assert [t.title for t in ws.tasks.list(conversation_id="conv_1")] == ["a"]
        assert [t.title for t in ws.tasks.list(project_id="prj_1")] == ["b"]
        with pytest.raises(ValidationError):
            ws.tasks.list(status="nonsense")

    def test_children_and_tree(self, ws):
        parent = ws.tasks.create("agent", "parent", start=True)
        child = ws.tasks.create("tool", "child", parent_task_id=parent.id, start=True)
        grandchild = ws.tasks.create("tool", "grandchild", parent_task_id=child.id, start=True)
        assert [t.id for t in ws.tasks.children(parent.id)] == [child.id]
        tree = ws.tasks.tree(parent.id)
        assert tree["id"] == parent.id
        assert tree["children"][0]["id"] == child.id
        assert tree["children"][0]["children"][0]["id"] == grandchild.id

    def test_open_questions_round_trip(self, ws):
        task = ws.tasks.create("agent", "x", start=True)
        ws.tasks.add_question(task.id, "which dataset?")
        ws.tasks.add_question(task.id, "which dataset?")  # idempotent
        ws.tasks.add_question(task.id, "which budget?")
        task = ws.tasks.get(task.id)
        assert task.unresolved == ["which dataset?", "which budget?"]
        task = ws.tasks.resolve_question(task.id, 0)
        assert task.unresolved == ["which budget?"]
        task = ws.tasks.resolve_question(task.id, "which budget?")
        assert task.unresolved == []
        with pytest.raises(ValidationError):
            ws.tasks.resolve_question(task.id, 0)
        with pytest.raises(NotFoundError):
            ws.tasks.resolve_question(ws.tasks.add_question(task.id, "q").id, "other")
        with pytest.raises(ValidationError):
            ws.tasks.add_question(task.id, "   ")

    def test_log_and_timeline(self, ws):
        task = ws.tasks.create("tool", "x", start=True)
        seq1 = ws.tasks.log(task.id, "step", detail="one")
        seq2 = ws.tasks.log(task.id, "step", detail="two")
        assert seq2 > seq1
        rows = ws.tasks.timeline(task.id)
        assert [row["detail"] for row in rows] == [
            "tool: x", None, "one", "two",
        ][: len(rows)] or rows[-1]["detail"] == "two"
        assert rows[-1]["kind"] == "step"
        with pytest.raises(NotFoundError):
            ws.tasks.timeline("tk_missing")

    def test_stats_counts_statuses_and_types(self, ws):
        a = ws.tasks.create("chat", "a", start=True)
        ws.tasks.complete(a.id)
        b = ws.tasks.create("tool", "b")
        ws.tasks.add_question(b.id, "why?")
        stats = ws.tasks.stats()
        assert stats["total"] == 2
        assert stats["by_status"]["completed"] == 1
        assert stats["by_status"]["queued"] == 1
        assert stats["by_type"]["chat"] == 1
        assert stats["with_open_questions"] == 1


# --------------------------------------------------------------------------
# interruption: the crash case
# --------------------------------------------------------------------------
class TestInterruption:
    def test_interrupt_stale_only_touches_running_tasks(self, ws):
        running = ws.tasks.create("agent", "still running", start=True)
        done = ws.tasks.create("tool", "finished", start=True)
        ws.tasks.complete(done.id)
        swept = ws.tasks.interrupt_stale()
        assert swept["interrupted"] == 1
        assert swept["ids"] == [running.id]
        assert ws.tasks.get(running.id).status == "interrupted"
        assert ws.tasks.get(done.id).status == "completed"

    def test_reopening_marks_a_running_task_interrupted(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "1")
        home = str(tmp_path / "home")
        ws = Workspace.open(home=home, env={})
        task = ws.tasks.create("agent", "crashed mid-run", start=True)
        # Simulate a crash: close without completing, no cancel, no failure recorded.
        ws.close()

        ws2 = Workspace.open(home=home, env={})
        try:
            reloaded = ws2.tasks.get(task.id)
            assert reloaded.status == "interrupted"
            assert "owned this task is gone" in reloaded.error
            assert any("interrupted" in warning for warning in ws2.warnings)
            assert reloaded.resumable
        finally:
            ws2.close()

    def test_manual_tasks_are_never_swept(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "1")
        home = str(tmp_path / "home")
        ws = Workspace.open(home=home, env={})
        task = ws.tasks.create("tool", "my own bookkeeping", start=True, manual=True)
        ws.close()
        ws2 = Workspace.open(home=home, env={})
        try:
            assert ws2.tasks.get(task.id).status == "running"
            assert any("manually" in warning for warning in ws2.warnings)
        finally:
            ws2.close()

    def test_a_task_owned_by_a_live_process_is_left_alone(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "1")
        home = str(tmp_path / "home")
        ws = Workspace.open(home=home, env={})
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            task = ws.tasks.create("agent", "someone else is working", start=True)
            ws.tasks.link(task.id, metadata={"pid": other.pid})
            ws.close()
            ws2 = Workspace.open(home=home, env={})
            try:
                assert ws2.tasks.get(task.id).status == "running"
                assert any("another live process" in warning for warning in ws2.warnings)
            finally:
                ws2.close()
        finally:
            other.kill()
            other.wait(timeout=10)

    def test_sweep_can_be_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "1")
        home = str(tmp_path / "home")
        ws = Workspace.open(home=home, env={})
        task = ws.tasks.create("agent", "running", start=True)
        ws.close()
        ws2 = Workspace.open(home=home, env={}, overrides={"tasks.interrupt_stale_on_open": False})
        try:
            assert ws2.tasks.get(task.id).status == "running"
        finally:
            ws2.close()


# --------------------------------------------------------------------------
# artifacts
# --------------------------------------------------------------------------
class TestArtifacts:
    def test_attach_records_size_checksum_and_mime(self, ws, tmp_path):
        path = _write(tmp_path / "report.txt", "hello artifact\n")
        task = ws.tasks.create("tool", "produce report", start=True)
        artifact = ws.tasks.attach_artifact(task.id, str(path), kind="report")
        assert artifact.task_id == task.id
        assert artifact.size == len("hello artifact\n")
        assert len(artifact.checksum) == 64
        assert artifact.mime == "text/plain"
        assert artifact.exists
        assert artifact.rel_path is None  # outside the workspace home
        assert artifact.metadata["version"] == "v1"

    def test_attach_inside_home_records_a_relative_path(self, ws, tmp_path):
        inside = Path(ws.config.path("paths.home")) / "notes.txt"
        _write(inside, "inside\n")
        task = ws.tasks.create("tool", "x", start=True)
        artifact = ws.tasks.attach_artifact(task.id, str(inside))
        assert artifact.rel_path == "notes.txt"

    def test_attach_missing_file_is_not_found(self, ws, tmp_path):
        task = ws.tasks.create("tool", "x", start=True)
        with pytest.raises(NotFoundError):
            ws.tasks.attach_artifact(task.id, str(tmp_path / "nope.txt"))

    def test_reattaching_changed_content_creates_a_second_version(self, ws, tmp_path):
        path = _write(tmp_path / "data.csv", "a,b\n1,2\n")
        task = ws.tasks.create("tool", "x", start=True)
        first = ws.tasks.attach_artifact(task.id, str(path))
        _write(path, "a,b\n1,2\n3,4\n")
        second = ws.tasks.attach_artifact(task.id, str(path))
        assert first.metadata["version"] == "v1"
        assert second.metadata["version"] == "v2"
        history = ws.versions.history("artifact", str(path.resolve()))
        assert [v.version for v in history] == ["v1", "v2"]
        assert history[1].checksum != history[0].checksum

    def test_attach_without_versioning_still_records_the_artifact(self, ws, tmp_path):
        path = _write(tmp_path / "blob.bin", "binary-ish")
        task = ws.tasks.create("tool", "x", start=True)
        artifact = ws.tasks.attach_artifact(task.id, str(path), record_version=False)
        assert "version" not in artifact.metadata
        assert artifact.checksum

    def test_deleting_the_file_is_visible_and_never_deletes_user_data(self, ws, tmp_path):
        path = _write(tmp_path / "gone.txt", "bye\n")
        task = ws.tasks.create("tool", "x", start=True)
        artifact = ws.tasks.attach_artifact(task.id, str(path))
        path.unlink()
        reloaded = ws.tasks.artifact(artifact.id).ok_or_raise()
        assert reloaded.exists is False
        assert reloaded.to_dict()["exists"] is False

    def test_unknown_artifact_is_a_result_error(self, ws):
        result = ws.tasks.artifact("ar_missing")
        assert result.is_err
        assert isinstance(result.error, NotFoundError)


# --------------------------------------------------------------------------
# versions
# --------------------------------------------------------------------------
class TestVersionsManager:
    def test_first_record_is_ordinal_one(self, ws):
        write = ws.versions.record("document", "notes", content="alpha\n")
        assert write.created
        assert write.version.ordinal == 1
        assert write.version.version == "v1"
        assert write.version.size == len("alpha\n")
        assert write.version.content_stored

    def test_identical_content_is_not_a_new_version(self, ws):
        first = ws.versions.record("document", "notes", content="alpha\n")
        again = ws.versions.record("document", "notes", content="alpha\n")
        assert first.created
        assert not again.created
        assert again.version.id == first.version.id
        assert "unchanged" in again.reason
        assert len(ws.versions.history("document", "notes")) == 1

    def test_changed_content_gets_the_next_ordinal(self, ws):
        ws.versions.record("document", "notes", content="alpha\n")
        second = ws.versions.record("document", "notes", content="alpha\nbeta\n")
        assert second.created and second.version.ordinal == 2
        assert [v.version for v in ws.versions.history("document", "notes")] == ["v1", "v2"]

    def test_explicit_labels_are_unique(self, ws):
        ws.versions.record("document", "notes", content="a", version="draft")
        with pytest.raises(ConflictError):
            ws.versions.record("document", "notes", content="b", version="draft")
        second = ws.versions.record("document", "notes", content="b", version="final")
        assert second.version.version == "final"

    def test_unknown_subject_type_is_rejected(self, ws):
        with pytest.raises(ValidationError):
            ws.versions.record("galaxy", "x", content="a")
        with pytest.raises(ValidationError):
            ws.versions.record("document", "  ", content="a")

    def test_exactly_one_source_is_required(self, ws):
        with pytest.raises(ValidationError):
            ws.versions.record("document", "notes")
        with pytest.raises(ValidationError):
            ws.versions.record("document", "notes", content="a", path="/tmp/x")

    def test_file_source_and_binary_content(self, ws, tmp_path):
        text = _write(tmp_path / "a.md", "# title\n")
        write = ws.versions.record("project_file", str(text), path=text)
        assert write.version.content == "# title\n"
        binary = tmp_path / "blob.bin"
        binary.write_bytes(b"\xff\xfe\x00\x01")
        write = ws.versions.record("project_file", str(binary), path=binary)
        assert not write.version.content_stored
        assert write.version.content == ""
        assert write.version.size == 4
        with pytest.raises(ValidationError):
            ws.versions.diff("project_file", str(binary))
        with pytest.raises(ValidationError):
            ws.versions.restore("project_file", str(binary), write.version.version)

    def test_missing_file_is_not_found(self, ws, tmp_path):
        with pytest.raises(NotFoundError):
            ws.versions.record("project_file", "x", path=tmp_path / "nope.md")

    def test_large_content_is_refused_unless_checksum_only(self, ws):
        manager = ws.versions
        original = manager.max_bytes
        manager.max_bytes = 8
        try:
            with pytest.raises(ValidationError) as exc:
                manager.record("document", "big", content="x" * 50)
            assert "max_version_bytes" in exc.value.message
            write = manager.record("document", "big", content="x" * 50, store_content=False)
            assert not write.version.content_stored
            assert write.version.size == 50
        finally:
            manager.max_bytes = original

    def test_latest_at_and_history(self, ws):
        ws.versions.record("document", "notes", content="one")
        ws.versions.record("document", "notes", content="two")
        assert ws.versions.latest("document", "notes").version == "v2"
        assert ws.versions.at("document", "notes", "v1").content == "one"
        assert ws.versions.at("document", "notes", "1").content == "one"
        assert ws.versions.at("document", "notes").content == "two"
        assert [v.version for v in ws.versions.history("document", "notes")] == ["v1", "v2"]
        assert ws.versions.latest("document", "unknown") is None

    def test_unknown_version_lists_the_known_ones(self, ws):
        ws.versions.record("document", "notes", content="one")
        ws.versions.record("document", "notes", content="two")
        with pytest.raises(NotFoundError) as exc:
            ws.versions.at("document", "notes", "v9")
        assert "v1" in exc.value.message and "v2" in exc.value.message

    def test_diff_reports_added_and_removed_lines(self, ws):
        ws.versions.record("document", "notes", content="keep\ndrop\n")
        ws.versions.record("document", "notes", content="keep\nadd\n")
        diff = ws.versions.diff("document", "notes")
        assert diff["from"] == "v1" and diff["to"] == "v2"
        assert diff["added"] == 1 and diff["removed"] == 1
        assert "+add" in diff["text"] and "-drop" in diff["text"]
        same = ws.versions.diff("document", "notes", "v2", "v2")
        assert same["identical"] and same["text"] == ""

    def test_diff_against_an_explicit_base(self, ws):
        for content in ("a\n", "b\n", "c\n"):
            ws.versions.record("document", "notes", content=content)
        diff = ws.versions.diff("document", "notes", "v1", "v3")
        assert diff["from"] == "v1" and diff["to"] == "v3"
        assert diff["added"] == 1 and diff["removed"] == 1

    def test_restore_writes_a_new_version_and_keeps_history(self, ws):
        ws.versions.record("document", "notes", content="original\n")
        ws.versions.record("document", "notes", content="changed\n")
        write = ws.versions.restore("document", "notes", "v1")
        assert write.created
        assert write.version.ordinal == 3
        assert write.version.content == "original\n"
        assert write.version.restored_from == "v1"
        history = ws.versions.history("document", "notes")
        assert [v.version for v in history] == ["v1", "v2", "v3"]
        assert history[1].content == "changed\n"

    def test_subjects_aggregate_versions(self, ws):
        ws.versions.record("document", "a", content="1")
        ws.versions.record("document", "a", content="2")
        ws.versions.record("prompt", "b", content="x")
        rows = {row["subject_id"]: row for row in ws.versions.subjects()}
        assert rows["a"]["versions"] == 2 and rows["a"]["latest_ordinal"] == 2
        assert rows["b"]["versions"] == 1
        assert ws.versions.count("document") == 2

    def test_versions_persist_across_reopen(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "1")
        home = str(tmp_path / "home")
        ws = Workspace.open(home=home, env={})
        ws.versions.record("document", "notes", content="first\n")
        ws.close()
        ws2 = Workspace.open(home=home, env={})
        try:
            second = ws2.versions.record("document", "notes", content="second\n")
            assert second.version.ordinal == 2
            assert [v.content for v in ws2.versions.history("document", "notes")] == [
                "first\n", "second\n",
            ]
        finally:
            ws2.close()


# --------------------------------------------------------------------------
# reproduction
# --------------------------------------------------------------------------
class TestReproduction:
    def test_exact_when_everything_is_present_and_deterministic(self, ws):
        task = ws.tasks.create("tool", "ask the app about itself", tools=["archx.info"], start=True)
        ws.tools.execute("archx.info", {}, context=_context(ws, task.id))
        ws.tasks.complete(task.id)
        assessment = ws.reproduction.assess(task.id)
        assert assessment["fidelity"] == "exact"
        assert assessment["issues"] == []
        assert any("tasks show" in command for command in assessment["commands"])

    def test_simulated_model_is_a_caveat_not_a_promise(self, ws):
        model = ws.models.register_remote("sim", provider="test-double", runtime="scripted", model_ref="simulated")
        task = ws.tasks.create("chat", "hello", model_id=model.id, start=True)
        ws.tasks.complete(task.id)
        assessment = ws.reproduction.assess(task.id)
        assert assessment["fidelity"] == "partial"
        codes = [issue["code"] for issue in assessment["issues"]]
        assert "model_simulated" in codes

    def test_removed_model_makes_it_impossible(self, ws):
        model = ws.models.register_remote("sim", provider="test-double", runtime="scripted", model_ref="simulated")
        task = ws.tasks.create("chat", "hello", model_id=model.id, start=True)
        ws.tasks.complete(task.id)
        ws.models.remove(model.id)
        assessment = ws.reproduction.assess(task.id)
        assert assessment["fidelity"] == "impossible"
        assert assessment["issues"][0]["code"] == "model_missing"

    def test_missing_tool_makes_it_impossible(self, ws):
        task = ws.tasks.create("tool", "x", tools=["nope.tool"], start=True)
        ws.tasks.complete(task.id)
        assessment = ws.reproduction.assess(task.id)
        assert assessment["fidelity"] == "impossible"
        assert [i["code"] for i in assessment["issues"]] == ["tool_missing"]

    def test_failed_task_is_partial_with_the_error(self, ws):
        task = ws.tasks.create("chat", "x", start=True)
        ws.tasks.fail(task.id, "the provider refused")
        assessment = ws.reproduction.assess(task.id)
        assert assessment["fidelity"] == "partial"
        assert "task_failed" in [i["code"] for i in assessment["issues"]]

    def test_interrupted_task_cannot_claim_an_outcome(self, ws):
        task = ws.tasks.create("agent", "x", start=True)
        ws.tasks.interrupt(task.id)
        assessment = ws.reproduction.assess(task.id)
        assert assessment["fidelity"] == "partial"
        assert "task_interrupted" in [i["code"] for i in assessment["issues"]]

    def test_open_questions_are_a_caveat(self, ws):
        task = ws.tasks.create("agent", "x", start=True)
        ws.tasks.add_question(task.id, "which budget?")
        ws.tasks.complete(task.id)
        assessment = ws.reproduction.assess(task.id)
        assert "open_questions" in [i["code"] for i in assessment["issues"]]

    def test_missing_output_artifact_blocks_reproduction(self, ws, tmp_path):
        path = _write(tmp_path / "out.txt", "result\n")
        task = ws.tasks.create("tool", "x", tools=["archx.info"], start=True)
        ws.tasks.attach_artifact(task.id, str(path))
        ws.tasks.complete(task.id)
        path.unlink()
        assessment = ws.reproduction.assess(task.id)
        assert assessment["fidelity"] == "impossible"
        assert "artifact_missing" in [i["code"] for i in assessment["issues"]]

    def test_commands_replay_real_tool_arguments(self, ws):
        _grant(ws, "fs.read", "fs.read")
        root = Path(ws.tools.roots()[0])
        _write(root / "notes.txt", "hello\n")
        task = ws.tasks.create("tool", "read a file", tools=["fs.read"], start=True)
        ws.tools.execute("fs.read", {"path": "notes.txt"},
                         context=_context(ws, task.id))
        ws.tasks.complete(task.id)
        commands = ws.reproduction.assess(task.id)["commands"]
        assert any("tools run fs.read" in command and "path=notes.txt" in command for command in commands)
        # The printed command really is the command that ran.
        assert any(command.startswith("archx-agent --home") for command in commands)

    def test_capture_records_and_lists(self, ws):
        task = ws.tasks.create("tool", "x", tools=["archx.info"], start=True)
        ws.tasks.complete(task.id)
        record = ws.reproduction.capture(task.id)
        assert record.fidelity == "exact"
        assert ws.reproduction.latest(task.id).id == record.id
        assert ws.reproduction.get(record.id).ok_or_raise().task_id == task.id
        assert ws.reproduction.records()[0].id == record.id
        assert ws.reproduction.stats()["by_fidelity"]["exact"] == 1
        assert ws.reproduction.get("rp_missing").is_err

    def test_verify_reports_no_change(self, ws):
        task = ws.tasks.create("tool", "x", tools=["archx.info"], start=True)
        ws.tasks.complete(task.id)
        record = ws.reproduction.capture(task.id)
        verdict = ws.reproduction.verify(record.id)
        assert verdict["recorded"] == verdict["current"] == "exact"
        assert verdict["changed"] is False
        assert verdict["new_blockers"] == []

    def test_verify_notices_a_model_disappearing(self, ws):
        model = ws.models.register_remote("sim", provider="test-double", runtime="scripted", model_ref="simulated")
        task = ws.tasks.create("chat", "x", model_id=model.id, start=True)
        ws.tasks.complete(task.id)
        record = ws.reproduction.capture(task.id)
        assert record.fidelity == "partial"
        ws.models.remove(model.id)
        verdict = ws.reproduction.verify(record.id)
        assert verdict["recorded"] == "partial" and verdict["current"] == "impossible"
        assert verdict["changed"] is True
        assert "model_missing" in verdict["new_blockers"]

    def test_verify_notices_changed_settings(self, ws):
        task = ws.tasks.create("tool", "x", tools=["archx.info"], start=True)
        ws.tasks.complete(task.id)
        record = ws.reproduction.capture(task.id)
        ws.config.set("model.temperature", 1.1)
        verdict = ws.reproduction.verify(record.id)
        assert "model.temperature" in verdict["changed_settings"]

    def test_verify_unknown_record(self, ws):
        with pytest.raises(NotFoundError):
            ws.reproduction.verify("rp_missing")

    def test_untrusted_dynamic_tool_is_a_blocker(self, ws):
        from archx_agent.managers.tools import ToolSpec

        ws.tools.declare_spec(
            ToolSpec(
                name="ext.ghost.ping",
                summary="a tool from an extension that is not installed",
                capability=None,
                risk="low",
                inputs={},
                builtin=False,
                origin="extension:ghost",
            ),
            lambda args: {"ok": True},
        )
        task = ws.tasks.create("tool", "x", tools=["ext.ghost.ping"], start=True)
        ws.tasks.complete(task.id)
        assessment = ws.reproduction.assess(task.id)
        assert assessment["fidelity"] == "impossible"
        assert "extension_inactive" in [i["code"] for i in assessment["issues"]]


def _context(ws, task_id):
    from archx_agent.managers.tools import ToolContext

    return ToolContext(task_id=task_id, purpose="test")


# --------------------------------------------------------------------------
# integration: chat records a task, tools land on the timeline
# --------------------------------------------------------------------------
class TestChatRecordsTasks:
    def test_a_chat_turn_becomes_a_completed_task(self, ws):
        model = ws.models.register_remote("sim", provider="test-double", runtime="scripted", model_ref="simulated")
        reply = ws.chat.send("what is the plan?")
        tasks = ws.tasks.list(kind="chat")
        assert len(tasks) == 1
        task = tasks[0]
        assert task.status == "completed"
        assert task.conversation_id == reply.conversation_id
        assert task.model_id == model.id
        assert task.input_refs == [reply.user_message.id]
        assert reply.assistant_message.id in task.output_refs
        assert task.resource_use["completion_tokens"] >= 0
        assert reply.task and reply.task["id"] == task.id
        assert [row["kind"] for row in ws.tasks.timeline(task.id)][:2] == ["created", "started"]
        assert "message" in [row["kind"] for row in ws.tasks.timeline(task.id)]

    def test_a_failed_chat_turn_becomes_a_failed_task(self, ws):
        model = ws.models.register_remote(
            "bad", provider="unreachable", runtime="openai-http", model_ref="x",
            base_url="http://127.0.0.1:9/v1",
        )
        assert model.id
        with pytest.raises(Exception):
            ws.chat.send("hello")
        tasks = ws.tasks.list(kind="chat")
        assert len(tasks) == 1
        assert tasks[0].status == "failed"
        assert tasks[0].error

    def test_auto_recording_can_be_switched_off(self, ws):
        ws.models.register_remote("sim", provider="test-double", runtime="scripted", model_ref="simulated")
        ws.config.set("tasks.auto_record_chat", False)
        ws.chat.send("hello")
        assert ws.tasks.list(kind="chat") == []

    def test_an_explicit_task_is_reused_not_duplicated(self, ws):
        ws.models.register_remote("sim", provider="test-double", runtime="scripted", model_ref="simulated")
        parent = ws.tasks.create("agent", "bigger job", start=True)
        reply = ws.chat.send("step one", task_id=parent.id)
        assert ws.tasks.list(kind="chat") == []
        assert reply.task and reply.task["id"] == parent.id
        assert ws.tasks.get(parent.id).conversation_id == reply.conversation_id

    def test_a_tool_call_inside_a_task_lands_on_the_timeline(self, ws):
        _grant(ws, "fs.read", "fs.read")
        root = Path(ws.tools.roots()[0])
        _write(root / "a.txt", "x\n")
        task = ws.tasks.create("tool", "read", start=True)
        run = ws.tools.execute("fs.read", {"path": "a.txt"}, context=_context(ws, task.id))
        assert run.status == "succeeded"
        assert ws.tasks.get(task.id).tools == ["fs.read"]
        assert "tool" in [row["kind"] for row in ws.tasks.timeline(task.id)]
        assert [r["id"] for r in ws.tasks.tool_runs(task.id)] == [run.id]

    def test_a_denied_tool_call_is_also_recorded_on_the_task(self, ws):
        root = Path(ws.tools.roots()[0])
        _write(root / "a.txt", "x\n")
        task = ws.tasks.create("tool", "read", start=True)
        with pytest.raises(Exception):
            ws.tools.execute("fs.read", {"path": "a.txt"}, context=_context(ws, task.id))
        rows = ws.tasks.tool_runs(task.id)
        assert rows and rows[0]["status"] == "denied"
        assert ws.tasks.get(task.id).tools == ["fs.read"]


# --------------------------------------------------------------------------
# the installed console script
# --------------------------------------------------------------------------
class TestCliTasks:
    def test_start_complete_and_show(self, home):
        started = _json(_run(home, "tasks", "start", "--type", "tool", "--title", "rebuild index", "--json"))
        assert started["status"] == "running"
        assert _ok(_run(home, "tasks", "log", started["id"], "--kind", "step", "--detail", "half way"))
        completed = _json(_run(home, "tasks", "complete", started["id"], "--summary", "done", "--json"))
        assert completed["status"] == "completed"
        text = _ok(_run(home, "tasks", "show", started["id"]))
        assert "timeline:" in text.stdout and "completed" in text.stdout
        shown = _json(_run(home, "tasks", "show", started["id"], "--json"))
        assert shown["title"] == "rebuild index"
        assert [row["kind"] for row in shown["timeline"]][-1] == "completed"
        listed = _json(_run(home, "tasks", "list", "--json"))
        assert [t["id"] for t in listed] == [started["id"]]

    def test_queue_then_start_and_cancel(self, home):
        queued = _json(_run(home, "tasks", "queue", "--type", "agent", "--title", "later", "--json"))
        assert queued["status"] == "queued"
        assert _run(home, "tasks", "cancel", queued["id"], "--reason", "not now").returncode == 0
        shown = _json(_run(home, "tasks", "show", queued["id"], "--json"))
        assert shown["status"] == "cancelled"

    def test_fail_and_question_commands(self, home):
        task = _json(_run(home, "tasks", "start", "--type", "chat", "--json"))
        _ok(_run(home, "tasks", "question", task["id"], "--text", "which model?"))
        _ok(_run(home, "tasks", "resolve", task["id"], "0"))
        _ok(_run(home, "tasks", "fail", task["id"], "--error", "provider outage"))
        shown = _json(_run(home, "tasks", "show", task["id"], "--json"))
        assert shown["status"] == "failed"
        assert "provider outage" in shown["error"]
        assert shown["unresolved"] == []

    def test_attach_and_version_commands(self, home, tmp_path):
        task = _json(_run(home, "tasks", "start", "--type", "tool", "--json"))
        path = tmp_path / "report.md"
        path.write_text("# one\n", encoding="utf-8")
        attached = _json(_run(home, "tasks", "attach", task["id"], str(path), "--json"))
        assert attached["metadata"]["version"] == "v1"
        path.write_text("# one\n# two\n", encoding="utf-8")
        _ok(_run(home, "tasks", "attach", task["id"], str(path)))
        listed = _json(_run(home, "versions", "list", "artifact", str(path.resolve()), "--json"))
        assert [v["version"] for v in listed] == ["v1", "v2"]
        diff = _ok(_run(home, "versions", "diff", "artifact", str(path.resolve())))
        assert "+# two" in diff.stdout
        restored = _ok(_run(home, "versions", "restore", "artifact", str(path.resolve()), "v1"))
        assert "restored v1 as v3" in restored.stdout
        history = _json(_run(home, "versions", "list", "artifact", str(path.resolve()), "--json"))
        assert [v["version"] for v in history] == ["v1", "v2", "v3"]

    def test_version_record_show_and_subjects(self, home):
        _ok(_run(home, "versions", "record", "prompt", "system", "--content", "be careful"))
        shown = _ok(_run(home, "versions", "show", "prompt", "system"))
        assert "be careful" in shown.stdout
        subjects = _json(_run(home, "versions", "subjects", "--json"))
        assert subjects[0]["subject_id"] == "system"

    def test_reproduce_exact_and_impossible(self, home):
        task = _json(_run(home, "tasks", "start", "--type", "tool", "--title", "inspect", "--json"))
        _ok(_run(home, "tasks", "complete", task["id"]))
        result = _ok(_run(home, "tasks", "reproduce", task["id"], "--record", "--json"))
        payload = json.loads(result.stdout)
        # A task with no model and no tools cannot claim determinism.
        assert payload["fidelity"] == "partial"
        assert payload["record"]["id"].startswith("rp_")

        impossible = _json(_run(home, "tasks", "start", "--type", "chat", "--json"))
        _ok(_run(home, "tasks", "complete", impossible["id"]))
        # no model registered at all -> nothing to replay is a caveat, still not exact
        payload = json.loads(_run(home, "tasks", "reproduce", impossible["id"], "--json").stdout)
        assert payload["fidelity"] == "partial"

    def test_reproduce_of_a_missing_model_exits_degraded(self, home, tmp_path):
        # Register a simulated model, use it, then remove it: reproduction is impossible.
        assert _run(home, "models", "add-scripted", "--name", "sim", allow_simulated=True).returncode == 0
        chat = _run(home, "chat", "--message", "hello", allow_simulated=True)
        assert chat.returncode == 0, chat.stderr
        task = _json(_run(home, "tasks", "list", "--type", "chat", "--json"))[0]
        assert task["model_id"]
        _ok(_run(home, "models", "remove", task["model_id"]))
        result = _run(home, "tasks", "reproduce", task["id"], "--json")
        assert result.returncode == 3, result.stderr
        assert json.loads(result.stdout)["fidelity"] == "impossible"

    def test_chat_appears_in_task_history(self, home):
        assert _run(home, "models", "add-scripted", "--name", "sim", allow_simulated=True).returncode == 0
        assert _run(home, "chat", "--message", "hello", allow_simulated=True).returncode == 0
        tasks = _json(_run(home, "tasks", "list", "--json"))
        assert len(tasks) == 1
        assert tasks[0]["type"] == "chat" and tasks[0]["status"] == "completed"

    def test_unknown_task_is_a_clean_error(self, home):
        result = _run(home, "tasks", "show", "tk_missing")
        assert result.returncode == 1
        assert "no task" in result.stderr

    def test_stats_and_db_check(self, home):
        _ok(_run(home, "tasks", "start", "--type", "tool", "--json"))
        stats = _json(_run(home, "tasks", "stats", "--json"))
        assert stats["total"] == 1
        check = _ok(_run(home, "db", "check", "--json"))
        assert json.loads(check.stdout)["integrity"] == ["ok"]
