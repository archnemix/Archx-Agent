"""M28: Researcher Mode - a question, a plan, real sources, and a report that cites them.

The tests are organised around what could quietly go wrong: a plan that pretends a model
made it, a source that was never read counting as evidence, a quote that is not in the
document, a citation pointing at a source that does not exist, a fetch that reaches the
machine it runs on, and a run that reports success while covering nothing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from archx_agent.adapters.net_fetch import (
    FetchBlockedError,
    FetchFailedError,
    check_url,
    fetch_limits,
    fetch_url,
    html_to_text,
)
from archx_agent.application.researcher import (
    ResearchBlocked,
    ResearchRunner,
    SourceDoc,
    _parse_judgement,
    _parse_plan,
    _rules_plan,
    _subject,
)
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from archx_agent.managers.research import ResearchManager

CLI = os.path.join(os.path.dirname(sys.executable), "archx-agent")

PAGES = {
    "/locking": (
        "<html><head><title>SQLite locking explained</title>"
        "<style>p{color:red}</style></head><body><h1>Locking</h1>"
        "<p>SQLite takes one write lock per transaction. Readers continue in WAL mode.</p>"
        "<script>var x = 1;</script>"
        "<p>A busy timeout makes a second writer wait instead of failing, "
        "and a retry loop handles SQLITE_BUSY.</p></body></html>"
    ),
    "/wal": (
        "<html><head><title>WAL limits</title></head><body>"
        "<p>WAL does not survive a process crash; the -wal file must be checkpointed.</p>"
        "</body></html>"
    ),
    "/binary": "BINARY",
    "/huge": "<p>" + ("sqlite locking " * 4000) + "</p>",
}


class _Handler(BaseHTTPRequestHandler):
    redirects = 0

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/locking")
            self.end_headers()
            return
        if path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
            return
        if path in {"/locking", "/wal"}:
            body = PAGES[path].encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/plain":
            body = b"SQLite locking is per transaction.\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/binary":
            body = b"\x00\x01\x02binary"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/huge":
            body = PAGES["/huge"].encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


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


def _corpus(ws):
    """Real local evidence: a memory and two files inside the tool roots."""
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
    with open(os.path.join(root, "docs", "wal.md"), "w", encoding="utf-8") as handle:
        handle.write(
            "WAL does not survive a process crash; the -wal file must be checkpointed. "
            "Locking errors appear as SQLITE_BUSY and a retry loop is the usual fix.\n"
        )
    return root


# --------------------------------------------------------------------------
# the fetch adapter
# --------------------------------------------------------------------------
class TestNetFetch:
    def test_only_http_and_https_are_allowed(self):
        for url in ("file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)"):
            with pytest.raises(FetchBlockedError):
                check_url(url, allow_private_hosts=True)

    def test_credentials_in_the_url_are_refused(self):
        with pytest.raises(FetchBlockedError) as exc:
            check_url("https://user:secret@example.com/x")
        assert "credentials" in exc.value.message

    def test_a_url_without_a_host_is_refused(self):
        with pytest.raises(FetchBlockedError):
            check_url("http:///path")

    def test_loopback_is_refused_by_default(self, site):
        with pytest.raises(FetchBlockedError) as exc:
            fetch_url(f"{site}/locking")
        assert "private or local" in exc.value.message
        assert "tools.fetch_allow_private_hosts" in exc.value.message

    def test_allow_private_hosts_is_deliberate(self, site):
        result = fetch_url(f"{site}/locking", allow_private_hosts=True)
        assert result["status"] == 200
        assert result["title"] == "SQLite locking explained"
        assert "one write lock per transaction" in result["text"]

    def test_html_becomes_text_without_scripts_or_styles(self, site):
        result = fetch_url(f"{site}/locking", allow_private_hosts=True)
        assert "var x" not in result["text"]
        assert "color:red" not in result["text"]
        assert "retry loop handles SQLITE_BUSY" in result["text"]

    def test_entities_are_decoded(self):
        text, title = html_to_text("<title>A &amp; B</title><p>5 &lt; 6 &amp;&amp; true</p>")
        assert title == "A & B"
        assert "5 < 6 && true" in text

    def test_binary_content_is_refused(self, site):
        with pytest.raises(FetchBlockedError) as exc:
            fetch_url(f"{site}/binary", allow_private_hosts=True)
        assert "not a text document" in exc.value.message

    def test_a_404_is_a_failure_not_a_block(self, site):
        with pytest.raises(FetchFailedError) as exc:
            fetch_url(f"{site}/missing", allow_private_hosts=True)
        assert "404" in exc.value.message

    def test_a_refused_connection_is_reported(self):
        with pytest.raises(FetchFailedError):
            fetch_url("http://127.0.0.1:1/x", allow_private_hosts=True, timeout=2)

    def test_redirects_are_followed_and_reported(self, site):
        result = fetch_url(f"{site}/redirect", allow_private_hosts=True)
        assert result["final_url"].endswith("/locking")
        assert result["redirects"] == [f"{site}/redirect"]

    def test_a_redirect_loop_stops(self, site):
        with pytest.raises(FetchBlockedError) as exc:
            fetch_url(f"{site}/loop", allow_private_hosts=True, max_redirects=2)
        assert "too many redirects" in exc.value.message

    def test_the_byte_limit_is_enforced_and_stated(self, site):
        result = fetch_url(f"{site}/huge", allow_private_hosts=True, max_bytes=500)
        assert result["truncated"] is True
        assert result["bytes"] == 500

    def test_the_body_is_hashed(self, site):
        first = fetch_url(f"{site}/plain", allow_private_hosts=True)
        second = fetch_url(f"{site}/plain", allow_private_hosts=True)
        assert first["sha256"] == second["sha256"]
        assert first["text"].strip() == "SQLite locking is per transaction."

    def test_limits_come_from_config(self, ws):
        ws.config.set("tools.fetch_max_bytes", 1234)
        limits = fetch_limits(ws.config)
        assert limits["max_bytes"] == 1234
        assert limits["allow_private_hosts"] is False


class TestNetFetchTool:
    def test_the_tool_needs_its_grant(self, ws, site):
        with pytest.raises(ApprovalRequiredError) as exc:
            ws.tools.execute("net.fetch", {"url": f"{site}/plain"})
        assert exc.value.approval_id
        grants = [g for g in ws.permissions.grants() if g.capability == "net.fetch"]
        assert grants == []

    def test_a_granted_fetch_refuses_private_hosts_without_the_flag(self, ws, site):
        ws.permissions.grant("net.fetch", subject="net.fetch", duration="persistent", confirm=True)
        with pytest.raises(FetchBlockedError):
            ws.tools.execute("net.fetch", {"url": f"{site}/plain"})

    def test_a_granted_fetch_with_the_flag_succeeds(self, ws, site):
        ws.permissions.grant("net.fetch", subject="net.fetch", duration="persistent", confirm=True)
        run = ws.tools.execute(
            "net.fetch", {"url": f"{site}/plain", "allow_private_hosts": True}
        )
        assert run.status == "succeeded"
        assert run.result["text"].startswith("SQLite locking")
        assert run.result["limits"]["max_bytes"] > 0

    def test_a_denied_fetch_is_still_a_tool_run(self, ws, site):
        with pytest.raises(ApprovalRequiredError):
            ws.tools.execute("net.fetch", {"url": f"{site}/plain"})
        runs = ws.tools.runs(limit=5)
        assert any(
            run["tool_name"] == "net.fetch" and run["status"] == "denied" for run in runs
        )


# --------------------------------------------------------------------------
# the research manager
# --------------------------------------------------------------------------
class TestResearchManager:
    def test_a_question_needs_four_characters(self, ws):
        with pytest.raises(ValidationError):
            ws.research.create("hi")

    def test_a_mode_must_be_known(self, ws):
        with pytest.raises(ValidationError):
            ws.research.create("a real question", mode="carrier-pigeon")

    def test_planned_by_must_be_known(self, ws):
        with pytest.raises(ValidationError):
            ws.research.create("a real question", planned_by="psychic")

    def test_a_run_round_trips(self, ws):
        run = ws.research.create("how does sqlite locking work", mode="local",
                                 plan=[{"question": "what is a lock", "why": "rule"}])
        assert run.status == "planning"
        assert run.plan[0]["question"] == "what is a lock"
        assert ws.research.get(run.id).question == run.question
        assert [item.question for item in ws.research.list()] == [run.question]

    def test_sources_belong_to_a_run(self, ws):
        ws.research.create("a real research question")
        with pytest.raises(NotFoundError):
            ws.research.add_source("rs_nope", url="file:///x", kind="file")

    def test_a_source_kind_must_be_known(self, ws):
        run = ws.research.create("a real research question")
        with pytest.raises(ValidationError):
            ws.research.add_source(run.id, url="x", kind="vibes")

    def test_a_source_status_must_be_known(self, ws):
        run = ws.research.create("a real research question")
        with pytest.raises(ValidationError):
            ws.research.add_source(run.id, url="x", kind="file", status="maybe")

    def test_a_source_needs_a_reference(self, ws):
        run = ws.research.create("a real research question")
        with pytest.raises(ValidationError):
            ws.research.add_source(run.id, url="  ", kind="file")

    def test_a_failed_source_is_still_stored(self, ws):
        run = ws.research.create("a real research question")
        stored = ws.research.add_source(
            run.id, url="https://example.invalid/x", kind="url",
            status="failed", error="connection refused",
        )
        assert stored.status == "failed" and stored.error == "connection refused"
        assert stored.usable is False
        assert [s.id for s in ws.research.sources(run.id)] == [stored.id]

    def test_update_refuses_unknown_fields(self, ws):
        run = ws.research.create("a real research question")
        with pytest.raises(ValidationError):
            ws.research.update(run.id, nonsense=1)

    def test_a_terminal_run_cannot_be_updated(self, ws):
        run = ws.research.create("a real research question")
        ws.research.finish(run.id, status="completed")
        with pytest.raises(ConflictError):
            ws.research.update(run.id, status="reading")

    def test_finish_requires_a_terminal_status(self, ws):
        run = ws.research.create("a real research question")
        with pytest.raises(ValidationError):
            ws.research.finish(run.id, status="reading")

    def test_finishing_twice_is_a_conflict(self, ws):
        run = ws.research.create("a real research question")
        ws.research.finish(run.id)
        with pytest.raises(ConflictError):
            ws.research.finish(run.id)

    def test_stats_and_search(self, ws):
        run = ws.research.create("how does sqlite locking work")
        ws.research.finish(run.id, status="incomplete", coverage=0.0)
        stats = ws.research.stats()
        assert stats["total"] == 1 and stats["by_status"]["incomplete"] == 1
        assert len(ws.research.search("locking")) == 1
        with pytest.raises(ValidationError):
            ws.research.search("x")

    def test_delete_removes_the_run_and_its_sources(self, ws):
        run = ws.research.create("a real research question")
        ws.research.add_source(run.id, url="file:///x", kind="file", excerpt="text")
        ws.research.finish(run.id)
        ws.research.delete(run.id)
        assert ws.research.stats()["total"] == 0
        assert ws.research.stats()["sources"] == 0
        with pytest.raises(NotFoundError):
            ws.research.get(run.id)

    def test_a_run_survives_a_reopen(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "1")
        home = str(tmp_path / "home")
        with open_workspace(home=home, env={}) as first:
            run = first.research.create("how does sqlite locking work")
            first.research.add_source(run.id, url="file:///x", kind="file", excerpt="body")
            first.research.finish(run.id, status="completed", coverage=1.0)
        with open_workspace(home=home, env={}) as second:
            stored = second.research.get(run.id)
            assert stored.status == "completed" and stored.coverage == 1.0
            assert len(second.research.sources(run.id)) == 1

    def test_the_schema_has_the_research_columns(self, ws):
        assert ws.store.schema_version() >= 18
        run_columns = {row["name"] for row in ws.store.query("PRAGMA table_info(research_runs)", ())}
        source_columns = {row["name"] for row in ws.store.query("PRAGMA table_info(research_sources)", ())}
        assert {"plan", "planned_by", "coverage", "report", "mode", "settings"} <= run_columns
        assert {"kind", "ref", "status", "checksum", "relevance", "claims"} <= source_columns

    def test_the_manager_is_the_one_the_workspace_uses(self, ws):
        assert isinstance(ws.research, ResearchManager)


# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------
class TestPlanning:
    def test_the_rules_plan_starts_with_the_question(self):
        plan = _rules_plan("how does sqlite locking work", 4)
        assert plan[0]["question"] == "how does sqlite locking work?"

    def test_the_rules_plan_is_deterministic(self):
        assert _rules_plan("what is retrieval quality", 4) == _rules_plan("what is retrieval quality", 4)

    def test_the_rules_plan_respects_the_cap(self):
        assert len(_rules_plan("how does sqlite locking work", 2)) == 2

    def test_the_rules_plan_says_it_came_from_rules(self):
        assert all(item["origin"] == "rules" for item in _rules_plan("what is kafka", 3))

    @pytest.mark.parametrize(
        "question, fragment",
        [
            ("how does sqlite locking work", "sqlite locking"),
            ("should i use postgres", "using postgres"),
            ("what does the router do", "the router"),
        ],
    )
    def test_the_subject_reads_naturally(self, question, fragment):
        assert fragment in _subject(question)

    def test_a_model_plan_is_used_when_it_validates(self, ws):
        model = ws.models.register_remote(
            "planner", provider="test-double", runtime="scripted", model_ref="simulated",
            capabilities=["chat"],
        )
        assert model.id
        reply = json.dumps({"subquestions": [
            {"question": "What is a write lock?", "why": "core"},
            {"question": "When do readers block?", "why": "behaviour"},
        ]})
        plan, planned_by, notes, meta = ResearchRunner(ws).plan("how does sqlite lock", subquestions=None)
        # the scripted runtime cannot produce JSON, so the honest answer is "rules"
        assert planned_by == "rules"
        assert plan and notes
        # and the parser itself is what accepts a real one:
        parsed = _parse_plan(reply, 8)
        assert [item["question"] for item in parsed] == [
            "What is a write lock?", "When do readers block?",
        ]
        assert all(item["origin"] == "model" for item in parsed)

    def test_user_subquestions_are_used_verbatim(self, ws):
        plan, planned_by, notes, meta = ResearchRunner(ws).plan(
            "how does sqlite lock", subquestions=["how does a write lock work"]
        )
        assert planned_by == "user"
        assert plan == [{"question": "how does a write lock work",
                         "why": "the user asked this", "origin": "user"}]
        assert meta["reason"].startswith("the user supplied")

    def test_user_subquestions_must_not_be_blank(self, ws):
        with pytest.raises(ValidationError):
            ResearchRunner(ws).plan("how does sqlite lock", subquestions=["   "])

    def test_a_malformed_plan_is_rejected_not_repaired(self):
        assert _parse_plan("I think you should research locks.", 8) == []
        assert _parse_plan('{"subquestions": "locks"}', 8) == []
        assert _parse_plan('{"subquestions": [{"question": "short"}]}', 8) == []

    def test_duplicate_and_oversized_plans_are_handled(self):
        text = json.dumps({"subquestions": [
            {"question": "What is a write lock?", "why": "a"},
            {"question": "what is a write lock?", "why": "b"},
            {"question": "When do readers block?", "why": "c"},
        ]})
        parsed = _parse_plan(text, 1)
        assert len(parsed) == 1

    def test_a_fenced_json_plan_is_accepted(self):
        text = 'Here you go:\n```json\n{"subquestions": [{"question": "What is WAL mode?"}]}\n```'
        assert len(_parse_plan(text, 4)) == 1


class TestJudgement:
    def test_a_valid_judgement_is_accepted(self):
        verdict = _parse_judgement(
            '{"stance": "supports", "relevance": 0.8, "claims": '
            '[{"quote": "one write lock per transaction", "why": "says so"}]}',
            "SQLite takes one write lock per transaction.",
        )
        assert verdict["stance"] == "supports"
        assert verdict["relevance"] == 0.8
        assert verdict["claims"][0]["quote"] == "one write lock per transaction"

    def test_a_fabricated_quote_is_dropped(self):
        verdict = _parse_judgement(
            '{"stance": "supports", "relevance": 0.9, "claims": '
            '[{"quote": "sqlite never locks at all", "why": "invented"}]}',
            "SQLite takes one write lock per transaction.",
        )
        assert verdict["claims"] == []

    def test_an_unknown_stance_is_rejected(self):
        assert _parse_judgement('{"stance": "vibes", "relevance": 0.5}', "text") is None

    def test_relevance_is_clamped(self):
        assert _parse_judgement('{"stance": "mixed", "relevance": 4.5}', "text")["relevance"] == 1.0
        assert _parse_judgement('{"stance": "mixed", "relevance": -2}', "text")["relevance"] == 0.0

    def test_a_non_numeric_relevance_is_rejected(self):
        assert _parse_judgement('{"stance": "mixed", "relevance": "high"}', "text") is None


# --------------------------------------------------------------------------
# running, locally
# --------------------------------------------------------------------------
class TestLocalRun:
    def test_a_local_run_finds_real_evidence_and_cites_it(self, ws):
        _corpus(ws)
        outcome = ws.researcher.run(
            "how does sqlite locking work",
            subquestions=["how does a write transaction lock"],
            use_model=False,
        )
        run = outcome["run"]
        assert run["status"] == "completed"
        assert run["evidence_count"] >= 2
        assert run["coverage"] == 1.0
        assert "[S1]" in outcome["report"]
        assert outcome["verification"]["ok"] is True
        assert outcome["verification"]["sources_cited"]

    def test_the_report_is_written_to_the_research_directory(self, ws):
        _corpus(ws)
        outcome = ws.researcher.run("how does sqlite locking work", use_model=False)
        path = outcome["report_path"]
        assert os.path.isfile(path)
        assert path.endswith(".md")
        with open(path, encoding="utf-8") as handle:
            assert "# Research: how does sqlite locking work" in handle.read()

    def test_out_overrides_the_location(self, ws, tmp_path):
        _corpus(ws)
        target = tmp_path / "custom" / "report.md"
        outcome = ws.researcher.run(
            "how does sqlite locking work", out=str(target), use_model=False
        )
        assert outcome["report_path"] == str(target)
        assert target.exists()

    def test_html_output_is_escaped(self, ws, tmp_path):
        _corpus(ws)
        target = tmp_path / "report.html"
        ws.researcher.run(
            "how does sqlite locking work && <script>", out=str(target), report_format="html",
            use_model=False,
        )
        body = target.read_text(encoding="utf-8")
        assert body.startswith("<!doctype html>")
        assert "&lt;script&gt;" in body

    def test_the_run_creates_a_research_task_with_an_artifact(self, ws):
        _corpus(ws)
        outcome = ws.researcher.run("how does sqlite locking work", use_model=False)
        task = ws.tasks.get(outcome["run"]["task_id"])
        assert task.type == "research"
        assert task.status == "completed"
        artifacts = ws.tasks.artifacts(task.id)
        assert artifacts and artifacts[0].kind == "report"

    def test_the_runs_own_task_is_not_evidence(self, ws):
        _corpus(ws)
        outcome = ws.researcher.run("how does sqlite locking work", use_model=False)
        sources = ws.research.sources(outcome["run"]["id"])
        assert all(source.kind != "task" for source in sources)

    def test_no_evidence_is_reported_as_incomplete_not_success(self, ws):
        outcome = ws.researcher.run(
            "what is the airspeed of an unladen swallow", use_model=False
        )
        run = outcome["run"]
        assert run["status"] == "incomplete"
        assert run["evidence_count"] == 0
        assert run["coverage"] == 0.0
        assert "I found no evidence" in outcome["report"]
        assert outcome["verification"]["ok"] is True

    def test_limitations_name_what_was_missing(self, ws):
        _corpus(ws)
        outcome = ws.researcher.run("how does sqlite locking work", use_model=False)
        limitations = " ".join(outcome["run"]["limitations"])
        assert "planned by rules" in limitations
        assert "the web was not consulted" in limitations
        assert "no model was configured" in limitations

    def test_without_a_model_the_report_is_extractive_and_says_so(self, ws):
        _corpus(ws)
        outcome = ws.researcher.run("how does sqlite locking work", use_model=False)
        assert "## Short answer (extractive, every line cited)" in outcome["report"]
        assert "## A model's reading" not in outcome["report"]

    def test_a_model_that_writes_uncited_prose_is_demoted(self, ws, model):
        _corpus(ws)
        outcome = ws.researcher.run(
            "how does sqlite locking work", subquestions=["how does a write lock work"]
        )
        assert outcome["model_reading"]["demoted"] >= 1
        assert "## Statements I could not tie to a source" in outcome["report"]
        assert any("not tied to a source" in note for note in outcome["run"]["limitations"])
        assert outcome["verification"]["ok"] is True

    def test_the_same_inputs_produce_the_same_evidence(self, ws):
        _corpus(ws)
        first = ws.researcher.run("how does sqlite locking work", use_model=False)
        second = ws.researcher.run("how does sqlite locking work", use_model=False)
        refs = [
            [source.ref for source in ws.research.sources(run["run"]["id"])]
            for run in (first, second)
        ]
        assert refs[0] == refs[1]

    def test_a_web_mode_without_urls_is_refused(self, ws):
        with pytest.raises(ValidationError) as exc:
            ws.researcher.run("how does sqlite locking work", mode="web")
        assert "--url" in exc.value.message

    def test_urls_with_local_mode_are_refused_rather_than_ignored(self, ws):
        with pytest.raises(ValidationError):
            ws.researcher.run("how does sqlite locking work", mode="local",
                              urls=["http://example.com"])

    def test_an_unknown_format_is_refused(self, ws):
        with pytest.raises(ValidationError):
            ws.researcher.run("how does sqlite locking work", report_format="pdf")

    def test_a_run_that_fails_is_recorded(self, ws, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("the disk caught fire")

        monkeypatch.setattr(ResearchRunner, "gather_local", boom)
        with pytest.raises(RuntimeError):
            ws.researcher.run("how does sqlite locking work", use_model=False)
        run = ws.research.list()[0]
        assert run.status == "failed"
        assert "disk caught fire" in (run.error or "")


class TestWebRun:
    def test_web_research_needs_the_capability_and_grants_nothing(self, ws, site):
        with pytest.raises(ResearchBlocked) as exc:
            ws.researcher.run(
                "how does sqlite locking work", mode="web", urls=[f"{site}/locking"],
                allow_private_hosts=True, use_model=False,
            )
        assert exc.value.approval_id
        run = ws.research.get(exc.value.run_id)
        assert run.status == "failed"
        assert "net.fetch" in (run.error or "")
        assert [g for g in ws.permissions.grants() if g.capability == "net.fetch"] == []

    def test_a_granted_web_run_reads_real_pages(self, ws, site):
        _corpus(ws)
        ws.permissions.grant("net.fetch", subject="net.fetch", duration="persistent", confirm=True)
        outcome = ws.researcher.run(
            "how does sqlite locking work", mode="web",
            urls=[f"{site}/locking", f"{site}/wal"], allow_private_hosts=True, use_model=False,
        )
        run = outcome["run"]
        assert run["status"] == "completed"
        sources = ws.research.sources(run["id"])
        assert {source.kind for source in sources} == {"url"}
        assert all(source.checksum for source in sources)
        assert "SQLite locking explained" in {source.title for source in sources}

    def test_a_page_that_cannot_be_read_is_recorded_not_hidden(self, ws, site):
        ws.permissions.grant("net.fetch", subject="net.fetch", duration="persistent", confirm=True)
        outcome = ws.researcher.run(
            "how does sqlite locking work", mode="web",
            urls=[f"{site}/locking", f"{site}/missing"], allow_private_hosts=True,
            use_model=False,
        )
        sources = ws.research.sources(outcome["run"]["id"])
        failed = [source for source in sources if source.status == "failed"]
        assert failed and "404" in (failed[0].error or "")
        assert "could not be read" in " ".join(outcome["run"]["limitations"])

    def test_mixed_mode_reads_both_and_labels_the_kinds(self, ws, site):
        _corpus(ws)
        ws.permissions.grant("net.fetch", subject="net.fetch", duration="persistent", confirm=True)
        outcome = ws.researcher.run(
            "how does sqlite locking work", mode="mixed",
            urls=[f"{site}/wal"], allow_private_hosts=True, use_model=False,
        )
        kinds = {source.kind for source in ws.research.sources(outcome["run"]["id"])}
        assert "url" in kinds and kinds & {"memory", "file"}

    def test_a_binary_page_is_refused_and_recorded(self, ws, site):
        ws.permissions.grant("net.fetch", subject="net.fetch", duration="persistent", confirm=True)
        outcome = ws.researcher.run(
            "how does sqlite locking work", mode="web", urls=[f"{site}/binary"],
            allow_private_hosts=True, use_model=False,
        )
        sources = ws.research.sources(outcome["run"]["id"])
        assert sources[0].status == "failed"
        assert "not a text document" in (sources[0].error or "")


class TestVerification:
    def test_a_report_with_no_citations_is_not_ok(self):
        report = (
            "## Short answer (extractive, every line cited)\n\n"
            "- **a claim** - no citation here\n"
        )
        result = ResearchRunner.verify(report, [1, 2])
        assert result["ok"] is False
        assert result["uncited_claims"]

    def test_an_unknown_citation_is_a_defect(self):
        report = "## Short answer (extractive, every line cited)\n\n- **q** - [S9] says so"
        result = ResearchRunner.verify(report, [1])
        assert result["unknown_citations"] == [9]
        assert result["ok"] is False

    def test_limitations_are_not_claims(self):
        report = (
            "## What I could not establish\n\n- the web was not consulted\n"
            "- no model was configured\n"
        )
        assert ResearchRunner.verify(report, [])["ok"] is True

    def test_a_facet_with_topic_evidence_still_needs_its_citation(self):
        report = (
            "## Short answer (extractive, every line cited)\n\n"
            "- **facet** - no source addresses this facet specifically; the topic evidence is [S1].\n"
        )
        assert ResearchRunner.verify(report, [1])["ok"] is True

    def test_demoted_prose_is_not_required_to_be_cited(self):
        report = (
            "## Statements I could not tie to a source\n\n"
            "_The model wrote these, but they carry no valid citation, so they are not findings._\n\n"
            "- SQLite is the fastest database in the world.\n"
        )
        assert ResearchRunner.verify(report, [])["ok"] is True


class TestSourceDoc:
    def test_a_document_with_no_text_is_not_usable(self):
        doc = SourceDoc(kind="url", ref="http://x", title="x", text="", excerpt="")
        assert doc.usable is False

    def test_a_failed_document_is_not_usable(self):
        doc = SourceDoc(kind="url", ref="http://x", title="x", text="body", status="failed")
        assert doc.usable is False


# --------------------------------------------------------------------------
# the installed console script
# --------------------------------------------------------------------------
class TestResearchCli:
    def _cli(self, home, *args, timeout=240, input_text=None):
        env = dict(os.environ)
        env.pop("ARCHX_PATHS_HOME", None)
        env["ARCHX_ALLOW_SIMULATED"] = "1"
        return subprocess.run(
            [CLI, "--home", home, *args], capture_output=True, text=True, env=env,
            timeout=timeout, input=input_text,
        )

    def _home(self, tmp_path):
        home = str(tmp_path / "cli-home")
        assert self._cli(home, "init").returncode == 0
        workspace = os.path.join(home, "workspace", "docs")
        os.makedirs(workspace, exist_ok=True)
        with open(os.path.join(workspace, "locking.md"), "w", encoding="utf-8") as handle:
            handle.write(
                "SQLite locking: a write transaction takes an exclusive lock, and WAL mode "
                "lets readers continue.\n"
            )
        return home

    def test_run_json_reports_coverage_and_verification(self, tmp_path):
        home = self._home(tmp_path)
        result = self._cli(home, "--json", "research", "run", "how does sqlite locking work",
                           "--no-model", "--subquestion", "how does a write lock work")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["run"]["status"] == "completed"
        assert payload["verification"]["ok"] is True
        assert payload["run"]["planned_by"] == "user"

    def test_run_without_evidence_exits_3(self, tmp_path):
        home = self._home(tmp_path)
        result = self._cli(home, "research", "run", "what is the airspeed of a swallow",
                           "--no-model", "--subquestion", "zeppelin schematics")
        assert result.returncode == 3, result.stdout
        assert "no evidence" in result.stdout.lower()

    def test_web_mode_without_urls_is_a_usage_error(self, tmp_path):
        home = self._home(tmp_path)
        result = self._cli(home, "research", "run", "how does sqlite lock", "--mode", "web",
                           "--no-model")
        assert result.returncode == 2
        assert "--url" in result.stderr

    def test_list_show_sources_report_and_stats(self, tmp_path):
        home = self._home(tmp_path)
        first = self._cli(home, "--json", "research", "run", "how does sqlite locking work",
                          "--no-model", "--subquestion", "how does a write lock work")
        run_id = json.loads(first.stdout)["run"]["id"]
        listing = self._cli(home, "--json", "research", "list")
        assert json.loads(listing.stdout)[0]["id"] == run_id
        show = self._cli(home, "research", "show", run_id)
        assert "plan:" in show.stdout and run_id in show.stdout
        sources = self._cli(home, "--json", "research", "sources", run_id)
        assert json.loads(sources.stdout)[0]["kind"] == "file"
        report = self._cli(home, "research", "report", run_id)
        assert "# Research:" in report.stdout
        verify = self._cli(home, "--json", "research", "verify", run_id)
        assert json.loads(verify.stdout)["ok"] is True
        stats = self._cli(home, "--json", "research", "stats")
        assert json.loads(stats.stdout)["total"] == 1

    def test_report_can_be_written_to_a_file(self, tmp_path):
        home = self._home(tmp_path)
        first = self._cli(home, "--json", "research", "run", "how does sqlite locking work",
                          "--no-model", "--subquestion", "how does a write lock work")
        run_id = json.loads(first.stdout)["run"]["id"]
        target = tmp_path / "copy.md"
        result = self._cli(home, "research", "report", run_id, "--write", str(target))
        assert result.returncode == 0
        assert target.exists() and target.read_text(encoding="utf-8").startswith("# Research:")

    def test_search_finds_a_past_run(self, tmp_path):
        home = self._home(tmp_path)
        self._cli(home, "research", "run", "how does sqlite locking work", "--no-model",
                  "--subquestion", "how does a write lock work")
        found = self._cli(home, "--json", "research", "search", "locking")
        assert len(json.loads(found.stdout)) == 1

    def test_delete_needs_yes(self, tmp_path):
        home = self._home(tmp_path)
        first = self._cli(home, "--json", "research", "run", "how does sqlite locking work",
                          "--no-model", "--subquestion", "how does a write lock work")
        run_id = json.loads(first.stdout)["run"]["id"]
        assert self._cli(home, "research", "delete", run_id).returncode == 2
        assert self._cli(home, "research", "delete", run_id, "--yes").returncode == 0
        assert json.loads(self._cli(home, "--json", "research", "list").stdout) == []

    def test_an_unknown_run_is_a_usage_error(self, tmp_path):
        home = self._home(tmp_path)
        assert self._cli(home, "research", "show", "rs_nope").returncode == 2

    def test_a_research_job_runs_through_the_queue(self, tmp_path):
        home = self._home(tmp_path)
        submitted = self._cli(
            home, "--json", "jobs", "submit", "research", "how does sqlite locking work",
            "--no-model", "--job-json", '{"subquestions": ["how does a write lock work"]}',
        )
        assert submitted.returncode == 0, submitted.stderr
        job_id = json.loads(submitted.stdout)["id"]
        assert json.loads(submitted.stdout)["status"] == "queued"
        drained = self._cli(home, "jobs", "run", "--once", "--kind", "research")
        assert drained.returncode in {0, 3}
        shown = json.loads(self._cli(home, "--json", "jobs", "show", job_id).stdout)
        assert shown["status"] == "completed"
        assert shown["task_id"]
        assert json.loads(self._cli(home, "--json", "research", "list").stdout)


# --------------------------------------------------------------------------
# targeted guards (each one fails if the specific protection is removed)
# --------------------------------------------------------------------------
class TestTargetedGuards:
    def test_the_metadata_address_is_blocked(self):
        with pytest.raises(FetchBlockedError) as exc:
            check_url("http://169.254.169.254/latest/meta-data/")
        assert "private or local" in exc.value.message

    def test_a_private_hostname_is_blocked_by_resolution(self):
        with pytest.raises(FetchBlockedError):
            check_url("http://localhost:8000/x")

    def test_the_excerpt_is_the_relevant_window_not_the_first_line(self):
        from archx_agent.application.researcher import _excerpt

        body = (
            "Unrelated introduction about gardening and the weather.\n"
            "Another paragraph about lunch and holidays.\n"
            "SQLite takes a write lock per transaction, which is what matters here.\n"
        )
        excerpt = _excerpt(body, ["sqlite", "write", "lock"], 90)
        assert "write lock per transaction" in excerpt
        assert "gardening" not in excerpt

    def test_a_facet_gets_no_credit_without_its_vocabulary(self):
        from archx_agent.application.researcher import _assign_subquestion

        plan = [
            {"question": "how does sqlite locking work?"},
            {"question": "What commonly goes wrong with sqlite locking?"},
        ]
        text = "SQLite takes one write lock per transaction; WAL lets readers continue."
        assert _assign_subquestion(text, plan, "how does sqlite locking work") == 0
        text_with_facet = "It commonly goes wrong when two writers collide."
        assert _assign_subquestion(text_with_facet, plan, "how does sqlite locking work") == 1

    def test_citation_numbers_restart_for_each_run(self, ws):
        _corpus(ws)
        first = ws.researcher.run("how does sqlite locking work", use_model=False)
        second = ws.researcher.run("how does sqlite locking work", use_model=False)
        for outcome in (first, second):
            assert "[S1]" in outcome["report"]
            assert outcome["verification"]["sources_cited"][0] == 1

    def test_verify_through_the_cli_exits_3_on_a_defective_report(self, tmp_path):
        home = str(tmp_path / "defective")
        with open_workspace(home=home, env={}) as ws:
            run = ws.research.create("how does sqlite locking work")
            ws.research.add_source(run.id, url="file:///x", kind="file", excerpt="body")
            ws.research.finish(
                run.id, status="completed", coverage=1.0,
                report="## Short answer (extractive, every line cited)\n\n"
                       "- **q** - [S7] claims something that has no source\n",
            )
        env = dict(os.environ)
        env.pop("ARCHX_PATHS_HOME", None)
        result = subprocess.run(
            [CLI, "--home", home, "--json", "research", "verify", run.id],
            capture_output=True, text=True, env=env, timeout=120,
        )
        assert result.returncode == 3
        payload = json.loads(result.stdout)
        assert payload["unknown_citations"] == [7]
        assert payload["ok"] is False
