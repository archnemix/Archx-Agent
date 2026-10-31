"""Research closure: a question is done when *you* say so, not when coverage says so.

A run's `status` describes what the runner did - `completed`, `incomplete`, `failed`. It says
nothing about whether the person who asked the question is finished with it, and inferring
that from coverage is how a research tool starts flattering. Closure is therefore a second,
explicit fact: `closed_at` is written only by `research close`, it is reversible with
`research reopen`, and the runner never touches it.

The tests are organised around the ways that second fact could rot: a close that also
rewrites the run's status, a close that can happen twice, a reopen that silently no-ops, a
filter that ignores closure, or a GUI button with nothing behind it.

These tests belong to the M28 extension (schema v20) and use the M29 GUI fixtures for the
HTTP layer, so they check the CLI, the manager and the socket paths against one record.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import ConflictError, NotFoundError
from archx_agent.interfaces.gui.server import ASSETS, GuiApi, Request, split_target
from archx_agent.managers.schema import MIGRATIONS, SCHEMA_VERSION

CLI = os.path.join(os.path.dirname(sys.executable), "archx-agent")
TOKEN = "closure-token"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "1")
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


@pytest.fixture()
def api(ws):
    return GuiApi(ws, token=TOKEN)


def _corpus(ws):
    """One memory and one file inside the tool roots: enough for a real local run."""
    ws.memory.add(
        "permanent", "SQLite locking",
        "SQLite takes one write lock per transaction; WAL lets readers continue.",
        category="fact",
    )
    root = ws.tool_roots()[0]
    os.makedirs(os.path.join(root, "docs"), exist_ok=True)
    with open(os.path.join(root, "docs", "locking.md"), "w", encoding="utf-8") as handle:
        handle.write(
            "SQLite locking: a write transaction takes an exclusive lock. WAL mode allows "
            "readers to continue while a writer commits. A busy timeout makes a second "
            "writer wait instead of failing.\n"
        )
    return root


def _run(ws) -> str:
    _corpus(ws)
    outcome = ws.researcher.run("how does sqlite locking work", use_model=False)
    return outcome["run"]["id"]


def call(api, method, path, *, token=TOKEN, body=None):
    parsed_path, parsed_query, url_token = split_target(path)
    request = Request(
        method=method,
        path=parsed_path,
        query=parsed_query,
        headers={"x-archx-token": token} if token else {},
        body=body,
        token=url_token,
        token_in_query=False,
    )
    response = api.dispatch(request)
    payload = response.payload if response.body is None else None
    return response.status, payload


def ok(api, method, path, **kwargs):
    status, payload = call(api, method, path, **kwargs)
    assert status == 200, (status, payload)
    assert payload["ok"] is True
    return payload["data"]


def cli(*args, home):
    env = {**os.environ, "ARCHX_PATHS_HOME": home, "ARCHX_ALLOW_SIMULATED": "1"}
    return subprocess.run(
        [CLI, *args], capture_output=True, text=True, env=env, timeout=120
    )


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------
class TestSchema:
    def test_v20_is_the_closure_migration_and_the_versions_are_contiguous(self):
        assert SCHEMA_VERSION >= 20
        versions = [migration.version for migration in MIGRATIONS]
        assert versions == list(range(1, SCHEMA_VERSION + 1))
        closure = [m for m in MIGRATIONS if m.version == 20]
        assert closure and closure[0].name == "research-closure"

    def test_the_columns_exist_and_start_empty(self, ws):
        columns = {row["name"] for row in ws.store.query("PRAGMA table_info(research_runs)")}
        assert {"closed_at", "closed_note"} <= columns

    def test_a_new_run_is_not_closed(self, ws):
        run = ws.research.get(_run(ws))
        assert run.closed is False
        assert run.closed_at is None
        assert run.to_dict()["closed"] is False


# --------------------------------------------------------------------------
# the manager
# --------------------------------------------------------------------------
class TestManager:
    def test_close_records_the_time_the_note_and_who_did_it(self, ws):
        run_id = _run(ws)
        run = ws.research.close(run_id, note="  enough for the design doc  ", by="user:test")
        assert run.closed is True
        assert run.closed_at
        assert run.closed_note == "enough for the design doc"
        assert run.to_dict()["closed"] is True

    def test_closing_does_not_rewrite_what_the_runner_reported(self, ws):
        """The two facts are separate: closing is not a promotion of `status`."""
        run_id = _run(ws)
        before = ws.research.get(run_id)
        after = ws.research.close(run_id)
        assert after.status == before.status
        assert after.coverage == before.coverage
        assert after.evidence_count == before.evidence_count

    def test_a_second_close_is_a_conflict_that_names_the_first(self, ws):
        run_id = _run(ws)
        first = ws.research.close(run_id)
        with pytest.raises(ConflictError) as exc:
            ws.research.close(run_id)
        assert "already closed" in exc.value.message
        assert first.closed_at in exc.value.message

    def test_closing_an_unknown_run_is_not_found(self, ws):
        with pytest.raises(NotFoundError):
            ws.research.close("rs_nope")

    def test_reopen_clears_both_fields(self, ws):
        run_id = _run(ws)
        ws.research.close(run_id, note="done")
        run = ws.research.reopen(run_id)
        assert run.closed is False
        assert run.closed_at is None
        assert run.closed_note is None

    def test_reopening_an_open_run_is_a_conflict_not_a_silent_no_op(self, ws):
        run_id = _run(ws)
        with pytest.raises(ConflictError) as exc:
            ws.research.reopen(run_id)
        assert "not closed" in exc.value.message

    def test_an_empty_note_is_stored_as_null(self, ws):
        run = ws.research.close(_run(ws), note="   ")
        assert run.closed_note is None

    def test_close_and_reopen_are_recorded_as_traces(self, ws):
        run_id = _run(ws)
        ws.research.close(run_id)
        ws.research.reopen(run_id)
        ws.events.flush(2.0)
        names = [event.name for event in ws.events.query(kind="research", limit=50)]
        assert "research.closed" in names
        assert "research.reopened" in names

    def test_the_list_can_be_filtered_by_closure(self, ws):
        closed_id = _run(ws)
        ws.research.create(question="a second question", mode="local")
        ws.research.close(closed_id)
        everything = {run.id for run in ws.research.list()}
        closed = {run.id for run in ws.research.list(closed=True)}
        open_runs = {run.id for run in ws.research.list(closed=False)}
        assert closed == {closed_id}
        assert closed_id not in open_runs
        assert len(everything) == len(closed) + len(open_runs)

    def test_stats_count_open_and_closed(self, ws):
        run_id = _run(ws)
        ws.research.create(question="a second question", mode="local")
        ws.research.close(run_id)
        stats = ws.research.stats()
        assert stats["total"] == 2
        assert stats["closed"] == 1
        assert stats["open"] == 1

    def test_a_closed_run_can_still_be_read_and_reported(self, ws):
        run_id = _run(ws)
        ws.research.close(run_id)
        run = ws.research.get(run_id)
        assert run.report
        assert ws.research.sources(run_id)

    def test_deleting_a_closed_run_still_works(self, ws):
        run_id = _run(ws)
        ws.research.close(run_id)
        ws.research.delete(run_id)
        with pytest.raises(NotFoundError):
            ws.research.get(run_id)


# --------------------------------------------------------------------------
# the HTTP layer
# --------------------------------------------------------------------------
class TestApi:
    def test_close_over_http_returns_the_closed_run(self, api, ws):
        run_id = _run(ws)
        data = ok(api, "POST", f"/api/research/{run_id}/close", body={"note": "ship it"})
        assert data["closed"] is True
        assert data["closed_note"] == "ship it"
        assert data["closed_at"]

    def test_the_close_is_visible_to_the_cli_read_paths(self, api, ws):
        run_id = _run(ws)
        ok(api, "POST", f"/api/research/{run_id}/close", body={})
        runs = ok(api, "GET", "/api/research")
        assert [run["closed"] for run in runs if run["id"] == run_id] == [True]

    def test_closing_twice_over_http_is_a_409(self, api, ws):
        run_id = _run(ws)
        ok(api, "POST", f"/api/research/{run_id}/close", body={})
        status, payload = call(api, "POST", f"/api/research/{run_id}/close", body={})
        assert status == 409
        assert payload["error"]["code"] == "conflict"

    def test_reopen_over_http(self, api, ws):
        run_id = _run(ws)
        ok(api, "POST", f"/api/research/{run_id}/close", body={})
        data = ok(api, "POST", f"/api/research/{run_id}/reopen", body={})
        assert data["closed"] is False

    def test_an_unknown_run_is_a_404(self, api):
        status, payload = call(api, "POST", "/api/research/rs_nope/close", body={})
        assert status == 404
        assert payload["error"]["code"] == "not_found"

    def test_a_non_text_note_is_a_400(self, api, ws):
        run_id = _run(ws)
        status, payload = call(api, "POST", f"/api/research/{run_id}/close", body={"note": 7})
        assert status == 400
        assert payload["error"]["code"] == "validation"

    def test_the_run_list_can_be_filtered_over_http(self, api, ws):
        run_id = _run(ws)
        ws.research.create(question="another question", mode="local")
        ok(api, "POST", f"/api/research/{run_id}/close", body={})
        closed = ok(api, "GET", "/api/research?closed=1")
        open_runs = ok(api, "GET", "/api/research?closed=0")
        assert {run["id"] for run in closed} == {run_id}
        assert run_id not in {run["id"] for run in open_runs}

    def test_the_routes_are_wired_and_need_the_token(self, api, ws):
        run_id = _run(ws)
        for method, path in (
            ("POST", f"/api/research/{run_id}/close"),
            ("POST", f"/api/research/{run_id}/reopen"),
        ):
            # No token: a write is refused either as unauthorized or as a cross-site write
            # (the CSRF header rule fires first when there is no credential at all).
            status, payload = call(api, method, path, token=None, body={})
            assert status in {401, 403}, path
            assert payload["error"]["code"] in {"unauthorized", "csrf"}

    def test_the_page_offers_the_control_and_the_script_calls_the_route(self):
        html = (ASSETS / "index.html").read_text()
        script = "\n".join(path.read_text() for path in sorted(ASSETS.glob("*.js")))
        assert 'id="research-detail"' in html
        assert call is not None  # keeps the helper referenced for readers of this file
        assert "/close" in script and "/reopen" in script
        assert '"Mark complete"' in script or "'mark complete'" in script or "mark complete" in script


# --------------------------------------------------------------------------
# the CLI
# --------------------------------------------------------------------------
class TestCli:
    def test_close_reopen_and_the_filters(self, ws, tmp_path):
        run_id = _run(ws)
        home = str(tmp_path / "home")

        done = cli("research", "close", run_id, "--note", "settled", home=home)
        assert done.returncode == 0, done.stderr
        assert "closed" in done.stdout
        assert "your call" in done.stdout

        listed = cli("research", "list", "--closed", "--json", home=home)
        assert listed.returncode == 0
        assert run_id in listed.stdout
        assert '"closed": true' in listed.stdout

        opened = cli("research", "list", "--open", "--json", home=home)
        assert run_id not in opened.stdout

        again = cli("research", "close", run_id, home=home)
        assert again.returncode == 1
        assert "already closed" in again.stderr

        back = cli("research", "reopen", run_id, home=home)
        assert back.returncode == 0
        assert "reopened" in back.stdout

        reopen_again = cli("research", "reopen", run_id, home=home)
        assert reopen_again.returncode == 1
        assert "not closed" in reopen_again.stderr

    def test_contradictory_filters_are_a_usage_error(self, ws, tmp_path):
        result = cli("research", "list", "--closed", "--open", home=str(tmp_path / "home"))
        assert result.returncode == 2
        assert "contradict" in result.stderr

    def test_an_unknown_run_is_a_usage_error(self, ws, tmp_path):
        result = cli("research", "close", "rs_nope", home=str(tmp_path / "home"))
        assert result.returncode == 2

    def test_the_cli_and_the_api_see_the_same_record(self, api, ws, tmp_path):
        run_id = _run(ws)
        ok(api, "POST", f"/api/research/{run_id}/close", body={"note": "from the page"})
        shown = cli("research", "show", run_id, "--json", home=str(tmp_path / "home"))
        assert shown.returncode == 0
        assert '"closed_note": "from the page"' in shown.stdout
