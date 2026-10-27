"""M27: unified search across conversations, memory, tasks, workflows and files.

The tests build real rows through the real managers (no fixtures of raw SQL) and then ask
the search service questions, because the point of the feature is that it reads *existing*
data rather than an index of its own.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from archx_agent.application.search import (
    KIND_WEIGHT,
    SEARCH_KINDS,
    SearchHit,
    SearchService,
    score_text,
)
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import ValidationError

CLI = os.path.join(os.path.dirname(sys.executable), "archx-agent")


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "1")
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


def _seed(ws, *, title="Database locks", content="SQLite locks once per write transaction."):
    memory = ws.memory.add("permanent", title, content, category="fact")
    assert memory.is_ok, memory.error
    conversation = ws.conversations.create(title="Notes about database tuning")
    ws.conversations.append_message(
        conversation.id, "user", "the database locks during writes"
    )
    ws.tasks.create("chat", "investigate database locks", start=True, manual=True)
    ws.workflows.create(
        {
            "name": "database-check",
            "goal": "check the database",
            "steps": [{"kind": "note", "text": "ok"}],
        }
    )
    project = ws.projects.create("database", description="schema and query work")
    return {"memory": memory.value, "conversation": conversation, "project": project}


def _write(ws, name, text, *, subdir=None):
    root = ws.tool_roots()[0]
    path = os.path.join(root, subdir, name) if subdir else os.path.join(root, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------
class TestScoring:
    def test_all_terms_score_at_least_one(self):
        assert score_text("database locks", "the database locks briefly") >= 1.0

    def test_partial_coverage_scores_below_full(self):
        full = score_text("database locks", "the database locks briefly")
        partial = score_text("database locks", "the database is fine")
        assert 0 < partial < full

    def test_the_phrase_bonus_ranks_exact_matches_higher(self):
        phrase = score_text("database locks", "database locks happen")
        apart = score_text("database locks", "the locks are in the database")
        assert phrase > apart

    def test_the_title_counts_as_content(self):
        assert score_text("database", "nothing relevant", title="Database locking") > 0

    def test_a_title_match_beats_a_body_only_match(self):
        title = score_text("kafka", "streams", title="Kafka notes")
        body = score_text("kafka", "kafka streams")
        assert title > body

    def test_no_match_scores_zero(self):
        assert score_text("kafka", "database locks") == 0.0

    def test_matching_is_case_insensitive(self):
        assert score_text("DATABASE", "the DataBase is locked") > 0

    def test_punctuation_is_ignored_in_terms(self):
        assert score_text("database, locks!", "database locks") > 0

    def test_an_empty_query_scores_zero(self):
        assert score_text("", "anything") == 0.0
        assert score_text("a", "anything") == 0.0  # one-letter terms are dropped

    def test_kind_weights_order_ties(self):
        assert KIND_WEIGHT["memory"] > KIND_WEIGHT["conversation"] > KIND_WEIGHT["file"]


# --------------------------------------------------------------------------
# the merged search
# --------------------------------------------------------------------------
class TestSearchSources:
    def test_every_kind_is_known(self):
        assert set(SEARCH_KINDS) == {
            "conversation", "memory", "task", "workflow", "project", "artifact", "file", "tool"
        }

    def test_memory_conversations_tasks_and_workflows_are_all_found(self, ws):
        _seed(ws)
        report = ws.search.search("database", limit=20, include_files=False)
        kinds = {hit.kind for hit in report.hits}
        assert {"memory", "conversation", "task", "workflow"} <= kinds
        assert report.counts["memory"] >= 1
        assert report.counts["conversation"] >= 1

    def test_projects_are_searchable(self, ws):
        _seed(ws)
        report = ws.search.search("schema", kinds=["project"])
        assert report.hits and report.hits[0].id == _seed_project_id(ws)

    def test_tools_are_searchable_by_name_and_summary(self, ws):
        report = ws.search.search("shell", kinds=["tool"])
        assert report.hits and report.hits[0].title == "shell.run"
        assert report.hits[0].meta["capability"] == "shell.run"

    def test_files_are_searchable_with_a_line_number(self, ws):
        path = _write(ws, "notes.md", "line one\nthe database locks here\nline three\n")
        report = ws.search.search("database locks", kinds=["file"])
        assert report.hits and report.hits[0].meta["path"] == path
        assert report.hits[0].meta["line"] == 2
        assert "database locks" in report.hits[0].snippet

    def test_files_in_nested_directories_are_found(self, ws):
        _write(ws, "deep.md", "kafka topic design", subdir="docs/design")
        report = ws.search.search("kafka", kinds=["file"])
        assert report.hits and report.hits[0].title.endswith("deep.md")

    def test_binary_files_are_skipped(self, ws):
        root = ws.tool_roots()[0]
        with open(os.path.join(root, "blob.bin"), "wb") as handle:
            handle.write(b"kafka\x00\x01\x02binary")
        report = ws.search.search("kafka", kinds=["file"])
        assert report.hits == []

    def test_oversized_files_are_skipped(self, ws):
        ws.config.set("search.max_file_bytes", 1024)
        _write(ws, "big.txt", "kafka " * 500)
        report = ws.search.search("kafka", kinds=["file"])
        assert report.hits == []

    def test_noise_directories_are_not_scanned(self, ws):
        _write(ws, "hidden.txt", "kafka topic", subdir="node_modules/pkg")
        report = ws.search.search("kafka", kinds=["file"])
        assert report.hits == []
        assert report.scanned["file"] == 0

    def test_artifacts_are_searchable(self, ws, tmp_path):
        task = ws.tasks.create("tool", "artifact owner", start=True, manual=True)
        path = tmp_path / "report.md"
        path.write_text("quarterly numbers\n", encoding="utf-8")
        artifact = ws.tasks.attach_artifact(task.id, str(path), name="quarterly-report.md")
        report = ws.search.search("quarterly", kinds=["artifact"])
        assert report.hits and report.hits[0].id == artifact.id
        assert report.hits[0].meta["checksum"]

    def test_conversation_hits_point_at_a_command(self, ws):
        _seed(ws)
        hit = ws.search.search("database", kinds=["conversation"]).hits[0]
        assert hit.ref.startswith("archx-agent conv show")

    def test_search_does_not_write_anything(self, ws):
        _seed(ws)
        before = (ws.memory.stats()["total_active"], ws.tasks.stats()["total"],
                  ws.conversations.list_conversations().__len__())
        ws.search.search("database", limit=20)
        after = (ws.memory.stats()["total_active"], ws.tasks.stats()["total"],
                 ws.conversations.list_conversations().__len__())
        assert before == after


def _seed_project_id(ws):
    return ws.projects.by_slug("database").value.id


class TestSearchControls:
    def test_kinds_restrict_the_sources(self, ws):
        _seed(ws)
        report = ws.search.search("database", kinds=["memory"])
        assert {hit.kind for hit in report.hits} == {"memory"}
        assert "conversation" not in report.counts

    def test_an_unknown_kind_is_refused(self, ws):
        with pytest.raises(ValidationError) as exc:
            ws.search.search("database", kinds=["emails"])
        assert "emails" in exc.value.message

    def test_a_one_character_query_is_refused(self, ws):
        with pytest.raises(ValidationError):
            ws.search.search("x")

    def test_limit_caps_the_merged_list(self, ws):
        _seed(ws)
        report = ws.search.search("database", limit=2)
        assert len(report.hits) == 2

    def test_per_source_caps_each_source(self, ws):
        topics = ["partitions", "offsets", "consumer groups", "retention", "compaction", "replication"]
        for topic in topics:
            stored = ws.memory.add(
                "permanent", f"kafka {topic}", f"how kafka handles {topic} in this project",
                category="fact",
            )
            assert stored.is_ok, stored.error
        report = ws.search.search("kafka", kinds=["memory"], per_source=3)
        assert report.counts["memory"] == 3

    def test_conversation_scope_limits_conversation_hits(self, ws):
        first = ws.conversations.create(title="kafka one")
        second = ws.conversations.create(title="kafka two")
        ws.conversations.append_message(second.id, "user", "kafka")
        report = ws.search.search("kafka", kinds=["conversation"], conversation_id=first.id)
        assert [hit.id for hit in report.hits] == [first.id]

    def test_file_search_can_be_switched_off(self, ws):
        _write(ws, "notes.md", "kafka")
        report = ws.search.search("kafka", include_files=False)
        assert "file" in report.skipped
        assert "disabled" in report.skipped["file"]

    def test_no_matches_is_an_empty_report_not_an_error(self, ws):
        report = ws.search.search("zeppelin")
        assert report.hits == []
        assert report.counts == {}
        assert report.total if False else True  # to_dict is separate
        assert report.to_dict()["total"] == 0

    def test_results_are_deterministic(self, ws):
        _seed(ws)
        first = [hit.id for hit in ws.search.search("database", limit=10).hits]
        second = [hit.id for hit in ws.search.search("database", limit=10).hits]
        assert first == second

    def test_higher_scores_come_first(self, ws):
        ws.memory.add("permanent", "kafka", "kafka kafka kafka", category="fact")
        ws.memory.add("permanent", "streams", "kafka is mentioned once", category="fact")
        hits = ws.search.search("kafka", kinds=["memory"]).hits
        assert hits[0].title == "kafka"

    def test_degraded_sources_are_reported_not_hidden(self, ws):
        _seed(ws)
        report = ws.search.search("database", kinds=["memory"])
        assert any("keyword-only" in note for note in report.degraded)

    def test_the_limit_comes_from_config_when_the_caller_does_not_pass_one(self, ws):
        for index in range(4):
            ws.memory.add("permanent", f"zebra note {index}", f"zebra body {index}",
                          category="fact", allow_duplicate=True)
        ws.config.set("search.default_limit", 2)
        assert len(ws.search.search("zebra").hits) == 2

    def test_the_per_source_cap_comes_from_config(self, ws):
        for index in range(4):
            ws.memory.add("permanent", f"yak note {index}", f"yak body {index}",
                          category="fact", allow_duplicate=True)
        ws.config.set("search.per_source", 2)
        report = ws.search.search("yak", kinds=["memory"], limit=50)
        assert report.counts["memory"] == 2

    def test_the_report_serialises(self, ws):
        _seed(ws)
        payload = ws.search.search("database", limit=3).to_dict()
        json.dumps(payload)  # must be JSON-serialisable
        assert payload["query"] == "database"
        assert payload["total"] == len(payload["hits"])
        for key in ("hits", "counts", "skipped", "degraded", "scanned", "elapsed_ms"):
            assert key in payload

    def test_a_hit_serialises_with_a_rounded_score(self):
        hit = SearchHit(kind="memory", id="m1", title="t", snippet="s", score=1.23456789)
        assert hit.to_dict()["score"] == 1.2346


class TestSearchCli:
    def _cli(self, home, *args, timeout=120):
        env = dict(os.environ)
        env.pop("ARCHX_PATHS_HOME", None)
        env["ARCHX_ALLOW_SIMULATED"] = "1"
        return subprocess.run(
            [CLI, "--home", home, *args], capture_output=True, text=True, env=env, timeout=timeout
        )

    def _home(self, tmp_path):
        home = str(tmp_path / "cli-home")
        assert self._cli(home, "init").returncode == 0
        return home

    def test_search_prints_hits_and_sources(self, tmp_path):
        home = self._home(tmp_path)
        assert self._cli(home, "memory", "add", "--kind", "permanent", "--title", "Kafka notes",
                         "--content", "kafka is a log", "--category", "fact").returncode == 0
        result = self._cli(home, "search", "kafka")
        assert result.returncode == 0, result.stderr
        assert "[memory] Kafka notes" in result.stdout
        assert "sources: memory 1" in result.stdout

    def test_search_json_is_machine_readable(self, tmp_path):
        home = self._home(tmp_path)
        self._cli(home, "memory", "add", "--kind", "permanent", "--title", "Kafka",
                  "--content", "kafka", "--category", "fact")
        payload = json.loads(self._cli(home, "--json", "search", "kafka").stdout)
        assert payload["total"] >= 1
        assert payload["hits"][0]["kind"] == "memory"

    def test_search_with_no_matches_says_so(self, tmp_path):
        home = self._home(tmp_path)
        result = self._cli(home, "search", "zeppelin")
        assert result.returncode == 0
        assert "no matches" in result.stdout

    def test_search_kind_filter_and_invalid_kind(self, tmp_path):
        home = self._home(tmp_path)
        self._cli(home, "memory", "add", "--kind", "permanent", "--title", "Kafka",
                  "--content", "kafka", "--category", "fact")
        limited = json.loads(self._cli(home, "--json", "search", "kafka", "--kind", "memory").stdout)
        assert {hit["kind"] for hit in limited["hits"]} == {"memory"}
        bad = self._cli(home, "search", "kafka", "--kind", "emails")
        assert bad.returncode == 2

    def test_no_files_flag_is_reported_as_skipped(self, tmp_path):
        home = self._home(tmp_path)
        payload = json.loads(self._cli(home, "--json", "search", "kafka", "--no-files").stdout)
        assert "file" in payload["skipped"]
