"""Durable scheduling is not a permission grant and is not job completion."""
import sys
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.timeutil import parse_iso
from archx_agent.helpers.exceptions import ValidationError


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    with open_workspace(home=str(tmp_path / "home"), overrides={"tools.roots": [str(root)]}) as ws:
        yield ws


def command():
    return [sys.executable, "-c", "print('scheduled')"]


def test_disabled_by_default_and_due_dispatch(ws):
    item = ws.automation.create("repeat", command(), interval=10)
    assert not item["enabled"]
    now = item["next_run_at"]
    assert not ws.automation.tick(now=now)["dispatched"]
    ws.automation.enable(item["id"], True)
    before = (parse_iso(now) - timedelta(seconds=1)).isoformat()
    assert not ws.automation.tick(now=before)["dispatched"]
    result = ws.automation.tick(now=now)
    assert len(result["dispatched"]) == 1
    assert ws.automations.runs()[0]["status"] == "queued"
    assert not ws.automation.tick(now=now)["dispatched"]


def test_once_disables_after_one_job(ws):
    item = ws.automation.create("once", command(), at="2020-01-01T00:00:00Z")
    ws.automation.enable(item["id"], True)
    result = ws.automation.tick()
    assert len(result["dispatched"]) == 1
    assert not ws.automations.get(item["id"])["enabled"]
    assert not ws.automation.tick()["dispatched"]


def test_dispatch_checks_permission_at_execution(ws):
    item = ws.automation.create("once", command(), at="2020-01-01T00:00:00Z")
    ws.automation.enable(item["id"], True)
    job_id = ws.automation.tick()["dispatched"][0]["job_id"]
    job = ws.scheduler.execute(ws.jobs.get(job_id))
    assert job.status == "failed"
    assert ws.automations.runs()[0]["status"] == "failed"


def test_granted_job_really_runs(ws):
    ws.permissions.grant("shell.run", subject="*", duration="persistent", confirm=True)
    item = ws.automation.create("once", command(), at="2020-01-01T00:00:00Z")
    ws.automation.enable(item["id"], True)
    job_id = ws.automation.tick()["dispatched"][0]["job_id"]
    job = ws.scheduler.execute(ws.jobs.get(job_id))
    assert job.status == "completed"
    assert "scheduled" in job.result["stdout"]
    assert ws.automations.runs()[0]["task_id"]


def test_two_ticks_dispatch_one_occurrence(ws):
    item = ws.automation.create("once", command(), at="2020-01-01T00:00:00Z")
    ws.automation.enable(item["id"], True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: ws.automation.tick(), range(2)))
    assert sum(len(r["dispatched"]) for r in results) == 1
    assert len(ws.automations.runs()) == 1


def test_watch_hashes_and_reacts_once(ws):
    path = ws.tools.runtime.resolve("input.txt")
    path.write_text("first")
    ws.permissions.grant("fs.read", subject="*", duration="persistent", confirm=True)
    item = ws.automation.create("watch", command(), watch="input.txt")
    ws.automation.enable(item["id"], True)
    assert not ws.automation.tick()["dispatched"]
    path.write_text("second")
    assert len(ws.automation.tick()["dispatched"]) == 1
    assert not ws.automation.tick()["dispatched"]
    job = ws.jobs.get(ws.automations.runs()[0]["job_id"])
    ws.jobs.cancel(job.id)
    path.write_text("first")
    assert len(ws.automation.tick()["dispatched"]) == 1


@pytest.mark.parametrize("options", [{}, {"interval": 0}, {"interval": True}, {"at": "tomorrow"},
    {"at": "2026-01-01T00:00:00"}, {"interval": 1, "at": "2020-01-01T00:00:00Z"}])
def test_invalid_schedules(ws, options):
    with pytest.raises(ValidationError):
        ws.automation.create("bad", command(), **options)
    assert not ws.automations.list()


def test_duplicate_name(ws):
    ws.automation.create("one", command(), interval=1)
    with pytest.raises(ValidationError):
        ws.automation.create("one", command(), interval=1)


def test_atomic_job_failure_rolls_back_schedule(ws, monkeypatch):
    item = ws.automation.create("once", command(), at="2020-01-01T00:00:00Z")
    ws.automation.enable(item["id"], True)
    before = ws.automations.get(item["id"])
    def broken(tx, payload):
        raise ValidationError("injected queue failure")
    monkeypatch.setattr(ws.jobs, "_apply_enqueue", broken)
    result = ws.automation.tick()
    assert result["refused"]
    assert ws.automations.get(item["id"]) == before
    assert not ws.automations.runs()
