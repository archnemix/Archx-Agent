"""Shared fixtures. Collected architecture guards live in test_architecture.py."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from archx_agent.helpers.config import load_config  # noqa: E402
from archx_agent.helpers.events import EventStore  # noqa: E402
from archx_agent.helpers.redaction import clear_registered_secrets  # noqa: E402
from archx_agent.helpers.sqlite_store import SqliteStore  # noqa: E402
from archx_agent.helpers.write_coordinator import WriteCoordinator  # noqa: E402

@pytest.fixture()
def archx_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    cfg = load_config(home=home, env={}, create=True)
    return cfg


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture()
def coordinator(store):
    co = WriteCoordinator(store, name="test")
    yield co
    co.stop()


@pytest.fixture()
def events(tmp_path):
    es = EventStore(tmp_path / "events.db", capture_level="diagnostic")
    yield es
    es.close()


@pytest.fixture(autouse=True)
def _clean_secrets():
    clear_registered_secrets()
    yield
    clear_registered_secrets()


# --------------------------------------------------------------------------
# a real local HTTP server that can behave like a provider
# --------------------------------------------------------------------------
class StubHandler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, dict]] = {}

    def do_GET(self):  # noqa: N802
        self._respond("GET", {})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._respond("POST", body)

    def _respond(self, method: str, body: dict) -> None:
        key = f"{method} {self.path}"
        status, payload = self.routes.get(key, (404, {"error": {"message": "no such route"}}))
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):  # silence
        pass


@pytest.fixture()
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    StubHandler.routes = {}
    yield f"http://127.0.0.1:{server.server_port}", StubHandler
    server.shutdown()
    server.server_close()


@pytest.fixture()
def secret_env(monkeypatch):
    def _set(value: str = "super-secret-value-1234567890") -> str:
        monkeypatch.setenv("ARCHX_TEST_SECRET", value)
        return value

    return _set


@pytest.fixture()
def domain(tmp_path, events):
    """A composed domain workspace (no environment access)."""
    from archx_agent.managers.conversation import ConversationManager
    from archx_agent.managers.memory import MemoryManager
    from archx_agent.managers.projects import ProjectManager
    from archx_agent.managers.schema import MIGRATIONS

    path = tmp_path / "domain.db"
    st = SqliteStore(path)
    st.migrate(MIGRATIONS)
    co = WriteCoordinator(st, name="domain")

    class Domain:
        pass

    d = Domain()
    d.store = st
    d.coordinator = co
    d.events = events
    d.path = path
    d.artifacts = tmp_path / "artifacts"
    d.conversations = ConversationManager(st, co, events=events)
    d.projects = ProjectManager(st, co, events=events, projects_root=str(tmp_path / "projects"))
    d.memory = MemoryManager(st, co, events=events, artifacts_root=str(d.artifacts))
    yield d
    co.stop()
    st.close()
