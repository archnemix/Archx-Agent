"""`models probe --capability tools`, end to end.

Before this, the probe could never pass: nothing offered the model a tool, so
`raw["tool_calls"]` was always empty and every probe failed with "tool use is not proven".
The capability was offered in the CLI and never verified - the exact thing this repository is
supposed to refuse to do.

Three cases matter:

* a runtime that *can* call tools, against a server that returns one: the probe passes and the
  capability is recorded as verified;
* a runtime that *cannot* (the scripted double): the probe fails saying so, rather than
  pretending a text reply is a tool call;
* a model that answers in prose while a tool is offered: still a failure, because offering is not
  calling.
"""

from __future__ import annotations

from tests.paths import REPO_ROOT

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from archx_agent.application.workspace import open_workspace

sys.path.insert(0, str(REPO_ROOT / "scripts"))
CLI = str(Path(sys.executable).parent / "archx-agent")


class _Stub(BaseHTTPRequestHandler):
    """OpenAI shape, and a tool call when one is offered. `mode` decides how it answers."""

    protocol_version = "HTTP/1.1"
    mode = "call"      # call | text

    def log_message(self, *args):
        pass

    def _send(self, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        self._send({"object": "list", "data": [{"id": "local", "object": "model"}]})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if not self.path.split("?")[0].endswith("/chat/completions"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if body.get("tools") and self.mode == "call":
            return self._send({
                "id": "x", "object": "chat.completion", "created": 1, "model": "local",
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function",
                                    "function": {"name": "record_value", "arguments": '{"value": 1}'}}]}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 5},
            })
        self._send({
            "id": "x", "object": "chat.completion", "created": 1, "model": "local",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "I would rather talk."}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 4},
        })


@pytest.fixture()
def stub(monkeypatch):
    _Stub.mode = "call"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def ws(tmp_path, monkeypatch, stub):
    monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "1")
    with open_workspace(home=str(tmp_path / "home"), env={"ARCHX_ALLOW_SIMULATED": "1"}) as workspace:
        workspace.providers.add("local-stub", template="openai-compatible-local", base_url=stub)
        workspace.models.register_remote(
            "stub-model",
            provider="local-stub",
            runtime="openai-http",
            model_ref="local",
            base_url=stub,
            context_length=2048,
            capabilities=["chat", "tools"],
            verification="inferred",
        )
        yield workspace


def _model(ws, name: str):
    record = ws.models.by_name(name)
    (record.ok_or_raise())
    return record.value


class TestTheProbe:
    def test_a_tool_call_passes_and_is_recorded_as_verified(self, ws):
        record = _model(ws, "stub-model")
        result = ws.router.probe(record.id, "tools")
        assert result["outcome"] == "passed", result
        assert "called record_value with {\"value\": 1}" in result["detail"]
        capability = ws.models.capability_state(ws.models.require(record.id), "tools")
        assert capability["state"] == "verified", capability
        assert capability["basis"] == "probe passed"

    def test_a_model_that_ignores_the_tool_fails(self, ws):
        _Stub.mode = "text"
        record = _model(ws, "stub-model")
        result = ws.router.probe(record.id, "tools")
        assert result["outcome"] == "failed", result
        assert "without calling the tool" in result["detail"]
        assert ws.models.capability_state(ws.models.require(record.id), "tools")["state"] == "unsupported"

    def test_a_runtime_without_a_tool_path_says_so(self, ws):
        record = ws.models.register_remote(
            "double",
            provider="test-double",
            runtime="scripted",
            model_ref="simulated",
            context_length=8192,
            capabilities=["chat"],
            verification="unverified",
            claims={"simulated": True},
        )
        result = ws.router.probe(record.id, "tools")
        assert result["outcome"] == "failed"
        assert "no tool-calling path" in result["detail"]


class TestTheCli:
    def test_models_probe_capability_tools_passes(self, tmp_path, monkeypatch, stub):
        home = tmp_path / "home"
        env = {
            "ARCHX_PATHS_HOME": str(home),
            "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
            "HOME": str(tmp_path),
        }
        run = lambda *args: subprocess.run(  # noqa: E731 - a two-line helper
            [CLI, *args], capture_output=True, text=True, env=env, timeout=120
        )
        assert run("init").returncode == 0
        assert run("providers", "add", "local-stub", "--template", "openai-compatible-local",
                   "--base-url", stub).returncode == 0
        assert run("models", "add-http", "--name", "stub-model", "--base-url", stub,
                   "--model", "local").returncode == 0
        probe = run("models", "probe", "stub-model", "--capability", "tools")
        assert "chat" not in probe.stdout.splitlines()[0], probe.stdout
        assert "tools: passed" in probe.stdout, probe.stdout + probe.stderr
        assert "state now verified" in probe.stdout, probe.stdout
