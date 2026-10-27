"""End-to-end tests through the installed console script.

These exercise the real application boundary: argv in, stdout/exit code out,
with a real database and real trace file on disk.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

CLI = shutil.which("archx-agent") or str(
    (__import__("pathlib").Path(sys.executable).parent / "archx-agent")
)


def run(*args: str, home: str, allow_simulated: bool = False, timeout: int = 120):
    cmd = [CLI, "--home", home]
    if allow_simulated:
        cmd.append("--allow-simulated")
    cmd.extend(args)
    env = dict(os.environ)
    env.pop("ARCHX_PATHS_HOME", None)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)


@pytest.fixture()
def home(tmp_path):
    h = str(tmp_path / "home")
    result = run("init", home=h)
    assert result.returncode == 0, result.stderr
    return h


def _json(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestCliBasics:
    def test_version_and_help(self):
        out = subprocess.run([CLI, "--version"], capture_output=True, text=True)
        assert out.returncode == 0 and "Archx Agent" in out.stdout
        out = subprocess.run([CLI, "--help"], capture_output=True, text=True)
        assert "memory" in out.stdout and "chat" in out.stdout

    def test_init_creates_home(self, tmp_path):
        home = str(tmp_path / "new")
        result = run("init", home=home)
        assert result.returncode == 0
        assert os.path.exists(os.path.join(home, "archx.db"))
        assert os.path.exists(os.path.join(home, "config.json"))
        assert os.path.exists(os.path.join(home, "events.db"))

    def test_info_and_doctor(self, home):
        data = _json(run("info", "--json", home=home))
        assert data["schema_version"] == data["expected_schema_version"]
        doctor = run("doctor", home=home)
        assert "model catalogue" in doctor.stdout

    def test_config_roundtrip(self, home):
        assert run("config", "set", "model.temperature", "0.15", home=home).returncode == 0
        data = _json(run("config", "get", "model.temperature", "--json", home=home))
        assert data["value"] == 0.15
        bad = run("config", "set", "model.temperature", "hot", home=home)
        assert bad.returncode != 0
        assert "model.temperature" in bad.stderr

    def test_unknown_setting_is_rejected_by_name(self, home, tmp_path):
        path = os.path.join(home, "config.json")
        with open(path) as fh:
            cfg = json.load(fh)
        cfg["settings"]["nope.nope"] = 1
        with open(path, "w") as fh:
            json.dump(cfg, fh)
        result = run("info", home=home)
        assert result.returncode != 0
        assert "nope.nope" in result.stderr


class TestCliMemoryAcceptance:
    """M17 acceptance through the CLI with a real database."""

    def test_all_six_kinds_round_trip(self, home):
        conv = run("conv", "new", "M17", home=home).stdout.split()[2]
        cases = [
            ("active", "goal", ["--conversation", conv]),
            ("permanent", "preference", ["--tags", "style"]),
            ("archival", "history", []),
            ("project", "known_issue", ["--project", "proj_cli"]),
            (
                "solution",
                "solution",
                ["--verification", "verified", "--problem", "p", "--solution", "s", "--evidence", "e"],
            ),
            ("learning", "progress", ["--topic", "loops"]),
        ]
        ids = {}
        for kind, category, extra in cases:
            result = run(
                "memory", "add", "--kind", kind, "--category", category,
                "--title", f"{kind} title", "--content", f"{kind} content", *extra, "--json", home=home,
            )
            assert result.returncode == 0, result.stderr
            ids[kind] = json.loads(result.stdout)["id"]
        listed = _json(run("memory", "list", "--json", home=home))
        assert {m["kind"] for m in listed} == {k for k, _, _ in cases}
        for kind, memory_id in ids.items():
            shown = _json(run("memory", "show", memory_id, "--json", home=home))
            assert shown["kind"] == kind
            assert shown["provenance"]["origin"] == "user"
            assert shown["created_at"] and shown["updated_at"]

    def test_edit_delete_and_history(self, home):
        memory_id = json.loads(
            run(
                "memory", "add", "--kind", "permanent", "--category", "fact",
                "--title", "Editable", "--content", "version one", "--json", home=home,
            ).stdout
        )["id"]
        assert run("memory", "edit", memory_id, "--content", "version two", home=home).returncode == 0
        shown = _json(run("memory", "show", memory_id, "--json", home=home))
        assert shown["content"] == "version two"
        assert shown["version"] == 2
        assert shown["history"][0]["snapshot"]["content"] == "version one"
        assert run("memory", "delete", memory_id, home=home).returncode == 0
        assert run("memory", "show", memory_id, "--json", home=home).returncode == 0  # still inspectable
        assert _json(run("memory", "list", "--json", home=home)) == []

    def test_scope_isolation_between_projects(self, home):
        run("memory", "add", "--kind", "project", "--category", "build_command",
            "--title", "A build", "--content", "make a", "--project", "proj_a", home=home)
        run("memory", "add", "--kind", "project", "--category", "build_command",
            "--title", "B build", "--content", "make b", "--project", "proj_b", home=home)
        a = _json(run("memory", "list", "--json", "--kind", "project", "--project", "proj_a", home=home))
        assert [m["title"] for m in a] == ["A build"]

    def test_archival_never_injected_by_default(self, home):
        run("memory", "add", "--kind", "archival", "--category", "history",
            "--title", "Old note", "--content", "ancient history", home=home)
        default = _json(run("memory", "retrieve", "--budget", "500", "--json", home=home))
        assert default["included"] == []
        explicit = _json(
            run("memory", "retrieve", "--budget", "500", "--include-archival", "--json", home=home)
        )
        assert [i["kind"] for i in explicit["included"]] == ["archival"]

    def test_solution_cannot_be_faked_as_verified(self, home):
        result = run("memory", "add", "--kind", "solution", "--category", "solution",
                     "--title", "Guess", "--content", "maybe this", "--verification", "verified",
                     "--problem", "p", "--solution", "s", home=home)
        assert result.returncode != 0
        assert "evidence" in result.stderr

    def test_secret_is_refused(self, home):
        result = run("memory", "add", "--kind", "permanent", "--category", "fact",
                     "--title", "Key", "--content", "sk-abcdefghijklmnopqrstuvwx", home=home)
        assert result.returncode != 0
        assert "credential" in result.stderr.lower() or "secret" in result.stderr.lower()

    def test_persistence_across_processes(self, home):
        memory_id = json.loads(run("memory", "add", "--kind", "permanent", "--category", "fact",
                                   "--title", "Across runs", "--content", "still here", "--json",
                                   home=home).stdout)["id"]
        shown = _json(run("memory", "show", memory_id, "--json", home=home))
        assert shown["content"] == "still here"

    def test_every_write_appears_in_the_trace(self, home):
        memory_id = json.loads(run("memory", "add", "--kind", "permanent", "--category", "fact",
                                   "--title", "Traced", "--content", "x", "--json", home=home).stdout)["id"]
        run("memory", "edit", memory_id, "--content", "y", home=home)
        run("memory", "delete", memory_id, home=home)
        events = _json(run("trace", "list", "--kind", "memory", "--json", home=home))
        names = [e["name"] for e in events]
        assert "memory.added" in names
        assert "memory.updated" in names
        assert "memory.deleted" in names


class TestCliChat:
    def test_chat_with_simulated_model_is_labelled(self, home):
        assert run("models", "add-scripted", home=home).returncode == 0
        result = run("chat", "--message", "hello", "--json", home=home, allow_simulated=True)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["simulated"] is True
        assert "SIMULATED" in data["text"]
        assert data["manifest"]["budget"] > 0

    def test_chat_without_model_fails_clearly(self, home):
        result = run("chat", "--message", "hello", home=home)
        assert result.returncode != 0
        assert "no usable model" in result.stderr

    def test_flag_is_required_for_simulated_runtime(self, home):
        run("models", "add-scripted", home=home)
        result = run("chat", "--message", "hello", home=home)  # no --allow-simulated
        assert result.returncode != 0

    def test_conversation_flow(self, home):
        run("models", "add-scripted", home=home)
        first = json.loads(run("chat", "-m", "one", "--json", home=home, allow_simulated=True).stdout)
        conv_id = first["conversation_id"]
        run("chat", "-m", "two", "-c", conv_id, home=home, allow_simulated=True)
        shown = _json(run("conv", "show", conv_id, "--json", home=home))
        assert len(shown["messages"]) == 4
        assert run("conv", "search", "one", home=home).stdout.count(conv_id) >= 1
        assert run("conv", "rename", conv_id, "Renamed", home=home).returncode == 0
        assert run("conv", "export", conv_id, "--format", "markdown", home=home).stdout.startswith("# Renamed")


class TestCliContext:
    def test_oldest_first_manifest_and_history_preserved(self, home):
        run("models", "add-scripted", home=home)
        conv = json.loads(run("chat", "-m", "message one", "--json", home=home, allow_simulated=True).stdout)[
            "conversation_id"
        ]
        for i in range(6):
            run("chat", "-m", f"filler {i}" * 20, "-c", conv, home=home, allow_simulated=True)
        manifest = _json(
            run("context", "build", conv, "--strategy", "oldest_first", "--budget", "120", "--json", home=home)
        )
        assert manifest["tokens_used"] <= 120
        assert manifest["omitted"], "older messages must be reported as omitted"
        # nothing was deleted: the stored history still has 14 messages
        shown = _json(run("conv", "show", conv, "--json", home=home))
        assert len(shown["messages"]) == 14

    def test_manual_selection(self, home):
        run("models", "add-scripted", home=home)
        conv = json.loads(run("chat", "-m", "first", "--json", home=home, allow_simulated=True).stdout)[
            "conversation_id"
        ]
        run("chat", "-m", "second", "-c", conv, home=home, allow_simulated=True)
        shown = _json(run("conv", "show", conv, "--json", home=home))
        keep = shown["messages"][0]["id"]
        manifest = _json(
            run("context", "build", conv, "--strategy", "manual", "--manual-ids", keep, "--json", home=home)
        )
        included_refs = [i["ref_id"] for i in manifest["included"]]
        assert keep in included_refs
        assert any(o["reason"] == "not selected manually" for o in manifest["omitted"])

    def test_ai_proposed_requires_approval(self, home):
        run("models", "add-scripted", home=home)
        conv = json.loads(run("chat", "-m", "start", "--json", home=home, allow_simulated=True).stdout)[
            "conversation_id"
        ]
        for i in range(8):
            run("chat", "-m", f"long message {i} " * 15, "-c", conv, home=home, allow_simulated=True)
        proposal = _json(run("context", "propose", conv, "--budget", "100", "--json", home=home))
        assert proposal["requires_approval"] is True
        assert proposal["summarise"]
        # the proposal alone changed nothing
        before = _json(run("conv", "show", conv, "--json", home=home))
        assert len(before["messages"]) == 18

    def test_summarize_keeps_summary_and_sources(self, home):
        run("models", "add-scripted", home=home)
        conv = json.loads(run("chat", "-m", "first fact", "--json", home=home, allow_simulated=True).stdout)[
            "conversation_id"
        ]
        for i in range(8):
            run("chat", "-m", f"detail {i} " * 30, "-c", conv, home=home, allow_simulated=True)
        manifest = _json(
            run("context", "build", conv, "--strategy", "summarize", "--budget", "150", "--json",
                home=home, allow_simulated=True)
        )
        assert "summary" in (manifest["notes"] or "") or manifest["summarizer"] is not None or manifest["degraded"]
        summaries = _json(run("context", "summaries", conv, "--json", home=home))
        if summaries:
            assert summaries[0]["source_start_seq"] >= 1
        stored = _json(run("conv", "show", conv, "--json", home=home))
        assert len(stored["messages"]) == 18, "summarisation must not delete originals"


class TestCliEmbeddings:
    def _seed(self, home):
        body = (
            "The project stores memories in SQLite and searches them with keyword matching"
        )
        assert run("memory", "add", "--kind", "permanent", "--category", "fact",
                   "--title", "Storage engine", "--content", body, home=home).returncode == 0
        assert run("memory", "add", "--kind", "permanent", "--category", "preference",
                   "--title", "Units", "--content", "Always use metric units for measurements",
                   home=home).returncode == 0

    def test_disabled_by_default_and_status_explains_how_to_enable(self, home):
        status = _json(run("embeddings", "status", "--json", home=home))
        assert status["enabled"] is False
        assert "memory.embeddings_enabled" in status["hint"]
        assert status["states"] == {}, "nothing is embedded on a fresh home"

    def test_backfill_search_and_purge(self, home):
        self._seed(home)
        run("config", "set", "memory.embeddings_enabled", "true", home=home)
        status = _json(run("embeddings", "status", "--json", home=home))
        assert status["enabled"] is True
        assert status["provider"]["id"] == "local-hash"
        assert status["provider"]["semantic"] is False, (
            "the offline hash provider must not claim to be semantic"
        )
        backfill = _json(run("embeddings", "backfill", "--json", home=home))
        assert backfill["embedded"] >= 2
        hits = _json(run("embeddings", "search", "which database holds memories", "-k", "3",
                         "--threshold", "0", "--json", home=home))
        assert hits["results"], "vector search must return neighbours"
        assert hits["results"][0]["owner_type"] == "memory"
        # the neighbour ids must resolve to real memories whose text is about storage
        titles = [
            _json(run("memory", "show", hit["owner_id"], "--json", home=home))["title"]
            for hit in hits["results"]
        ]
        assert any("storage" in title.lower() for title in titles), titles
        purged = _json(run("embeddings", "purge", "--yes", "--json", home=home))
        assert purged["deleted"] >= 2
        assert _json(run("embeddings", "status", "--json", home=home))["states"] == {}

    def test_search_requires_enabled_embeddings(self, home):
        result = run("embeddings", "search", "anything", home=home)
        assert result.returncode != 0
        assert "disabled" in (result.stdout + result.stderr).lower()

    def test_retrieval_eval_harness_reports_all_three_modes(self, home, tmp_path):
        out = tmp_path / "report.md"
        result = run("eval", "retrieval", "--dataset", str(tmp_path / "missing.json"), home=home)
        assert result.returncode != 0, "a missing dataset must fail loudly"

        dataset = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "data", "retrieval_set.json")
        report = _json(run("eval", "retrieval", "--dataset", dataset, "--k", "5", "--json", home=home))
        assert {row["mode"] for row in report["modes"]} == {"keyword", "semantic", "hybrid"}
        assert report["size"] == {"corpus": 20, "queries": 12}
        for row in report["modes"]:
            assert 0.0 <= row["ndcg@k"] <= 1.0 and row["ndcg@k"] > 0.3
        hybrid = next(r for r in report["modes"] if r["mode"] == "hybrid")
        keyword = next(r for r in report["modes"] if r["mode"] == "keyword")
        assert hybrid["mrr"] >= keyword["mrr"], "hybrid ranking must not be worse than keyword on MRR"

        written = run("eval", "retrieval", "--dataset", dataset, "--k", "5", "--out", str(out), home=home)
        assert written.returncode == 0, written.stderr
        text = out.read_text()
        assert "| hybrid |" in text and "nDCG" in text


class TestCliContextStrategies:
    def test_summarize_reports_generator(self, home):
        run("models", "add-scripted", home=home)
        conv = json.loads(run("chat", "-m", "seed", "--json", home=home, allow_simulated=True).stdout)[
            "conversation_id"
        ]
        for i in range(8):
            run("chat", "-m", f"detail {i} " * 30, "-c", conv, home=home, allow_simulated=True)
        _json(run("context", "build", conv, "--strategy", "summarize", "--budget", "150",
                  "--json", home=home, allow_simulated=True))
        summaries = _json(run("context", "summaries", conv, "--json", home=home))
        assert summaries
        assert summaries[0]["generator"] == "simulated-test-double", (
            "a simulated summary must never be presented as a model summary"
        )

    def test_rejected_proposal_cannot_be_applied(self, home):
        run("models", "add-scripted", home=home)
        conv = json.loads(run("chat", "-m", "seed", "--json", home=home, allow_simulated=True).stdout)[
            "conversation_id"
        ]
        for i in range(8):
            run("chat", "-m", f"padding {i} " * 20, "-c", conv, home=home, allow_simulated=True)
        proposal = _json(run("context", "propose", conv, "--budget", "100", "--json", home=home))
        assert run("context", "reject", proposal["id"], "--reason", "keep history", home=home).returncode == 0
        result = run("context", "build", conv, "--strategy", "ai_proposed", "--proposal", proposal["id"],
                     "--budget", "100", home=home, allow_simulated=True)
        assert result.returncode != 0
        shown = _json(run("conv", "show", conv, "--json", home=home))
        assert len(shown["messages"]) == 18


class TestCliProviders:
    def test_local_provider_flow_and_usage(self, home, stub_server):
        base, handler = stub_server
        handler.routes = {
            "GET /v1/models": (200, {"data": [{"id": "protocol-stub"}]}),
            "POST /v1/chat/completions": (
                200,
                {
                    "id": "x",
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": "hello from the stub"},
                         "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                },
            ),
        }
        added = _json(run("providers", "add", "local-llama", "--template", "openai-compatible-local",
                          "--base-url", f"{base}/v1", "--json", home=home))
        assert added["is_local"] is True
        assert added["blocking_reason"] is None, "a loopback endpoint needs no consent"

        privacy = _json(run("providers", "privacy", "--json", home=home))
        assert privacy[0]["data_leaves_device"] is False

        checked = _json(run("providers", "check", "local-llama", "--json", home=home))
        assert checked["status"] == "reachable"
        assert checked["models_seen"] == 1

        run("models", "add-http", "--name", "stub", "--base-url", f"{base}/v1", "--model", "protocol-stub",
            home=home)
        reply = _json(run("chat", "-m", "hi", "--json", home=home))
        assert reply["text"] == "hello from the stub"
        assert reply["model"]["local"] is True

        usage = _json(run("providers", "usage", "local-llama", "--json", home=home))
        assert usage["requests"] == 1
        assert usage["tokens_in"] == 11 and usage["tokens_out"] == 7
        assert usage["estimated_cost"] is None, "no prices configured means no cost estimate"

    def test_cloud_provider_requires_confirmation_then_consent(self, home):
        added = _json(run("providers", "add", "cloud", "--template", "openai", "--json", home=home))
        assert added["data_leaves_device"] is True
        assert "confirm" in added["blocking_reason"]

        refused = run("providers", "consent", "cloud", home=home)
        assert refused.returncode != 0
        assert "not confirmed" in refused.stderr

        run("providers", "confirm", "cloud", "--data-leaves-device", "yes",
            "--retention", "vendor: 30 days", home=home)
        assert run("providers", "consent", "cloud", "--note", "accepted", home=home).returncode == 0
        after = _json(run("providers", "show", "cloud", "--json", home=home))
        assert after["consented"] is True and after["blocking_reason"] is None
        assert after["effective_privacy"]["sources"]["data_leaves_device"] == "user-confirmed"

        run("providers", "revoke", "cloud", home=home)
        revoked = _json(run("providers", "show", "cloud", "--json", home=home))
        assert revoked["consented"] is False and revoked["blocking_reason"]

    def test_raw_key_is_rejected_and_never_stored(self, home):
        result = run("providers", "add", "bad", "--base-url", "https://example.invalid/v1",
                     "--auth-ref", "sk-live-abcdef1234567890", home=home)
        assert result.returncode != 0
        assert "reference" in (result.stdout + result.stderr)
        listed = run("providers", "list", "--json", home=home).stdout
        assert "sk-live-abcdef" not in listed

    def test_quota_is_reported(self, home):
        run("providers", "add", "local-llama", "--template", "openai-compatible-local", home=home)
        assert run("providers", "quota", "local-llama", "--requests-per-day", "3", home=home).returncode == 0
        quota = _json(run("providers", "quota", "local-llama", "--json", home=home))
        assert quota == {"max_requests_per_day": 3}

    def test_remote_model_is_refused_until_opted_in(self, home):
        run("models", "add-http", "--name", "remote", "--base-url", "https://api.openai.com/v1",
            "--model", "gpt-x", home=home)
        models = _json(run("models", "list", "--json", home=home))
        model_id = next(m["id"] for m in models if m["name"] == "remote")
        result = run("chat", "--model", model_id, "-m", "hello", home=home)
        assert result.returncode != 0
        assert "local_only" in result.stderr


class TestCliRouting:
    def test_route_explains_choices_and_refusals(self, home):
        run("models", "add-scripted", "--name", "sim", home=home)
        decision = _json(run("models", "route", "--json", home=home, allow_simulated=True))
        assert decision["chosen_name"] == "sim"
        assert decision["acceptable"] is True
        assert decision["policy"]["allow_cloud"] is False
        assert "explanation" in decision and "chat" in decision["explanation"]

    def test_no_model_is_a_clear_failure(self, home):
        result = run("models", "route", home=home)
        assert result.returncode != 0
        assert "no usable model" in result.stderr
        assert "models add-http" in result.stderr

    def test_probe_changes_the_capability_state(self, home):
        run("models", "add-scripted", "--name", "sim", home=home)
        before = _json(run("models", "capabilities", "sim", "--json", home=home))
        assert before["capabilities"]["chat"]["state"] == "inferred"
        probed = _json(run("models", "probe", "sim", "--capability", "chat", "--json",
                           home=home, allow_simulated=True))
        assert probed["outcome"] == "passed"
        assert probed["state_after"]["state"] == "verified"
        after = _json(run("models", "capabilities", "sim", "--json", home=home))
        assert after["capabilities"]["chat"]["state"] == "verified"
        assert "probe passed" in after["capabilities"]["chat"]["basis"]

    def test_probe_rejects_an_unmeasurable_capability(self, home):
        run("models", "add-scripted", "--name", "sim", home=home)
        result = run("models", "probe", "sim", "--capability", "vision", home=home, allow_simulated=True)
        assert result.returncode != 0
        assert "invalid choice" in result.stderr

    def test_require_verified_policy_gates_routing(self, home):
        run("models", "add-scripted", "--name", "sim", home=home)
        run("config", "set", "router.require_verified", "true", home=home)
        refused = run("models", "route", home=home, allow_simulated=True)
        assert refused.returncode != 0
        assert "not verified" in refused.stderr
        run("models", "probe", "sim", "--capability", "chat", home=home, allow_simulated=True)
        ok = _json(run("models", "route", "--json", home=home, allow_simulated=True))
        assert ok["chosen_name"] == "sim"

    def test_capability_regression_is_never_routed(self, home):
        run("models", "add-scripted", "--name", "sim", home=home)
        models = _json(run("models", "list", "--json", home=home))
        model_id = models[0]["id"]
        # measure a failure, then prove the router refuses the model
        from archx_agent.application.workspace import open_workspace

        with open_workspace(home=home) as ws:
            ws.models.record_capability_test(model_id, "chat", "failed", detail="measured broken")
        result = run("models", "route", home=home, allow_simulated=True)
        assert result.returncode != 0
        assert "unsupported" in result.stderr


class TestCliTools:
    def _run_id(self, result):
        return _json(result)

    def test_tools_list_shows_capabilities_and_risk(self, home):
        out = run("tools", "list", home=home).stdout
        assert "fs.write" in out and "medium" in out and "shell.run" in out
        registry = _json(run("tools", "list", "--json", home=home))
        write = next(row for row in registry if row["name"] == "fs.write")
        assert write["capability"] == "fs.write"
        assert write["supports_dry_run"] is True

    def test_denied_run_is_exit_4_and_names_the_approval(self, home):
        result = run("tools", "run", "fs.write", "--arg", "path=note.md", "--arg", "content=hello",
                     home=home)
        assert result.returncode == 4
        assert "denied" in result.stderr
        assert "approvals approve" in result.stderr
        pending = _json(run("approvals", "list", "--json", home=home))
        assert len(pending) == 1 and pending[0]["capability"] == "fs.write"

    def test_approve_then_run_writes_the_file(self, home):
        run("tools", "run", "fs.write", "--arg", "path=note.md", "--arg", "content=hello", home=home)
        approval = _json(run("approvals", "list", "--json", home=home))[0]["id"]
        approved = run("approvals", "approve", approval, home=home)
        assert approved.returncode == 0 and "approved" in approved.stdout
        result = run("tools", "run", "fs.write", "--arg", "path=note.md", "--arg", "content=hello",
                     "--json", home=home)
        assert result.returncode == 0, result.stderr
        payload = _json(result)
        assert payload["status"] == "succeeded"
        assert os.path.exists(os.path.join(home, "workspace", "note.md"))
        assert open(os.path.join(home, "workspace", "note.md")).read() == "hello"

    def test_single_use_grant_is_consumed_after_one_run(self, home):
        run("tools", "run", "fs.write", "--arg", "path=a.txt", "--arg", "content=x", home=home)
        approval = _json(run("approvals", "list", "--json", home=home))[0]["id"]
        run("approvals", "approve", approval, home=home)
        assert run("tools", "run", "fs.write", "--arg", "path=a.txt", "--arg", "content=x",
                   home=home).returncode == 0
        assert run("tools", "run", "fs.write", "--arg", "path=a.txt", "--arg", "content=x",
                   home=home).returncode == 4

    def test_persistent_grant_needs_confirm(self, home):
        refused = run("permissions", "grant", "fs.read", "--subject", "fs.read",
                      "--duration", "persistent", home=home)
        assert refused.returncode == 2
        assert "--confirm" in refused.stderr
        granted = run("permissions", "grant", "fs.read", "--subject", "fs.read",
                      "--duration", "persistent", "--confirm", home=home)
        assert granted.returncode == 0
        assert "persistent" in granted.stdout

    def test_check_reports_denied_then_allowed(self, home):
        denied = run("permissions", "check", "fs.read", "--subject", "fs.read", home=home)
        assert denied.returncode == 4 and "denied" in denied.stdout
        run("permissions", "grant", "fs.read", "--subject", "fs.read", home=home)
        allowed = run("permissions", "check", "fs.read", "--subject", "fs.read", home=home)
        assert allowed.returncode == 0 and "allowed" in allowed.stdout

    def test_check_creates_no_approval_request(self, home):
        run("permissions", "check", "fs.read", "--subject", "fs.read", home=home)
        assert _json(run("approvals", "list", "--json", home=home)) == []

    def test_revoke_then_check_is_denied_again(self, home):
        grant = _json(run("permissions", "grant", "fs.read", "--subject", "fs.read",
                          "--json", home=home))
        assert run("permissions", "revoke", grant["id"], home=home).returncode == 0
        assert run("permissions", "check", "fs.read", "--subject", "fs.read", home=home).returncode == 4

    def test_runs_history_lists_denials_and_successes(self, home):
        run("tools", "run", "fs.write", "--arg", "path=a.txt", "--arg", "content=x", home=home)
        approval = _json(run("approvals", "list", "--json", home=home))[0]["id"]
        run("approvals", "approve", approval, home=home)
        run("tools", "run", "fs.write", "--arg", "path=a.txt", "--arg", "content=x", home=home)
        rows = _json(run("tools", "runs", "--json", home=home))
        assert [row["status"] for row in rows] == ["succeeded", "denied"]
        assert [row["seq"] for row in rows] == [2, 1]

    def test_unknown_argument_is_a_usage_error(self, home):
        result = run("tools", "run", "fs.read", "--arg", "pth=x", home=home)
        assert result.returncode == 2
        assert "does not take pth" in result.stderr

    def test_dry_run_does_not_touch_the_disk(self, home):
        run("permissions", "grant", "fs.write", "--subject", "fs.write", home=home)
        result = run("tools", "run", "fs.write", "--arg", "path=preview.txt",
                     "--arg", "content=x", "--dry-run", "--json", home=home)
        assert result.returncode == 0
        assert _json(result)["dry_run"] is True
        assert not os.path.exists(os.path.join(home, "workspace", "preview.txt"))

    def test_approval_can_be_denied_and_a_new_request_appears(self, home):
        run("tools", "run", "fs.delete", "--arg", "path=x", home=home)
        first = _json(run("approvals", "list", "--json", home=home))[0]["id"]
        denied = run("approvals", "deny", first, "--reason", "no", home=home)
        assert denied.returncode == 0 and "no grant" in denied.stdout
        run("tools", "run", "fs.delete", "--arg", "path=x", home=home)
        second = _json(run("approvals", "list", "--json", home=home))[0]["id"]
        assert second != first

    def test_tool_show_lists_inputs_and_roots(self, home):
        result = run("tools", "show", "fs.write", home=home)
        assert result.returncode == 0
        assert "content" in result.stdout and "roots:" in result.stdout
