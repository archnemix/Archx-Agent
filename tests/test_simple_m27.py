"""M27: Simple Mode - one box, an honest answer, and never a silent privilege.

The tests care as much about the *explanation* (intent, why, next step) as about the
answer, because the failure mode of a friendlier front end is that it hides what happened.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from archx_agent.application.simple import (
    INTENTS,
    SimpleMode,
    SimpleResult,
    detect_intent,
    search_terms,
)
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import ValidationError

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


def _seed(ws):
    ws.memory.add("permanent", "Database locking", "SQLite locks once per write.", category="fact")
    conversation = ws.conversations.create(title="database notes")
    ws.conversations.append_message(conversation.id, "user", "the database locks briefly")
    root = ws.tool_roots()[0]
    with open(os.path.join(root, "notes.md"), "w", encoding="utf-8") as handle:
        handle.write("the database uses WAL\n")
    return conversation


# --------------------------------------------------------------------------
# intent detection
# --------------------------------------------------------------------------
class TestIntentDetection:
    @pytest.mark.parametrize(
        "text, intent",
        [
            ("where did I write about database locks", "search"),
            ("find the notes on kafka", "search"),
            ("do we have anything about WAL", "search"),
            ("remember that the staging key lives in vault", "remember"),
            ("remember: deploy on fridays", "remember"),
            ("note that the build is slow", "remember"),
            ("always use metric units", "remember"),
            ("from now on answer briefly", "remember"),
            ("recall the database decision", "recall"),
            ("what do you know about kafka", "recall"),
            ("status", "status"),
            ("what's running", "status"),
            ("what is pending", "status"),
            ("run template summarise-file path=notes.md", "workflow"),
            ("run the workflow database-check", "workflow"),
            ("help", "help"),
            ("hello, how are you?", "chat"),
            ("summarise this paragraph", "chat"),
        ],
    )
    def test_natural_language_rules(self, text, intent):
        assert detect_intent(text)[0] == intent

    @pytest.mark.parametrize(
        "text, intent",
        [
            ("/search kafka", "search"),
            ("/find kafka", "search"),
            ("/remember the key is in vault", "remember"),
            ("/note the build is slow", "remember"),
            ("/recall kafka", "recall"),
            ("/status", "status"),
            ("/help", "help"),
            ("/ask what is kafka", "chat"),
            ("/quit", "quit"),
            ("/exit", "quit"),
        ],
    )
    def test_slash_commands(self, text, intent):
        assert detect_intent(text)[0] == intent

    def test_an_unknown_slash_command_falls_back_to_help(self):
        intent, why = detect_intent("/deploy now")
        assert intent == "help" and "/deploy" in why

    def test_every_intent_has_a_plain_language_reason(self):
        for text in ("where is x", "status", "hello", "help"):
            intent, why = detect_intent(text)
            assert intent in INTENTS and why and why[0].islower()

    def test_an_empty_line_is_refused(self):
        with pytest.raises(ValidationError):
            detect_intent("   ")

    def test_question_prefixes_are_stripped_from_the_query(self):
        assert search_terms("where did I write about database locks?") == "database locks"
        assert search_terms("find the notes on kafka") == "notes kafka"

    def test_a_query_of_only_stopwords_keeps_the_original_words(self):
        assert search_terms("what is it") != ""


# --------------------------------------------------------------------------
# intents
# --------------------------------------------------------------------------
class TestSimpleIntents:
    def test_search_finds_memory_files_and_conversations_and_says_why(self, ws):
        _seed(ws)
        result = ws.simple.ask("where did I write about database locks")
        assert result.intent == "search"
        assert "result(s)" in result.headline
        assert "[memory]" in result.detail and "[file]" in result.detail
        assert "searched the workspace" in result.why
        assert result.data["report"]["total"] >= 2

    def test_search_says_where_it_looked_when_nothing_matches(self, ws):
        _seed(ws)
        result = ws.simple.ask("find zeppelin schematics")
        assert result.intent == "search"
        assert "could not find" in result.headline
        assert "I looked in" in result.detail

    def test_search_reports_degraded_sources(self, ws):
        _seed(ws)
        result = ws.simple.ask("where did I write about database")
        assert "keyword-only" in result.detail

    def test_recall_only_searches_memory(self, ws):
        _seed(ws)
        result = ws.simple.ask("recall database")
        assert result.intent == "recall"
        assert "memory item(s)" in result.headline
        assert "[file]" not in result.detail

    def test_remember_stores_a_permanent_fact(self, ws):
        result = ws.simple.ask("remember that the staging key lives in vault")
        assert result.intent == "remember"
        assert "Stored as permanent/fact" in result.headline
        memory = ws.memory.require(result.data["memory_id"])
        assert memory.title == "the staging key lives in vault"
        assert memory.kind == "permanent"
        assert memory.provenance["mode"] == "simple"

    def test_remember_detects_a_preference(self, ws):
        result = ws.simple.ask("from now on answer in metric units")
        assert result.intent == "remember"
        assert result.data["category"] == "preference"
        assert "preference" in result.headline

    def test_remembering_the_same_thing_twice_is_reported_not_hidden(self, ws):
        ws.simple.ask("remember that the deploy window is friday")
        second = ws.simple.ask("remember that the deploy window is friday")
        assert second.headline == "I did not store that."
        assert second.data["duplicate"] is True
        assert len(ws.memory.search("deploy window").hits) == 1

    def test_remembering_nothing_is_refused(self, ws):
        with pytest.raises(ValidationError):
            ws.simple.ask("remember that")

    def test_remembered_items_are_immediately_recallable(self, ws):
        ws.simple.ask("remember that the cache lives in redis")
        result = ws.simple.ask("recall cache")
        assert "redis" in result.detail

    def test_status_reports_models_memory_and_jobs(self, ws, model):
        ws.memory.add("permanent", "a fact", "content", category="fact")
        ws.jobs.enqueue("command", "queued work", {"command": "echo hi"})
        result = ws.simple.status()
        assert result.intent == "status"
        assert "1 registered" in result.detail
        assert "1 active item" in result.detail
        assert "1 queued" in result.detail
        assert result.data["jobs"]["queued"] == 1

    def test_status_says_when_the_model_is_a_test_double(self, ws, model):
        result = ws.simple.status()
        assert result.data["simulated"] is True
        assert "SIMULATED" in result.detail

    def test_status_never_raises_without_a_model(self, ws):
        result = ws.simple.status()
        assert result.intent == "status"
        assert "nothing eligible" in result.detail

    def test_help_lists_the_intents(self, ws):
        result = ws.simple.help()
        assert result.intent == "help"
        for phrase in ("ask me anything", "remember that", "run template", "/quit"):
            assert phrase in result.detail


# --------------------------------------------------------------------------
# chat intent, approvals and authority
# --------------------------------------------------------------------------
class TestSimpleChat:
    def test_chat_answers_through_the_real_chat_service(self, ws, model):
        result = ws.simple.ask("hello there")
        assert result.intent == "chat"
        assert result.headline  # the scripted reply
        assert result.data["conversation_id"]
        assert result.data["model_id"]

    def test_chat_keeps_one_conversation_across_turns(self, ws, model):
        first = ws.simple.ask("hello")
        second = ws.simple.ask("again", conversation_id=first.data["conversation_id"])
        assert second.data["conversation_id"] == first.data["conversation_id"]
        messages = ws.conversations.messages(first.data["conversation_id"])
        assert len(messages) == 4

    def test_no_model_is_explained_with_a_next_step(self, ws):
        result = ws.simple.ask("hello")
        assert result.intent == "chat"
        assert "no model" in result.headline.lower()
        assert "models add-http" in result.next_step

    def test_a_simulated_reply_is_labelled(self, ws, model):
        result = ws.simple.ask("hello")
        assert result.simulated is True
        assert "(simulated)" in result.detail

    def test_a_workflow_without_its_grant_stops_and_grants_nothing(self, ws, model):
        root = ws.tool_roots()[0]
        with open(os.path.join(root, "notes.md"), "w", encoding="utf-8") as handle:
            handle.write("alpha beta\n")
        before = len(ws.permissions.grants())
        result = ws.simple.ask("run template summarise-file path=notes.md")
        assert result.intent == "workflow"
        assert result.headline.startswith("A step needs a permission")
        assert result.next_step and result.next_step.startswith("archx-agent approvals approve")
        assert result.data["approval_id"]
        assert len(ws.permissions.grants()) == before

    def test_a_workflow_runs_when_the_capability_is_granted(self, ws, model):
        root = ws.tool_roots()[0]
        with open(os.path.join(root, "notes.md"), "w", encoding="utf-8") as handle:
            handle.write("alpha beta\n")
        ws.permissions.grant("fs.read", subject="fs.read", duration="persistent", confirm=True)
        result = ws.simple.ask("run template summarise-file path=notes.md")
        assert result.intent == "workflow"
        assert result.headline.startswith("Ran summarise-file: completed")
        assert ws.workflows.get(result.data["workflow_id"]).status == "completed"

    def test_an_unknown_template_is_a_clear_error(self, ws):
        with pytest.raises(Exception) as exc:
            ws.simple.ask("run template does-not-exist")
        assert "does-not-exist" in str(getattr(exc.value, "message", exc.value))

    def test_template_inputs_must_be_key_value_pairs(self, ws):
        with pytest.raises(ValidationError) as exc:
            ws.simple.ask("run template summarise-file notakeyvalue")
        assert "key=value" in exc.value.message

    def test_a_workflow_that_needs_a_model_explains_it_instead_of_crashing(self, ws):
        root = ws.tool_roots()[0]
        with open(os.path.join(root, "notes.md"), "w", encoding="utf-8") as handle:
            handle.write("alpha beta\n")
        ws.permissions.grant("fs.read", subject="fs.read", duration="persistent", confirm=True)
        result = ws.simple.ask("run template summarise-file path=notes.md")
        assert result.intent == "workflow"
        assert result.headline.startswith("The workflow stopped: it has a model step")
        assert result.data["stopped"] == "WorkflowFailed"
        assert result.next_step.startswith("archx-agent models add-http")

    def test_a_workflow_failure_is_an_archx_error_not_a_bare_exception(self):
        from archx_agent.application.agent import WorkflowFailed
        from archx_agent.helpers.exceptions import ArchxError

        assert issubclass(WorkflowFailed, ArchxError)

    def test_a_quit_intent_is_not_an_error(self, ws):
        result = ws.simple.ask("/quit")
        assert result.intent == "quit" and result.headline == "Goodbye."


class TestSimpleResultShape:
    def test_a_result_serialises(self):
        result = SimpleResult(intent="search", why="because", headline="h", detail="d")
        payload = result.to_dict()
        json.dumps(payload)
        assert payload["intent"] == "search"
        assert payload["next_step"] is None
        assert payload["data"] == {}

    def test_simple_mode_is_constructed_from_the_workspace(self, ws):
        assert isinstance(ws.simple, SimpleMode)


# --------------------------------------------------------------------------
# the installed console script
# --------------------------------------------------------------------------
class TestSimpleCli:
    def _cli(self, home, *args, timeout=180, input_text=None):
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
        return home

    def test_ask_prints_the_answer_and_the_reason(self, tmp_path):
        home = self._home(tmp_path)
        assert self._cli(home, "models", "add-scripted", "--name", "sim").returncode == 0
        result = self._cli(home, "simple", "ask", "hello there")
        assert result.returncode == 0, result.stderr
        assert "why:" in result.stdout

    def test_ask_json_carries_the_intent(self, tmp_path):
        home = self._home(tmp_path)
        self._cli(home, "memory", "add", "--kind", "permanent", "--title", "Kafka",
                  "--content", "kafka is a log", "--category", "fact")
        payload = json.loads(self._cli(home, "--json", "simple", "ask",
                                       "where did I write about kafka").stdout)
        assert payload["intent"] == "search"
        assert payload["data"]["report"]["total"] >= 1

    def test_remember_through_the_cli(self, tmp_path):
        home = self._home(tmp_path)
        result = self._cli(home, "simple", "ask", "remember that the build is slow")
        assert result.returncode == 0
        assert "Stored as permanent" in result.stdout
        recalled = self._cli(home, "simple", "ask", "recall build")
        assert "slow" in recalled.stdout

    def test_status_and_help(self, tmp_path):
        home = self._home(tmp_path)
        status = self._cli(home, "simple", "status")
        assert status.returncode == 0 and "memory:" in status.stdout
        help_output = self._cli(home, "simple", "help")
        assert help_output.returncode == 0 and "remember that" in help_output.stdout

    def test_the_chat_loop_answers_and_stops(self, tmp_path):
        home = self._home(tmp_path)
        self._cli(home, "models", "add-scripted", "--name", "sim")
        session = self._cli(
            home, "simple",
            input_text="where did I write about kafka\n/help\n/quit\n",
        )
        assert session.returncode == 0, session.stderr
        assert "type /help" in session.stdout
        assert "could not find" in session.stdout
        assert "I can do six things" in session.stdout

    def test_json_without_a_subcommand_is_a_usage_error(self, tmp_path):
        home = self._home(tmp_path)
        result = self._cli(home, "--json", "simple")
        assert result.returncode == 2

    def test_a_usage_mistake_is_reported_without_a_traceback(self, tmp_path):
        home = self._home(tmp_path)
        result = self._cli(home, "simple", "ask", "remember that")
        assert result.returncode == 2
        assert "Traceback" not in result.stderr
        assert "error:" in result.stderr

    def test_a_missing_model_exits_zero_but_says_what_to_do(self, tmp_path):
        home = self._home(tmp_path)
        result = self._cli(home, "simple", "ask", "hello")
        assert result.returncode == 0
        assert "next:" in result.stdout
