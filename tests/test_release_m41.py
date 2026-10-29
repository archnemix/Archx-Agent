"""Release-hardening regressions: framing, bounded decoding, noisy processes and queue permissions."""
import base64
import socket
import sys
import tomllib
from pathlib import Path

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.interfaces.gui.server import GuiApi, GuiServer


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    with open_workspace(home=str(tmp_path / "home"), overrides={"tools.roots": [str(root)]}) as ws:
        yield ws


@pytest.mark.parametrize("length", ["-1", "garbage", "+1", "1.5"])
def test_bad_content_length_is_rejected_without_waiting_for_body(ws, length):
    with GuiServer(GuiApi(ws, token="test")) as server:
        with socket.create_connection(("127.0.0.1", server.port), timeout=2) as sock:
            sock.sendall(("POST /api/scenes HTTP/1.0\r\nHost: localhost\r\nContent-Length: " + length + "\r\n\r\n").encode())
            assert b"400" in sock.recv(1024).split(b"\r\n")[0]


def test_large_stdout_does_not_deadlock_command_job(ws):
    job = ws.jobs.enqueue("command", "noisy", {"command": [sys.executable, "-c", "import sys; sys.stdout.write('x'*1000000); sys.stderr.write('y'*1000000)"]}, timeout=5)
    result = ws.scheduler.execute(job)
    assert result.status == "completed", result.error
    assert result.result["truncated"]
    assert len(result.result["stdout"]) < 21000
    assert len(result.result["stderr"]) < 21000


def test_oversized_base64_is_refused_before_decode(ws, monkeypatch):
    ws.permissions.grant("fs.write", subject="*", duration="persistent", confirm=True)
    runtime = ws.tools.runtime
    monkeypatch.setattr(runtime, "max_file_bytes", 4)
    monkeypatch.setattr(base64, "b64decode", lambda *a, **k: pytest.fail("must reject before allocation"))
    from archx_agent.helpers.exceptions import ToolValidationError
    with pytest.raises(ToolValidationError):
        ws.tools.execute("fs.write_bytes", {"path": "large.bin", "content_base64": "A" * 100})
    assert not runtime.resolve("large.bin").exists()


def test_revoke_after_enqueue_prevents_scheduled_command(ws):
    grant = ws.permissions.grant("shell.run", subject="*", duration="persistent", confirm=True)
    au = ws.automation.create("once", [sys.executable, "-c", "from pathlib import Path; Path('forbidden').write_text('bad')"], at="2020-01-01T00:00:00Z")
    ws.automation.enable(au["id"], True)
    job_id = ws.automation.tick()["dispatched"][0]["job_id"]
    ws.permissions.revoke(grant.id)
    job = ws.scheduler.execute(ws.jobs.get(job_id))
    assert job.status == "failed"
    assert ws.tasks.get(job.task_id).status == "failed"
    assert not ws.tools.runtime.resolve("forbidden").exists()


def test_distribution_declares_gui_assets():
    config = tomllib.loads(Path("pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]["archx_agent.interfaces.gui"]
    assert {"assets/*.html", "assets/*.css", "assets/*.js"} <= set(patterns)
