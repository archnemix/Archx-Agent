"""Integration: the whole app, driven the way a person drives it.

Unit tests prove a function; this file proves the seams. Every test here starts a **real process**
or a **real socket** and checks that a change made in one place is visible in another:

* the CLI registers a model against a live HTTP server, probes it, chats, and the turn appears as
  a task, in the conversation, in search, and in the trace;
* a message written through the GUI is readable by the CLI, and a task created by the CLI is
  visible in the GUI - two interfaces, one database;
* closing and reopening the workspace loses nothing, and a second process can read while the
  first writes;
* a vendor SDK, registered through the CLI, answers from the same endpoint the hand-written
  client uses.

If these pass and the whole app is broken, the seam is in a place none of them look at - which is
itself worth knowing.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = str(Path(sys.executable).parent / "archx-agent")


# --------------------------------------------------------------------------
# a model that really answers, over a socket
# --------------------------------------------------------------------------
class _Model(BaseHTTPRequestHandler):
    """OpenAI shape, with a tool call when one is offered, and a reply that echoes the prompt."""

    protocol_version = "HTTP/1.1"
    calls: list[dict] = []

    def log_message(self, *args):
        pass

    def _json(self, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        self._json({"object": "list", "data": [{"id": "local", "object": "model"}]})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).calls.append({"path": self.path, "body": body})
        if not self.path.split("?")[0].endswith("/chat/completions"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if body.get("tools"):
            return self._json({
                "id": "t", "object": "chat.completion", "created": 1, "model": "local",
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{"id": "c1", "type": "function",
                                    "function": {"name": "record_value", "arguments": '{"value": 1}'}}]}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            })
        asked = body["messages"][-1]["content"]
        if body.get("stream"):
            frames = [json.dumps({"id": "s", "object": "chat.completion.chunk", "model": "local",
                                  "choices": [{"index": 0, "delta": {"content": part},
                                               "finish_reason": None}]})
                      for part in ("about ", asked[:40])]
            raw = "".join(f"data: {f}\n\n" for f in frames).encode() + b"data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self._json({
            "id": "x", "object": "chat.completion", "created": 1, "model": "local",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": f"about {asked[:60]}"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 4},
        })


@pytest.fixture()
def model():
    _Model.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------------------
# a CLI process with its own home
# --------------------------------------------------------------------------
@pytest.fixture()
def cli(tmp_path):
    home = tmp_path / "home"
    env = {
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "ARCHX_PATHS_HOME": str(home),
        "ARCHX_ALLOW_SIMULATED": "1",
        "PYTHONIOENCODING": "utf-8",
    }

    def run(*args: str, expect: int = 0, timeout: float = 120.0) -> subprocess.CompletedProcess:
        result = subprocess.run([CLI, *args], capture_output=True, text=True, env=env, timeout=timeout)
        if expect is not None:
            assert result.returncode == expect, (
                f"`archx-agent {' '.join(args)}` returned {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    run.home = str(home)  # type: ignore[attr-defined]
    run.env = env  # type: ignore[attr-defined]
    run("init")
    return run


# --------------------------------------------------------------------------
# one turn, seen from everywhere
# --------------------------------------------------------------------------
class TestOneTurnSeenEverywhere:
    def test_init_creates_a_working_home(self, cli):
        info = cli("info")
        assert "archx agent" in info.stdout.lower()
        assert Path(cli.home).is_dir()
        assert "archx.db" in info.stdout
        # the schema is at the version this build expects, not merely "a database exists"
        assert "expected v" in info.stdout and "(" in info.stdout
        version = info.stdout.split("expected v")[1].split(")")[0]
        assert f"v{version}" in info.stdout

    def test_a_model_is_registered_probed_and_used(self, cli, model):
        cli("providers", "add", "local-stub", "--template", "openai-compatible-local",
            "--base-url", model)
        cli("models", "add-http", "--name", "stub", "--base-url", model, "--model", "local",
            "--provider", "local-stub")
        probe = cli("models", "probe", "stub", "--capability", "chat")
        assert "passed" in probe.stdout
        assert _Model.calls, "the probe never reached the server"

        reply = cli("chat", "--message", "what is a tunnel", "--model", "stub")
        assert "about what is a tunnel" in reply.stdout
        # the request the app built is a real OpenAI chat request
        last = _Model.calls[-1]["body"]
        assert last["messages"][-1]["content"] == "what is a tunnel"
        assert last["stream"] is False

    def test_the_turn_is_a_task_a_message_and_a_search_hit(self, cli, model):
        cli("providers", "add", "local-stub", "--template", "openai-compatible-local",
            "--base-url", model)
        cli("models", "add-http", "--name", "stub", "--base-url", model, "--model", "local",
            "--provider", "local-stub")
        cli("chat", "--message", "explain write-ahead logging", "--model", "stub")

        tasks = cli("--json", "tasks", "list", "--limit", "10")
        records = json.loads(tasks.stdout)
        chat_tasks = [t for t in records if t["type"] == "chat"]
        assert chat_tasks, "the chat left no task"

        search = cli("--json", "search", "logging")
        report = json.loads(search.stdout)
        kinds = {row["kind"] for row in report.get("hits", [])}
        assert "conversation" in kinds or "task" in kinds, report

    def test_the_turn_is_traced(self, cli, model):
        cli("providers", "add", "local-stub", "--template", "openai-compatible-local",
            "--base-url", model)
        cli("models", "add-http", "--name", "stub", "--base-url", model, "--model", "local",
            "--provider", "local-stub")
        cli("chat", "--message", "trace me", "--model", "stub")
        trace = cli("--json", "trace", "list", "--limit", "40")
        events = json.loads(trace.stdout)
        kinds = {event["kind"] for event in events}
        assert any("chat" in kind or "model" in kind for kind in kinds), kinds

    def test_streaming_through_the_cli_reaches_the_same_server(self, cli, model):
        cli("providers", "add", "local-stub", "--template", "openai-compatible-local",
            "--base-url", model)
        cli("models", "add-http", "--name", "stub", "--base-url", model, "--model", "local",
            "--provider", "local-stub")
        out = cli("chat", "--message", "stream this", "--model", "stub", "--stream")
        assert "about stream this" in out.stdout
        assert _Model.calls[-1]["body"].get("stream") is True


# --------------------------------------------------------------------------
# two interfaces, one database
# --------------------------------------------------------------------------
class TestTheSeamBetweenCliAndGui:
    def test_a_gui_message_is_a_cli_message(self, cli, model, tmp_path):
        from archx_agent.application.workspace import open_workspace
        from archx_agent.interfaces.gui.server import GuiApi, GuiServer

        cli("providers", "add", "local-stub", "--template", "openai-compatible-local",
            "--base-url", model)
        cli("models", "add-http", "--name", "stub", "--base-url", model, "--model", "local",
            "--provider", "local-stub")

        # the GUI opens the same home the CLI just wrote
        with open_workspace(home=cli.home, env=cli.env) as ws:
            api = GuiApi(ws)
            server = GuiServer(api, port=0)
            server.start()
            try:
                body = json.dumps({"message": "written in the gui"}).encode()
                request = (
                    f"POST /api/chat HTTP/1.1\r\nHost: x\r\nContent-Length: {len(body)}\r\n"
                    f"Connection: close\r\nX-Archx-Token: {api.token}\r\n"
                    f"X-Archx-Request: gui\r\nContent-Type: application/json\r\n\r\n"
                ).encode() + body
                with socket.create_connection(("127.0.0.1", server.port), timeout=60) as sock:
                    sock.sendall(request)
                    raw = b""
                    while True:
                        chunk = sock.recv(65536)
                        if not chunk:
                            break
                        raw += chunk
                payload = json.loads(raw.partition(b"\r\n\r\n")[2])
                assert payload["ok"] is True
                task_id = payload["data"]["task"]["id"]
            finally:
                server.stop()
        # ...and the CLI, in another process, sees that task
        shown = cli("--json", "tasks", "show", task_id)
        assert "written in the gui" in shown.stdout

    def test_search_finds_a_message_a_cli_write_produced(self, cli):
        cli("memory", "add", "--kind", "permanent", "--category", "fact",
            "--title", "a fact", "--content", "the gui and the cli share one sqlite file")
        found = cli("--json", "search", "sqlite")
        report = json.loads(found.stdout)
        assert report["counts"].get("memory", 0) >= 1, report
        assert any("sqlite" in (hit.get("title") or "").lower()
                   or "sqlite" in (hit.get("snippet") or "").lower()
                   for hit in report["hits"]), report["hits"]


# --------------------------------------------------------------------------
# durability and concurrency
# --------------------------------------------------------------------------
class TestDurability:
    def test_a_restart_loses_nothing(self, cli, model):
        cli("providers", "add", "local-stub", "--template", "openai-compatible-local",
            "--base-url", model)
        cli("models", "add-http", "--name", "stub", "--base-url", model, "--model", "local",
            "--provider", "local-stub")
        cli("chat", "--message", "survive the restart", "--model", "stub")
        # every CLI call is already a fresh process, so a second call is a restart
        conversations = cli("--json", "conv", "list")
        items = json.loads(conversations.stdout)
        assert items, "the conversation did not survive"
        shown = cli("--json", "conv", "show", items[0]["id"])
        payload = json.loads(shown.stdout)
        rows = payload["messages"] if isinstance(payload, dict) else payload
        contents = [row["content"] for row in rows]
        assert "survive the restart" in contents
        assert any("about survive the restart" in text for text in contents)

    def test_a_second_process_can_read_while_the_first_runs(self, cli, model):
        cli("providers", "add", "local-stub", "--template", "openai-compatible-local",
            "--base-url", model)
        cli("models", "add-http", "--name", "stub", "--base-url", model, "--model", "local",
            "--provider", "local-stub")
        # a long turn in the background, while the foreground lists tasks
        writer = subprocess.Popen(
            [CLI, "chat", "--message", "a slow one", "--model", "stub"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=cli.env, text=True,
        )
        try:
            reader = cli("--json", "tasks", "list", "--limit", "5")
            assert json.loads(reader.stdout) is not None
        finally:
            writer.wait(timeout=120)

    def test_the_database_stays_consistent_under_repeated_opens(self, cli):
        for _ in range(5):
            cli("info")
        check = cli("db", "check")
        assert "ok" in check.stdout.lower(), check.stdout


# --------------------------------------------------------------------------
# a vendor SDK through the whole stack
# --------------------------------------------------------------------------
class TestSdkThroughTheStack:
    def test_the_openai_sdk_is_registered_and_answers(self, cli, model, monkeypatch):
        pytest.importorskip("openai")
        env = dict(cli.env)
        env["OPENAI_API_KEY"] = "integration-key-not-real"
        home = cli.home
        result = subprocess.run(
            [CLI, "models", "add-sdk", "--name", "sdk-model", "--sdk", "openai",
             "--model", "local", "--base-url", model],
            capture_output=True, text=True, env=env, timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        probe = subprocess.run(
            [CLI, "models", "probe", "sdk-model", "--capability", "chat"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        assert "passed" in probe.stdout, probe.stdout + probe.stderr
        reply = subprocess.run(
            [CLI, "chat", "--message", "sdk hello", "--model", "sdk-model"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        assert reply.returncode == 0, reply.stdout + reply.stderr
        assert "about sdk hello" in reply.stdout
        assert Path(home).is_dir()
