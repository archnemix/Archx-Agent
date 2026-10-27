"""M26: the durable job scheduler (concurrency, hard deadlines, pause/resume).

Built in the order the milestone was built: the queue's data model and refusals, then
claiming (including two workers racing for the same row), then the two real job kinds,
then pause/resume/retry, then crash recovery and deadline reaping, then concurrency and
admission control, then the installed console script.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

from archx_agent.application.agent import RunPaused
from archx_agent.application.scheduler import JobStopped, _truncate
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.managers.jobs import DEFAULT_ESTIMATES, JOB_KINDS, STATUSES, JobManager

CLI = os.path.join(os.path.dirname(sys.executable), "archx-agent")


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "1")
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


@pytest.fixture()
def model(ws):
    return ws.models.register_remote(
        "sim", provider="test-double", runtime="scripted", model_ref="simulated",
        capabilities=["chat"],
    )


def _job(ws, command, *, title=None, **kwargs):
    return ws.jobs.enqueue("command", title, {"command": command}, **kwargs)


def _wait_until(predicate, timeout=20.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition was not met in time")


def _notes(ws, count: int, name: str = "notes"):
    steps = [{"kind": "note", "title": f"step {i}", "text": f"value {i}"} for i in range(1, count + 1)]
    return ws.workflows.create({"name": name, "goal": "demonstrate", "steps": steps})


# --------------------------------------------------------------------------
# the queue
# --------------------------------------------------------------------------
class TestEnqueue:
    def test_a_job_starts_queued_not_done(self, ws):
        job = _job(ws, "echo hi", title="greet")
        assert job.status == "queued"
        assert job.queue_seq == 1
        assert job.title == "greet"
        assert job.attempts == 0 and job.max_attempts == 2
        assert job.timeout_seconds == ws.config.get("scheduler.job_timeout_seconds")
        assert job.resource_estimate == DEFAULT_ESTIMATES["command"]

    def test_unknown_kind_is_refused_with_the_known_ones(self, ws):
        with pytest.raises(ValidationError) as exc:
            ws.jobs.enqueue("teleport", "x", {})
        assert "teleport" in exc.value.message and "command" in exc.value.message

    @pytest.mark.parametrize("priority", [-1, 10, "high", 1.5, True])
    def test_priority_must_be_an_integer_in_range(self, ws, priority):
        with pytest.raises(ValidationError) as exc:
            _job(ws, "echo hi", priority=priority)
        assert "priority" in exc.value.message

    @pytest.mark.parametrize("timeout", [0, -5, 900000])
    def test_timeout_must_be_positive_and_bounded(self, ws, timeout):
        with pytest.raises(ValidationError) as exc:
            _job(ws, "echo hi", timeout=timeout)
        assert "timeout" in exc.value.message

    def test_max_attempts_must_be_positive(self, ws):
        with pytest.raises(ValidationError):
            _job(ws, "echo hi", max_attempts=0)

    def test_resource_estimates_are_validated(self, ws):
        with pytest.raises(ValidationError):
            _job(ws, "echo hi", resource_estimate={"cpu_percent": 0, "memory_mb": 10})
        with pytest.raises(ValidationError):
            _job(ws, "echo hi", resource_estimate={"cpu_percent": 10, "memory_mb": 0})

    def test_queue_sequence_increases_and_is_the_ordering(self, ws):
        first = _job(ws, "echo 1")
        second = _job(ws, "echo 2")
        third = _job(ws, "echo 3")
        assert [first.queue_seq, second.queue_seq, third.queue_seq] == [1, 2, 3]
        assert [job.id for job in ws.jobs.queue()] == [first.id, second.id, third.id]

    def test_priority_orders_the_queue_before_the_sequence(self, ws):
        low = _job(ws, "echo low", priority=1)
        high = _job(ws, "echo high", priority=9)
        mid = _job(ws, "echo mid", priority=5)
        assert [job.id for job in ws.jobs.queue()] == [high.id, mid.id, low.id]

    def test_dedupe_key_returns_the_live_job(self, ws):
        first = _job(ws, "echo once", dedupe_key="nightly")
        again = _job(ws, "echo once", dedupe_key="nightly")
        assert again.id == first.id
        assert ws.jobs.stats()["total"] == 1

    def test_dedupe_key_allows_a_new_job_after_the_first_finished(self, ws):
        first = _job(ws, "echo once", dedupe_key="nightly")
        ws.scheduler.drain()
        second = _job(ws, "echo once", dedupe_key="nightly")
        assert second.id != first.id
        assert ws.jobs.stats()["total"] == 2

    def test_list_filters_and_refuses_an_unknown_status(self, ws):
        _job(ws, "echo 1")
        workflow = _notes(ws, 1, name="wf")
        ws.jobs.enqueue("workflow", None, {"workflow": workflow.id})
        assert len(ws.jobs.list(kind="command")) == 1
        assert len(ws.jobs.list(kind="workflow")) == 1
        assert ws.jobs.list(status="queued")
        with pytest.raises(ValidationError):
            ws.jobs.list(status="running-ish")

    def test_stats_count_by_status_and_kind(self, ws):
        _job(ws, "echo 1")
        _job(ws, "echo 2")
        stats = ws.jobs.stats()
        assert stats["total"] == 2 and stats["queued"] == 2
        assert stats["by_kind"]["command"] == 2

    def test_find_accepts_a_unique_prefix(self, ws):
        job = _job(ws, "echo hi")
        assert ws.jobs.find(job.id[:10]).id == job.id
        assert ws.jobs.find("nope") is None
        with pytest.raises(NotFoundError):
            ws.jobs.get("jb_missing")


# --------------------------------------------------------------------------
# claiming
# --------------------------------------------------------------------------
class TestClaim:
    def test_claim_marks_running_with_pid_worker_and_deadline(self, ws):
        job = _job(ws, "echo hi", timeout=30)
        claimed = ws.jobs.claim(worker="wk_test")
        assert claimed.id == job.id
        assert claimed.status == "running"
        assert claimed.attempts == 1
        assert claimed.worker == "wk_test"
        assert claimed.pid == os.getpid()
        assert claimed.deadline is not None
        assert ws.jobs.get(job.id).status == "running"

    def test_claim_returns_none_when_the_queue_is_empty(self, ws):
        assert ws.jobs.claim() is None

    def test_claim_honours_a_kind_filter(self, ws):
        _job(ws, "echo hi")
        assert ws.jobs.claim(kinds=["workflow"]) is None
        assert ws.jobs.claim(kinds=["command"]).kind == "command"

    def test_a_job_that_does_not_fit_memory_is_left_queued(self, ws):
        big = _job(ws, "echo big", resource_estimate={"cpu_percent": 10, "memory_mb": 4096})
        small = _job(ws, "echo small", resource_estimate={"cpu_percent": 10, "memory_mb": 64})
        claimed = ws.jobs.claim(memory_free=512)
        assert claimed.id == small.id
        assert ws.jobs.get(big.id).status == "queued"

    def test_claim_prefers_priority_over_arrival(self, ws):
        _job(ws, "echo first", priority=1)
        urgent = _job(ws, "echo urgent", priority=9)
        assert ws.jobs.claim().id == urgent.id

    def test_two_workers_never_claim_the_same_job(self, ws):
        jobs = [_job(ws, f"echo {i}") for i in range(24)]
        claimed: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            while True:
                job = ws.jobs.claim(worker="wk_race")
                if job is None:
                    return
                with lock:
                    claimed.append(job.id)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert len(claimed) == len(jobs)
        assert len(set(claimed)) == len(jobs)
        assert ws.jobs.stats()["running"] == len(jobs)


# --------------------------------------------------------------------------
# command jobs
# --------------------------------------------------------------------------
class TestCommandJobs:
    def test_a_successful_command_records_output_and_a_task(self, ws):
        job = _job(ws, "echo hello world", title="greet")
        done = ws.scheduler.execute(job)
        assert done.status == "completed"
        assert done.result["exit_code"] == 0
        assert done.result["stdout"].strip() == "hello world"
        assert done.result["duration_ms"] >= 0
        task = ws.tasks.get(done.task_id)
        assert task.status == "completed"
        assert task.type == "automation"
        kinds = [row["kind"] for row in ws.tasks.timeline(task.id)]
        assert kinds[:3] == ["created", "started", "command_started"]
        assert "command_succeeded" in kinds and kinds[-1] == "completed"

    def test_a_nonzero_exit_fails_the_job_and_its_task(self, ws):
        job = _job(ws, "sh -c 'echo boom >&2; exit 3'")
        done = ws.scheduler.execute(job)
        assert done.status == "failed"
        assert "exited with code 3" in done.error
        assert "boom" in done.error
        assert done.result["stderr"].strip() == "boom"
        assert ws.tasks.get(done.task_id).status == "failed"

    def test_stdout_and_stderr_are_both_captured(self, ws):
        job = _job(ws, "sh -c 'echo out; echo err >&2'")
        done = ws.scheduler.execute(job)
        assert done.status == "completed"
        assert done.result["stdout"].strip() == "out"
        assert done.result["stderr"].strip() == "err"

    def test_a_missing_binary_is_refused_before_spawning(self, ws):
        job = _job(ws, "definitely-not-a-binary --flag")
        done = ws.scheduler.execute(job)
        assert done.status == "failed"
        assert "command not found" in done.error

    def test_an_empty_payload_is_a_validation_failure(self, ws):
        job = ws.jobs.enqueue("command", "nothing", {})
        done = ws.scheduler.execute(job)
        assert done.status == "failed"
        assert "payload.command" in done.error

    def test_an_invalid_working_directory_is_refused(self, ws):
        job = _job(ws, "echo hi", )
        ws.jobs._update(job.id, payload={"command": "echo hi", "cwd": "/nope/not/here"})
        done = ws.scheduler.execute(ws.jobs.get(job.id))
        assert done.status == "failed"
        assert "working directory" in done.error

    def test_environment_overrides_are_passed_to_the_child(self, ws):
        job = ws.jobs.enqueue(
            "command", "env", {"command": "sh -c 'echo $ARCHX_JOB_FLAG'", "env": {"ARCHX_JOB_FLAG": "on"}}
        )
        done = ws.scheduler.execute(job)
        assert done.status == "completed"
        assert done.result["stdout"].strip() == "on"
        assert done.result["env_overrides"] == ["ARCHX_JOB_FLAG"]

    def test_a_hard_deadline_kills_the_child(self, ws):
        job = _job(ws, "sleep 30", timeout=1)
        started = time.time()
        done = ws.scheduler.execute(job)
        elapsed = time.time() - started
        assert done.status == "failed"
        assert "timed out after 1s" in done.error
        assert done.result["timed_out"] is True
        assert elapsed < 8, f"the deadline did not stop the child quickly ({elapsed:.1f}s)"
        assert ws.tasks.get(done.task_id).status == "failed"

    def test_a_running_command_cannot_be_paused(self, ws):
        job = _job(ws, "sleep 5")
        claimed = ws.jobs.claim()
        with pytest.raises(ConflictError) as exc:
            ws.jobs.pause(claimed.id)
        assert "child process" in exc.value.message
        ws.jobs.cancel(claimed.id)
        assert job.id == claimed.id

    def test_cancelling_a_running_command_kills_it_and_marks_the_job(self, ws):
        job = _job(ws, "sleep 30")
        results: list = []
        thread = threading.Thread(target=lambda: results.append(ws.scheduler.drain(concurrency=1)))
        thread.start()
        _wait_until(lambda: ws.jobs.get(job.id).status == "running")
        ws.jobs.cancel(job.id, reason="stop it")
        thread.join(timeout=30)
        assert not thread.is_alive()
        done = ws.jobs.get(job.id)
        assert done.status == "cancelled"
        assert done.cancelled is True
        assert ws.tasks.get(done.task_id).status == "cancelled"

    def test_truncation_is_marked_not_silent(self):
        text, cut = _truncate("x" * 30, limit=10)
        assert cut is True
        assert text.startswith("xxxxxxxxxx")
        assert "truncated 20 character(s)" in text
        assert _truncate("short", limit=10) == ("short", False)


# --------------------------------------------------------------------------
# workflow jobs
# --------------------------------------------------------------------------
class TestWorkflowJobs:
    def test_a_workflow_job_runs_and_links_its_task(self, ws):
        workflow = _notes(ws, 3, name="three-notes")
        job = ws.jobs.enqueue("workflow", "run it", {"workflow": workflow.id})
        done = ws.scheduler.execute(job)
        assert done.status == "completed", done.error
        assert done.result["workflow_id"] == workflow.id
        assert done.result["steps"] == 3
        assert ws.workflows.get(workflow.id).status == "completed"
        assert ws.tasks.get(done.task_id).status == "completed"
        assert len(ws.workflows.steps(workflow.id)) == 3

    def test_a_missing_workflow_fails_the_job(self, ws):
        job = ws.jobs.enqueue("workflow", "bad ref", {"workflow": "wf_missing"})
        done = ws.scheduler.execute(job)
        assert done.status == "failed"
        assert "wf_missing" in done.error

    def test_a_proposed_plan_cannot_run_as_a_job(self, ws):
        workflow = ws.workflows.create(
            {"name": "proposed", "goal": "g", "steps": [{"kind": "note", "text": "x"}]},
            status="proposed",
        )
        job = ws.jobs.enqueue("workflow", "unapproved", {"workflow": workflow.id})
        done = ws.scheduler.execute(job)
        assert done.status == "failed"
        assert "approval required" in done.error
        assert ws.workflows.get(workflow.id).status == "proposed"

    def test_approve_flag_lets_a_proposed_plan_run(self, ws):
        workflow = ws.workflows.create(
            {"name": "proposed", "goal": "g", "steps": [{"kind": "note", "text": "x"}]},
            status="proposed",
        )
        job = ws.jobs.enqueue("workflow", "approved", {"workflow": workflow.id, "approve": True})
        done = ws.scheduler.execute(job)
        assert done.status == "completed", done.error
        assert ws.workflows.get(workflow.id).status == "completed"

    def test_a_refused_tool_fails_the_job_through_the_permission_centre(self, ws):
        root = ws.tool_roots()[0]
        workflow = ws.workflows.create({
            "name": "write", "goal": "g",
            "steps": [{"kind": "tool", "tool": "fs.write",
                       "args": {"path": os.path.join(root, "x.txt"), "content": "y"}}],
        })
        job = ws.jobs.enqueue("workflow", "denied", {"workflow": workflow.id})
        done = ws.scheduler.execute(job)
        assert done.status == "failed"
        assert "approval" in done.error.lower()
        assert not os.path.exists(os.path.join(root, "x.txt"))

    def test_a_pause_request_stops_at_a_step_boundary(self, ws):
        workflow = _notes(ws, 3, name="pausable")
        seen: list[int] = []

        def control(completed: int) -> str | None:
            seen.append(completed)
            return "pause" if completed >= 1 else None

        with pytest.raises(RunPaused) as exc:
            ws.agent.run(workflow.id, control=control)
        assert exc.value.cursor == 1
        assert seen == [0, 1]
        current = ws.workflows.get(workflow.id)
        assert current.status == "running"
        assert ws.tasks.get(current.task_id).status == "running"
        assert [step.status for step in ws.workflows.steps(workflow.id)] == ["succeeded"]

    def test_resume_continues_without_replaying_finished_steps(self, ws):
        workflow = _notes(ws, 3, name="resumable")

        def control(completed: int) -> str | None:
            return "pause" if completed >= 1 else None

        with pytest.raises(RunPaused):
            ws.agent.run(workflow.id, control=control)
        job = ws.jobs.enqueue(
            "workflow", "resume it", {"workflow": workflow.id}, resource_estimate={"cpu_percent": 10, "memory_mb": 64}
        )
        ws.jobs._update(job.id, cursor=1)
        done = ws.scheduler.execute(ws.jobs.get(job.id))
        assert done.status == "completed", done.error
        steps = ws.workflows.steps(workflow.id)
        assert [(step.seq, step.status) for step in steps] == [(1, "succeeded"), (2, "succeeded"), (3, "succeeded")]
        assert ws.workflows.get(workflow.id).status == "completed"
        assert done.result["steps"] == 3

    def test_resume_after_the_first_task_was_swept_uses_a_new_task(self, ws):
        workflow = _notes(ws, 2, name="swept")
        with pytest.raises(RunPaused):
            ws.agent.run(workflow.id, control=lambda completed: "pause" if completed >= 1 else None)
        first_task = ws.tasks.get(ws.workflows.get(workflow.id).task_id)
        ws.tasks.interrupt(first_task.id, "the process died")
        job = ws.jobs.enqueue("workflow", "resume", {"workflow": workflow.id})
        ws.jobs._update(job.id, cursor=1)
        done = ws.scheduler.execute(ws.jobs.get(job.id))
        assert done.status == "completed", done.error
        second_task = ws.tasks.get(done.task_id)
        assert second_task.id != first_task.id
        assert second_task.metadata["resumed_from"] == first_task.id

    def test_a_cancel_request_cancels_the_workflow_not_just_the_job(self, ws):
        ws.permissions.grant("shell.run", subject="shell.run", duration="persistent", confirm=True)
        workflow = ws.workflows.create({
            "name": "cancellable", "goal": "g",
            "steps": [
                {"kind": "tool", "title": "slow", "tool": "shell.run",
                 "args": {"command": "sleep 1"}},
                {"kind": "note", "title": "after", "text": "x"},
            ],
        })
        job = ws.jobs.enqueue("workflow", "cancel me", {"workflow": workflow.id})
        results: list = []
        thread = threading.Thread(target=lambda: results.append(ws.scheduler.drain(concurrency=1)))
        thread.start()
        _wait_until(lambda: ws.jobs.get(job.id).status == "running")
        ws.jobs.cancel(job.id)
        thread.join(timeout=30)
        assert not thread.is_alive()
        done = ws.jobs.get(job.id)
        assert done.status == "cancelled"
        assert ws.workflows.get(workflow.id).status == "cancelled"

    def test_a_job_deadline_fails_a_workflow_between_steps(self, ws):
        workflow = _notes(ws, 40, name="long")
        job = ws.jobs.enqueue(
            "workflow", "deadline", {"workflow": workflow.id}, timeout=1,
            resource_estimate={"cpu_percent": 10, "memory_mb": 64},
        )
        ws.jobs.claim()
        ws.jobs._update(job.id, deadline="2000-01-01T00:00:00.000Z")
        done = ws.scheduler.execute(ws.jobs.get(job.id))
        assert done.status == "failed"
        assert "deadline" in done.error
        assert ws.workflows.get(workflow.id).status == "failed"


# --------------------------------------------------------------------------
# pause / resume / retry
# --------------------------------------------------------------------------
class TestPauseResumeRetry:
    def test_pausing_a_queued_job_is_immediate_and_resume_requeues_it(self, ws):
        job = _job(ws, "echo hi")
        paused = ws.jobs.pause(job.id, reason="later")
        assert paused.status == "paused"
        assert paused.message == "later"
        assert ws.jobs.stats()["paused"] == 1
        assert ws.scheduler.drain() == []  # a paused job is not claimable
        resumed = ws.jobs.resume(job.id)
        assert resumed.status == "queued"
        assert ws.scheduler.drain()[0].status == "completed"

    def test_pausing_twice_is_a_conflict(self, ws):
        job = _job(ws, "echo hi")
        ws.jobs.pause(job.id)
        with pytest.raises(ConflictError):
            ws.jobs.pause(job.id)

    def test_resuming_a_job_that_is_not_paused_is_a_conflict(self, ws):
        job = _job(ws, "echo hi")
        with pytest.raises(ConflictError):
            ws.jobs.resume(job.id)

    def test_a_terminal_job_cannot_be_paused(self, ws):
        job = _job(ws, "echo hi")
        ws.scheduler.drain()
        with pytest.raises(ConflictError):
            ws.jobs.pause(job.id)

    def test_cancelling_a_queued_job_ends_it_immediately(self, ws):
        job = _job(ws, "echo hi")
        cancelled = ws.jobs.cancel(job.id, reason="not needed")
        assert cancelled.status == "cancelled"
        assert cancelled.ended_at and cancelled.error == "not needed"
        assert ws.scheduler.drain() == []
        with pytest.raises(ConflictError):
            ws.jobs.cancel(job.id)

    def test_retry_requeues_a_failed_job(self, ws):
        job = _job(ws, "sh -c 'exit 2'")
        assert ws.scheduler.execute(job).status == "failed"
        retried = ws.jobs.retry(job.id)
        assert retried.status == "queued"
        assert retried.error is None
        assert retried.attempts == 1

    def test_a_completed_job_cannot_be_retried(self, ws):
        job = _job(ws, "echo hi")
        ws.scheduler.drain()
        with pytest.raises(ConflictError) as exc:
            ws.jobs.retry(job.id)
        assert "submit a new job" in exc.value.message

    def test_retry_refuses_when_attempts_are_used_up_unless_forced(self, ws):
        job = _job(ws, "sh -c 'exit 2'", max_attempts=1)
        ws.scheduler.execute(job)
        with pytest.raises(ConflictError) as exc:
            ws.jobs.retry(job.id)
        assert "force" in exc.value.message
        forced = ws.jobs.retry(job.id, force=True)
        assert forced.status == "queued" and forced.max_attempts > forced.attempts

    def test_heartbeat_requires_a_running_job(self, ws):
        job = _job(ws, "echo hi")
        with pytest.raises(ConflictError):
            ws.jobs.heartbeat(job.id, progress=0.5)
        ws.jobs.claim()
        updated = ws.jobs.heartbeat(job.id, progress=0.5, message="halfway")
        assert updated.progress == 0.5 and updated.message == "halfway"


# --------------------------------------------------------------------------
# crash recovery and deadlines
# --------------------------------------------------------------------------
class TestRecovery:
    def test_a_dead_worker_with_attempts_left_is_requeued(self, ws):
        job = _job(ws, "echo hi")
        ws.jobs.claim()
        ws.jobs._update(job.id, pid=999_999, worker="wk_dead")
        result = ws.jobs.recover()
        assert result["requeued"] == 1
        requeued = ws.jobs.get(job.id)
        assert requeued.status == "queued"
        assert requeued.pid is None and requeued.worker is None
        assert requeued.requeued_at is not None
        assert requeued.attempts == 1

    def test_a_dead_worker_without_attempts_left_is_interrupted(self, ws):
        job = _job(ws, "echo hi", max_attempts=1)
        ws.jobs.claim()
        ws.jobs._update(job.id, pid=999_999)
        result = ws.jobs.recover()
        assert result["interrupted"] == 1
        done = ws.jobs.get(job.id)
        assert done.status == "interrupted"
        assert "disappeared" in done.error
        # A claimed-but-never-executed job has not created a task yet.
        assert done.task_id is None

    def test_a_live_worker_is_left_alone(self, ws):
        job = _job(ws, "echo hi")
        ws.jobs.claim()
        result = ws.jobs.recover()
        assert result["skipped"] == 1
        assert ws.jobs.get(job.id).status == "running"

    def test_recover_is_idempotent(self, ws):
        job = _job(ws, "echo hi")
        ws.jobs.claim()
        ws.jobs._update(job.id, pid=999_999)
        ws.jobs.recover()
        second = ws.jobs.recover()
        assert second["requeued"] == 0 and second["interrupted"] == 0

    def test_a_passed_deadline_is_failed_by_any_worker(self, ws):
        job = _job(ws, "sleep 10")
        ws.jobs.claim()
        ws.jobs._update(job.id, deadline="2000-01-01T00:00:00.000Z")
        reaped = ws.jobs.reap_expired()
        assert reaped["expired"] == 1
        done = ws.jobs.get(job.id)
        assert done.status == "failed"
        assert "hard deadline" in done.error
        assert done.ended_at is not None
        assert done.control is None

    def test_reap_leaves_a_future_deadline_alone(self, ws):
        job = _job(ws, "echo hi", timeout=60)
        ws.jobs.claim()
        assert ws.jobs.reap_expired()["expired"] == 0
        assert ws.jobs.get(job.id).status == "running"


# --------------------------------------------------------------------------
# concurrency and admission
# --------------------------------------------------------------------------
class TestConcurrency:
    def test_jobs_run_in_parallel_up_to_the_limit(self, ws):
        ws.config.set("scheduler.max_concurrent_jobs", 4)
        jobs = [_job(ws, "sleep 0.6") for _ in range(4)]
        started = time.time()
        done = ws.scheduler.drain()
        elapsed = time.time() - started
        assert len(done) == 4
        assert all(job.status == "completed" for job in done)
        assert elapsed < 2.0, f"four 0.6s jobs at concurrency 4 took {elapsed:.2f}s"

    def test_serial_baseline_is_respected_when_concurrency_is_one(self, ws):
        jobs = [_job(ws, "sleep 0.3") for _ in range(3)]
        started = time.time()
        ws.scheduler.drain(concurrency=1)
        elapsed = time.time() - started
        assert elapsed >= 0.9
        assert ws.jobs.stats()["by_status"]["completed"] == 3

    def test_the_memory_budget_serialises_heavy_jobs(self, ws):
        ws.config.set("scheduler.memory_limit_mb", 512)
        ws.config.set("scheduler.cpu_limit_percent", 200 if False else 80)
        jobs = [
            _job(ws, "sleep 0.5", resource_estimate={"cpu_percent": 10, "memory_mb": 400})
            for _ in range(2)
        ]
        started = time.time()
        done = ws.scheduler.drain(concurrency=2)
        elapsed = time.time() - started
        assert [job.status for job in done] == ["completed", "completed"]
        assert elapsed >= 1.0, f"both heavy jobs ran at once despite the memory ceiling ({elapsed:.2f}s)"

    def test_max_jobs_stops_the_drain_early(self, ws):
        jobs = [_job(ws, "echo hi") for _ in range(3)]
        done = ws.scheduler.drain(max_jobs=1)
        assert len(done) == 1
        assert ws.jobs.stats()["queued"] == 2

    def test_draining_an_empty_queue_is_a_no_op(self, ws):
        assert ws.scheduler.drain() == []

    def test_a_drain_deadline_stops_claiming_but_finishes_in_flight_work(self, ws):
        jobs = [_job(ws, "sleep 0.4") for _ in range(3)]
        done = ws.scheduler.drain(max_seconds=0.2, concurrency=1)
        assert done, "the job already claimed should still finish"
        assert all(job.status == "completed" for job in done)


# --------------------------------------------------------------------------
# the installed console script
# --------------------------------------------------------------------------
def _cli(home, *args, timeout=180):
    env = dict(os.environ)
    env.pop("ARCHX_PATHS_HOME", None)
    env["ARCHX_ALLOW_SIMULATED"] = "1"
    return subprocess.run(
        [CLI, "--home", home, *args], capture_output=True, text=True, env=env, timeout=timeout
    )


def _home(tmp_path) -> str:
    home = str(tmp_path / "cli-home")
    assert _cli(home, "init").returncode == 0
    return home


class TestCliJobs:
    def test_submit_run_and_inspect(self, tmp_path):
        home = _home(tmp_path)
        submitted = _cli(home, "jobs", "submit", "command", "echo cli-hello", "--title", "greet")
        assert submitted.returncode == 0, submitted.stderr
        assert "queued" in submitted.stdout
        job_id = submitted.stdout.split()[0]
        listed = json.loads(_cli(home, "--json", "jobs", "list").stdout)
        assert listed[0]["id"] == job_id and listed[0]["status"] == "queued"
        queued = json.loads(_cli(home, "--json", "jobs", "queue").stdout)
        assert [row["id"] for row in queued] == [job_id]
        ran = _cli(home, "jobs", "run")
        assert ran.returncode == 0, ran.stderr
        assert "completed" in ran.stdout
        logs = _cli(home, "jobs", "logs", job_id)
        assert "cli-hello" in logs.stdout
        shown = json.loads(_cli(home, "--json", "jobs", "show", job_id).stdout)
        assert shown["status"] == "completed"
        assert shown["task"]["status"] == "completed"
        assert any(row["kind"] == "job_completed" for row in shown["timeline"])

    def test_submit_with_run_drains_immediately(self, tmp_path):
        home = _home(tmp_path)
        result = _cli(home, "jobs", "submit", "command", "echo inline", "--run", "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["submitted"]["status"] == "queued"
        assert payload["ran"][0]["status"] == "completed"

    def test_a_failing_command_exits_one(self, tmp_path):
        home = _home(tmp_path)
        assert _cli(home, "jobs", "submit", "command", "sh -c 'exit 7'").returncode == 0
        result = _cli(home, "jobs", "run")
        assert result.returncode == 1
        job_id = json.loads(_cli(home, "--json", "jobs", "list").stdout)[0]["id"]
        logs = _cli(home, "jobs", "logs", job_id)
        assert "exited with code 7" in logs.stderr

    def test_a_paused_job_left_behind_exits_three(self, tmp_path):
        home = _home(tmp_path)
        running = _cli(home, "jobs", "submit", "command", "echo go").stdout.split()[0]
        paused = _cli(home, "jobs", "submit", "command", "echo later").stdout.split()[0]
        assert _cli(home, "jobs", "pause", paused).returncode == 0
        result = _cli(home, "jobs", "run")
        assert result.returncode == 3, result.stdout + result.stderr
        assert "1 paused" in result.stdout
        assert _cli(home, "jobs", "resume", paused).returncode == 0
        assert _cli(home, "jobs", "run").returncode == 0

    def test_pause_resume_cancel_and_retry(self, tmp_path):
        home = _home(tmp_path)
        job_id = _cli(home, "jobs", "submit", "command", "echo hi").stdout.split()[0]
        assert "paused" in _cli(home, "jobs", "pause", job_id).stdout
        assert "queued" in _cli(home, "jobs", "resume", job_id).stdout
        assert "cancelled" in _cli(home, "jobs", "cancel", job_id, "--reason", "no").stdout
        shown = json.loads(_cli(home, "--json", "jobs", "show", job_id).stdout)
        assert shown["status"] == "cancelled"
        retried = _cli(home, "jobs", "retry", job_id)
        assert retried.returncode == 0
        assert "queued" in retried.stdout

    def test_recover_and_reap_report_what_they_changed(self, tmp_path):
        home = _home(tmp_path)
        recovered = _cli(home, "jobs", "recover", "--json")
        assert recovered.returncode == 0
        assert json.loads(recovered.stdout)["requeued"] == 0
        reaped = _cli(home, "jobs", "reap", "--json")
        assert reaped.returncode == 0
        assert json.loads(reaped.stdout)["expired"] == 0

    def test_stats_and_show_for_an_unknown_job(self, tmp_path):
        home = _home(tmp_path)
        stats = json.loads(_cli(home, "--json", "jobs", "stats").stdout)
        assert stats["total"] == 0
        missing = _cli(home, "jobs", "show", "jb_nope")
        assert missing.returncode == 1
        assert "jb_nope" in missing.stderr

    def test_invalid_payload_json_exits_two(self, tmp_path):
        home = _home(tmp_path)
        result = _cli(home, "jobs", "submit", "command", "echo hi", "--job-json", "{nope")
        assert result.returncode == 2
        assert "not valid JSON" in result.stderr
        not_object = _cli(home, "jobs", "submit", "command", "echo hi", "--job-json", "[1]")
        assert not_object.returncode == 2

    def test_a_workflow_job_through_the_cli(self, tmp_path):
        home = _home(tmp_path)
        definition = {
            "name": "cli-wf", "goal": "g",
            "steps": [{"kind": "note", "text": "a"}, {"kind": "note", "text": "b"}],
        }
        seed = tmp_path / "seed.py"
        seed.write_text(
            "import json, sys\n"
            "from archx_agent.application.workspace import Workspace\n"
            "ws = Workspace.open(home=sys.argv[1], env={}, allow_test_double=True)\n"
            f"wf = ws.workflows.create(json.loads({json.dumps(json.dumps(definition))}))\n"
            "print(wf.id)\n"
            "ws.close()\n"
        )
        env = dict(os.environ)
        env["ARCHX_ALLOW_SIMULATED"] = "1"
        created = subprocess.run([sys.executable, str(seed), home], capture_output=True, text=True, env=env)
        assert created.returncode == 0, created.stderr
        workflow_id = created.stdout.strip().splitlines()[-1]
        submitted = _cli(home, "jobs", "submit", "workflow", workflow_id, "--title", "wf job")
        assert submitted.returncode == 0, submitted.stderr
        job_id = submitted.stdout.split()[0]
        ran = _cli(home, "jobs", "run")
        assert ran.returncode == 0, ran.stderr
        shown = json.loads(_cli(home, "--json", "jobs", "show", job_id).stdout)
        assert shown["status"] == "completed"
        assert shown["workflow"]["status"] == "completed"
        assert [step["status"] for step in shown["steps"]] == ["succeeded", "succeeded"]


# --------------------------------------------------------------------------
# schema + config
# --------------------------------------------------------------------------
class TestSchemaAndConfig:
    def test_the_jobs_table_has_the_worker_columns(self, ws):
        assert ws.store.schema_version() == 17
        columns = {
            row["name"] for row in ws.store.query("PRAGMA table_info(jobs)", ())
        }
        assert {
            "attempts", "max_attempts", "timeout_seconds", "pid", "worker",
            "requeued_at", "control", "cursor", "dedupe_key", "deadline",
        } <= columns

    def test_scheduler_settings_have_safe_defaults(self, ws):
        assert ws.config.get("scheduler.max_concurrent_jobs") == 2
        assert ws.config.get("scheduler.max_attempts") == 2
        assert ws.config.get("scheduler.poll_seconds") == 0.05
        assert ws.config.get("scheduler.recover_on_open") is True
        assert ws.config.get("scheduler.reap_on_open") is True

    def test_a_bad_poll_interval_is_rejected(self, tmp_path):
        from archx_agent.helpers.config import load_config

        with pytest.raises(Exception):
            load_config(home=str(tmp_path / "cfg"), env={}, create=True,
                        overrides={"scheduler.poll_seconds": 0})

    def test_known_kinds_and_statuses_are_stable(self):
        assert JOB_KINDS == ("command", "workflow")
        assert STATUSES == (
            "queued", "running", "paused", "completed", "failed", "cancelled", "interrupted"
        )
        assert isinstance(JobManager.__dict__["tables"], tuple)


# --------------------------------------------------------------------------
# boundaries and edges (mutation-checked by hand: each assertion fails if the
# guard it covers is removed)
# --------------------------------------------------------------------------
class TestEdges:
    def test_a_deadline_only_counts_while_running(self, ws):
        from archx_agent.helpers.timeutil import iso_from_ts

        job = _job(ws, "echo hi")
        past = iso_from_ts(time.time() - 60)
        assert job.expired() is False  # queued: a deadline is meaningless yet
        claimed = ws.jobs.claim()
        assert claimed.expired() is False
        ws.jobs._update(claimed.id, deadline=past)
        assert ws.jobs.get(claimed.id).expired() is True

    def test_attempts_left_never_goes_negative(self, ws):
        job = _job(ws, "echo hi", max_attempts=1)
        ws.jobs._update(job.id, attempts=5)
        assert ws.jobs.get(job.id).attempts_left == 0

    def test_dedupe_ignores_a_finished_job(self, ws):
        first = _job(ws, "echo once", dedupe_key="k")
        ws.scheduler.drain()
        assert ws.jobs.get(first.id).status == "completed"
        second = _job(ws, "echo twice", dedupe_key="k")
        assert second.id != first.id

    def test_dedupe_does_not_reuse_an_interrupted_job(self, ws):
        first = _job(ws, "echo once", dedupe_key="k", max_attempts=1)
        ws.jobs.claim()
        ws.jobs._update(first.id, pid=999_999)
        ws.jobs.recover()
        assert ws.jobs.get(first.id).status == "interrupted"
        second = _job(ws, "echo again", dedupe_key="k")
        assert second.id != first.id

    def test_a_paused_job_is_never_claimed(self, ws):
        job = _job(ws, "echo hi")
        ws.jobs.pause(job.id)
        assert ws.jobs.claim() is None
        assert ws.jobs.get(job.id).status == "paused"

    def test_stop_refuses_any_other_terminal_status(self, ws):
        job = _job(ws, "echo hi")
        ws.jobs.claim()
        with pytest.raises(ValidationError):
            ws.jobs.stop(job.id, status="completed")
        assert ws.jobs.get(job.id).status == "running"

    def test_link_task_points_the_job_at_a_task(self, ws):
        job = _job(ws, "echo hi")
        task = ws.tasks.create("system", "manual", start=True, manual=True)
        linked = ws.jobs.link_task(job.id, task.id)
        assert linked.task_id == task.id
        assert ws.jobs.get(job.id).task_id == task.id

    def test_command_output_is_truncated_and_flagged(self, ws):
        ws.config.set("tools.max_output_bytes", 4096)
        job = _job(ws, "sh -c 'head -c 9000 /dev/zero | tr \\0 x'")
        done = ws.scheduler.execute(job)
        assert done.status == "completed"
        assert done.result["truncated"] is True
        assert "truncated" in done.result["stdout"]

    def test_a_stopped_runner_claims_nothing_more(self, ws):
        _job(ws, "echo one")
        _job(ws, "echo two")
        ws.scheduler.stop()
        assert ws.scheduler.drain() == []
        assert ws.jobs.stats()["queued"] == 2

    def test_a_run_report_serialises(self):
        from archx_agent.application.scheduler import JobRun

        report = JobRun(job_id="jb_1", kind="command", status="completed", result={"a": 1})
        assert report.to_dict() == {
            "job_id": "jb_1", "kind": "command", "status": "completed",
            "result": {"a": 1}, "error": None, "cursor": 0,
        }

    def test_job_stopped_carries_its_reason_and_cursor(self):
        stop = JobStopped("pause", message="paused", cursor=3)
        assert (stop.reason, stop.cursor, stop.message) == ("pause", 3, "paused")


class TestPausedTaskProtection:
    def test_protected_task_ids_names_paused_jobs_and_resumed_ones(self, ws):
        queued = _job(ws, "echo 1")
        paused = _job(ws, "echo 2")
        task = ws.tasks.create("system", "owned", start=True, manual=True)
        ws.jobs.link_task(paused.id, task.id)
        ws.jobs.pause(paused.id)
        assert ws.jobs.protected_task_ids() == {task.id}
        # A job that already ran once and is waiting again also owns its task.
        resumed = _job(ws, "echo 3")
        ws.jobs.link_task(resumed.id, task.id)
        ws.jobs._update(resumed.id, attempts=1)
        assert ws.jobs.protected_task_ids() == {task.id}
        assert queued.id not in ws.jobs.protected_task_ids()

    def test_a_task_a_paused_job_will_continue_is_not_swept(self, ws):
        workflow = _notes(ws, 2, name="protected")
        with pytest.raises(RunPaused):
            ws.agent.run(workflow.id, control=lambda done: "pause" if done >= 1 else None)
        task_id = ws.workflows.get(workflow.id).task_id
        job = ws.jobs.enqueue("workflow", "protect", {"workflow": workflow.id})
        ws.jobs.link_task(job.id, task_id)
        ws.jobs.pause(job.id)
        swept = ws.tasks.interrupt_stale(protect=ws.jobs.protected_task_ids())
        assert task_id in swept["skipped"]
        assert ws.tasks.get(task_id).status == "running"

    def test_without_protection_the_same_task_is_interrupted(self, ws):
        workflow = _notes(ws, 2, name="unprotected")
        with pytest.raises(RunPaused):
            ws.agent.run(workflow.id, control=lambda done: "pause" if done >= 1 else None)
        task_id = ws.workflows.get(workflow.id).task_id
        swept = ws.tasks.interrupt_stale()
        assert task_id in swept["ids"]
        assert ws.tasks.get(task_id).status == "interrupted"
