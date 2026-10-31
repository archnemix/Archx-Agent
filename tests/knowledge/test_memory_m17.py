from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from archx_agent.helpers.exceptions import DuplicateError, NotFoundError, ValidationError
from archx_agent.helpers.sqlite_store import SqliteStore
from archx_agent.helpers.write_coordinator import WriteCoordinator
from archx_agent.managers.memory import KINDS, MemoryManager


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class TestConversationBasics:
    def test_create_append_order_and_reload(self, domain):
        conv = domain.conversations.create("Test chat")
        for i in range(5):
            domain.conversations.append_message(conv.id, "user" if i % 2 == 0 else "assistant", f"msg {i}")
        messages = domain.conversations.messages(conv.id)
        assert [m.seq for m in messages] == [1, 2, 3, 4, 5]
        assert [m.content for m in messages] == [f"msg {i}" for i in range(5)]
        # reopening the same file sees the same order (sequence, not timestamp)
        reopened = SqliteStore(domain.path)
        rows = reopened.query("SELECT seq, content FROM messages WHERE conversation_id=? ORDER BY seq", (conv.id,))
        assert [r["content"] for r in rows] == [f"msg {i}" for i in range(5)]
        reopened.close()

    def test_clear_context_preserves_history(self, domain):
        conv = domain.conversations.create("ctx")
        for i in range(3):
            domain.conversations.append_message(conv.id, "user", f"m{i}")
        hidden = domain.conversations.clear_context(conv.id)
        assert hidden == 3
        assert domain.conversations.messages(conv.id) == []
        assert len(domain.conversations.messages(conv.id, include_excluded=True)) == 3
        domain.conversations.restore_context(conv.id)
        assert len(domain.conversations.messages(conv.id)) == 3

    def test_soft_delete_then_restore(self, domain):
        conv = domain.conversations.create("bye")
        assert domain.conversations.delete(conv.id) == "soft_deleted"
        assert domain.conversations.get(conv.id).is_err
        assert domain.conversations.get(conv.id, include_deleted=True).is_ok
        domain.conversations.restore(conv.id)
        assert domain.conversations.get(conv.id).is_ok

    def test_hard_delete_requires_confirmation(self, domain):
        conv = domain.conversations.create("gone")
        domain.conversations.append_message(conv.id, "user", "x")
        with pytest.raises(ValidationError):
            domain.conversations.delete(conv.id, hard=True)
        assert domain.conversations.delete(conv.id, hard=True, confirm=True) == "hard_deleted"
        assert domain.conversations.messages(conv.id) == []

    def test_validation(self, domain):
        with pytest.raises(NotFoundError):
            domain.conversations.append_message("nope", "user", "hi")
        conv = domain.conversations.create("v")
        with pytest.raises(ValidationError):
            domain.conversations.append_message(conv.id, "wizard", "hi")
        with pytest.raises(ValidationError):
            domain.conversations.rename(conv.id, "   ")
        with pytest.raises(NotFoundError):
            domain.conversations.append_message("missing", "user", "hi")

    def test_search_finds_title_and_messages(self, domain):
        a = domain.conversations.create("Rust ownership")
        domain.conversations.append_message(a.id, "user", "explain borrow checker")
        b = domain.conversations.create("Python packaging")
        domain.conversations.append_message(b.id, "user", "how do I build a wheel")
        assert [h["conversation_id"] for h in domain.conversations.search("Rust")] == [a.id]
        assert [h["conversation_id"] for h in domain.conversations.search("wheel")] == [b.id]
        assert domain.conversations.search("") == []

    def test_export_formats(self, domain):
        conv = domain.conversations.create("Export me")
        domain.conversations.append_message(conv.id, "user", "hello")
        data = json.loads(domain.conversations.export(conv.id))
        assert data["conversation"]["title"] == "Export me"
        assert data["messages"][0]["content"] == "hello"
        md = domain.conversations.export(conv.id, fmt="markdown")
        assert "# Export me" in md and "hello" in md
        with pytest.raises(ValidationError):
            domain.conversations.export(conv.id, fmt="pdf")

    def test_pinning_protects_from_clear(self, domain):
        conv = domain.conversations.create("pin")
        m1 = domain.conversations.append_message(conv.id, "user", "keep me", pinned=True)
        domain.conversations.append_message(conv.id, "user", "drop me")
        domain.conversations.clear_context(conv.id)
        remaining = domain.conversations.messages(conv.id)
        assert [m.id for m in remaining] == [m1.id]


class TestProjects:
    def test_create_and_identity(self, domain):
        p = domain.projects.create("Archx Demo", description="demo")
        assert p.slug == "archx-demo"
        assert domain.projects.get(p.id).is_ok
        assert domain.projects.by_slug("archx-demo").is_ok
        with pytest.raises(ValidationError):
            domain.projects.create("Archx Demo")  # duplicate slug
        with pytest.raises(ValidationError):
            domain.projects.create("Bad Slug", slug="Not Valid!")

    def test_project_path_containment(self, domain):
        with pytest.raises(Exception):
            domain.projects.create("Escape", root_path="../../etc")

    def test_list_and_archive(self, domain):
        a = domain.projects.create("A")
        b = domain.projects.create("B")
        assert {p.id for p in domain.projects.list()} == {a.id, b.id}
        domain.projects.archive(a.id)
        assert {p.id for p in domain.projects.list()} == {b.id}
        assert domain.projects.delete(b.id) == "soft_deleted"
        assert domain.projects.list() == []


def _make_active(domain, conv_id, title="current goal", content="Finish M17", **kw):
    return domain.memory.add(
        "active", title, content, category="goal", conversation_id=conv_id, source="user", **kw
    )


class TestMemoryKinds:
    def test_active_memory_requires_conversation_or_task(self, domain):
        with pytest.raises(ValidationError):
            domain.memory.add("active", "goal", "text", category="goal")

    def test_active_memory_ttl_and_expiry(self, domain):
        conv = domain.conversations.create("c")
        result = _make_active(domain, conv.id)
        memory = result.ok_or_raise()
        assert memory.scope == "conversation" and memory.scope_id == conv.id
        assert memory.expires_at is not None
        future = datetime.now(timezone.utc) + timedelta(minutes=1000)
        counts = domain.memory.apply_retention(now=future)
        assert counts["expired_active"] == 1
        assert domain.memory.require(memory.id).status == "expired"
        assert domain.memory.list(kinds=["active"], conversation_id=conv.id) == []

    def test_permanent_memory_rules(self, domain):
        ok = domain.memory.add(
            "permanent", "Prefers metric units", "Always use metric units.", category="preference"
        ).ok_or_raise()
        assert ok.scope == "global"
        with pytest.raises(ValidationError):
            domain.memory.add("permanent", "note", "x", category="note")
        with pytest.raises(ValidationError):
            domain.memory.add(
                "permanent", "API key", "sk-abcdefghijklmnopqrstuvwx", category="fact"
            )

    def test_archival_not_injected(self, domain):
        conv = domain.conversations.create("c")
        domain.memory.add(
            "archival",
            "Old design notes",
            "We used to use JSON files.",
            category="history",
            conversation_id=conv.id,
            provenance={"origin": "user", "uri": "file:///notes.md"},
        )
        result = domain.memory.retrieve_for_context(budget_tokens=500, conversation_id=conv.id)
        assert result.items == []
        with_archival = domain.memory.retrieve_for_context(
            budget_tokens=500, conversation_id=conv.id, include_archival=True
        )
        assert [m.kind for m in with_archival.items] == ["archival"]

    def test_archival_requires_provenance_origin(self, domain):
        memory = domain.memory.add(
            "archival", "No provenance", "text", category="history"
        ).ok_or_raise()
        assert memory.provenance["origin"] == "user"

    def test_project_memory_isolation(self, domain):
        p1 = domain.projects.create("One")
        p2 = domain.projects.create("Two")
        domain.memory.add(
            "project", "Build command", "pytest -q", category="build_command", project_id=p1.id
        ).ok_or_raise()
        domain.memory.add(
            "project", "Known issue", "flaky test", category="known_issue", project_id=p2.id
        ).ok_or_raise()
        p1_items = domain.memory.list(kinds=["project"], project_id=p1.id)
        p2_items = domain.memory.list(kinds=["project"], project_id=p2.id)
        assert [m.title for m in p1_items] == ["Build command"]
        assert [m.title for m in p2_items] == ["Known issue"]
        result = domain.memory.retrieve_for_context(budget_tokens=500, project_id=p1.id)
        assert {m.project_id for m in result.items} == {p1.id}
        with pytest.raises(ValidationError):
            domain.memory.add("project", "no project", "x", category="note")
        with pytest.raises(ValidationError):
            domain.memory.add(
                "project", "wrong scope", "x", category="note", scope="global", project_id=p1.id
            )

    def test_solution_verification_gate(self, domain):
        with pytest.raises(ValidationError):
            domain.memory.add(
                "solution", "Fix", "Use os.replace", category="solution", verification="unverified"
            )
        with pytest.raises(ValidationError):
            domain.memory.add(
                "solution",
                "Fix",
                "Use os.replace",
                category="solution",
                verification="verified",
                details={"problem": "partial writes", "solution": "os.replace"},
            )
        verified = domain.memory.add(
            "solution",
            "Atomic file write",
            "Write to temp then os.replace.",
            category="solution",
            verification="verified",
            details={
                "problem": "partial writes on crash",
                "solution": "temp file + os.replace",
                "evidence": ["test_atomic_write passed on 3.11"],
                "environment": "linux, python 3.11",
                "limitations": "same filesystem only",
            },
            evidence=[{"kind": "test", "ref": "tests/test_storage.py::test_atomic"}],
        ).ok_or_raise()
        assert verified.verification == "verified"
        # unverified solutions are not injected
        unverified = domain.memory.add(
            "solution",
            "Maybe fix",
            "Try increasing timeout.",
            category="solution",
            verification="unverified",
            details={"problem": "timeouts", "solution": "increase timeout"},
        ).ok_or_raise()
        result = domain.memory.retrieve_for_context(budget_tokens=500, query="atomic file write")
        ids = [m.id for m in result.items]
        assert verified.id in ids
        assert unverified.id not in ids

    def test_solution_retirement(self, domain):
        sol = domain.memory.add(
            "solution",
            "Old fix",
            "Use X",
            category="solution",
            verification="reported",
            details={"problem": "p", "solution": "s", "evidence": ["forum post"]},
        ).ok_or_raise()
        retired = domain.memory.retire(sol.id, reason="did not work on 3.13")
        assert retired.status == "retired"
        assert retired.details["retire_reason"] == "did not work on 3.13"

    def test_learning_memory_and_profile(self, domain):
        entry = domain.memory.add(
            "learning",
            "Recursion basics",
            "Completed first exercises; struggled with base cases.",
            category="progress",
            details={"topic": "recursion", "outcome": "failed", "attempts": 1},
        ).ok_or_raise()
        assert entry.scope == "learner"
        with pytest.raises(ValidationError):
            domain.memory.add("learning", "x", "y", category="progress")
        with pytest.raises(ValidationError):
            domain.memory.add(
                "learning",
                "x",
                "y",
                category="progress",
                details={"topic": "recursion", "permanent_label": "bad at recursion"},
            )
        domain.memory.record_learning_event(topic="recursion", outcome="failed")
        profile_one = domain.memory.learner_profile()
        # a single failure is not a weakness label
        assert profile_one["needs_practice"] == []
        domain.memory.record_learning_event(topic="recursion", outcome="failed")
        profile_two = domain.memory.learner_profile()
        assert profile_two["needs_practice"] == ["recursion"]
        domain.memory.record_learning_event(topic="loops", outcome="passed")
        domain.memory.record_learning_event(topic="loops", outcome="passed")
        assert "loops" in domain.memory.learner_profile()["strengths"]

    def test_unknown_kind_and_category(self, domain):
        with pytest.raises(ValidationError):
            domain.memory.add("dream", "x", "y", category="note")
        with pytest.raises(ValidationError):
            domain.memory.add("permanent", "x", "y", category="nonsense")


class TestMemoryGovernance:
    def test_edit_creates_history_and_bumps_version(self, domain):
        memory = domain.memory.add("permanent", "Editor", "vim", category="preference").ok_or_raise()
        updated = domain.memory.update(memory.id, content="neovim", change="user-edit")
        assert updated.version == 2
        assert updated.content == "neovim"
        history = domain.memory.history(memory.id)
        assert len(history) == 1
        assert history[0]["snapshot"]["content"] == "vim"
        assert history[0]["change"] == "user-edit"

    def test_delete_soft_and_hard(self, domain):
        a = domain.memory.add("permanent", "A", "a", category="fact").ok_or_raise()
        b = domain.memory.add("permanent", "B", "b", category="fact").ok_or_raise()
        assert domain.memory.delete(a.id) == "deleted"
        assert domain.memory.get(a.id).is_err
        assert domain.memory.get(a.id, include_deleted=True).is_ok
        assert domain.memory.delete(b.id, hard=True) == "hard_deleted"
        assert domain.memory.get(b.id, include_deleted=True).is_err
        assert domain.store.scalar("SELECT COUNT(*) FROM memories WHERE id=?", (b.id,)) == 0
        assert any(h["change"] == "hard_deleted" for h in domain.memory.history(b.id))

    def test_duplicate_detection_exact_and_fuzzy(self, domain):
        first = domain.memory.add("permanent", "Prefers tabs", "Use tabs in Go code", category="preference").ok_or_raise()
        exact = domain.memory.add("permanent", "Prefers tabs", "Use tabs in Go code", category="preference")
        assert exact.is_err and isinstance(exact.error, DuplicateError)
        assert exact.error.context["existing_id"] == first.id
        fuzzy = domain.memory.add(
            "permanent", "Prefers tabs", "Use tabs in Go code, always", category="preference"
        )
        assert fuzzy.is_err and isinstance(fuzzy.error, DuplicateError)
        allowed = domain.memory.add(
            "permanent", "Prefers tabs", "Use tabs in Go code", category="preference", allow_duplicate=True
        )
        assert allowed.is_ok

    def test_slot_supersedes_previous(self, domain):
        conv = domain.conversations.create("slot")
        g1 = _make_active(domain, conv.id, content="Goal A", slot="current_goal").ok_or_raise()
        g2 = _make_active(domain, conv.id, content="Goal B", slot="current_goal").ok_or_raise()
        assert domain.memory.require(g1.id).status == "superseded"
        assert g2.supersedes == g1.id
        assert [m.content for m in domain.memory.list(kinds=["active"], conversation_id=conv.id)] == ["Goal B"]

    def test_search_scoring_and_degraded_flag(self, domain):
        domain.memory.add(
            "permanent", "Python version", "Prefer Python 3.11 for this project", category="preference"
        ).ok_or_raise()
        domain.memory.add("permanent", "Editor", "Neovim with LSP", category="preference").ok_or_raise()
        outcome = domain.memory.search("python")
        assert outcome.hits and outcome.hits[0].memory.title == "Python version"
        assert outcome.mode == "keyword"
        assert outcome.degraded in (True, False)
        if outcome.degraded:
            assert "semantic" in (outcome.degraded_reason or "")

    def test_retrieval_budget_and_manifest(self, domain):
        conv = domain.conversations.create("budget")
        _make_active(domain, conv.id, content="A" * 400)
        for i in range(10):
            domain.memory.add(
                "permanent", f"Fact {i}", "x" * 200, category="fact", allow_duplicate=True
            ).ok_or_raise()
        result = domain.memory.retrieve_for_context(budget_tokens=120, conversation_id=conv.id)
        assert result.tokens_used <= 120
        assert result.budget == 120
        assert result.included and all("reason" in item for item in result.included)
        assert result.omitted  # something had to be left out
        assert sum(item["tokens"] for item in result.included) == result.tokens_used

    def test_retrieval_is_traced(self, domain):
        conv = domain.conversations.create("traced")
        memory = _make_active(domain, conv.id).ok_or_raise()
        domain.memory.retrieve_for_context(budget_tokens=500, conversation_id=conv.id)
        domain.events.flush()
        events = domain.events.query(kind="memory")
        names = [e.name for e in events]
        assert "memory.added" in names
        retrieved = [e for e in events if e.name == "memory.retrieved"]
        assert retrieved and memory.id in retrieved[0].payload["included"]
        rows = domain.store.query("SELECT * FROM memory_retrievals WHERE memory_id=?", (memory.id,))
        assert rows and rows[0]["conversation_id"] == conv.id
        assert domain.memory.require(memory.id).access_count == 1

    def test_sources_and_provenance(self, domain):
        memory = domain.memory.add(
            "archival",
            "RFC 2119",
            "MUST/SHOULD semantics",
            category="history",
            provenance={"origin": "web", "uri": "https://www.rfc-editor.org/rfc/rfc2119"},
        ).ok_or_raise()
        domain.memory.add_source(
            memory.id, source_type="web", reference="https://www.rfc-editor.org/rfc/rfc2119", excerpt="MUST means..."
        )
        sources = domain.memory.sources(memory.id)
        assert sources[0]["reference"].startswith("https://www.rfc-editor.org")
        assert memory.provenance["origin"] == "web"
        with pytest.raises(ValidationError):
            domain.memory.add_source(memory.id, source_type="psychic")

    def test_artifact_round_trip_and_checksum(self, domain):
        memory = domain.memory.add("archival", "Log", "big log attached", category="history").ok_or_raise()
        path = domain.memory.attach_artifact(memory.id, b"line1\nline2\n", filename="run.log")
        assert path.endswith("run.log")
        assert domain.memory.read_artifact(memory.id) == b"line1\nline2\n"
        with open(path, "wb") as fh:
            fh.write(b"tampered")
        with pytest.raises(ValidationError):
            domain.memory.read_artifact(memory.id)

    def test_path_traversal_in_artifact_name(self, domain):
        memory = domain.memory.add("archival", "Esc", "x", category="history").ok_or_raise()
        path = domain.memory.attach_artifact(memory.id, b"x", filename="../../evil.sh")
        # the traversal is neutralised: the file must stay inside the memory directory
        assert str(domain.artifacts / "memory" / memory.id) in path
        assert ".." not in path

    def test_crash_replay_of_memory_write(self, domain):
        """A memory write accepted before a crash is replayed exactly once."""
        from archx_agent.managers.memory import MemoryManager as MM

        payload = {
            "memory": {
                "id": "mem_crash",
                "kind": "permanent",
                "scope": "global",
                "scope_id": None,
                "slot": None,
                "title": "Crash survivor",
                "content": "written before crash",
                "category": "fact",
                "source": "user",
                "provenance": {"origin": "user"},
                "confidence": 0.9,
                "status": "active",
                "pinned": False,
                "tags": "[]",
                "details": "{}",
                "evidence": "[]",
                "worked": None,
                "checksum": "abc",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
            "supersede_ids": [],
        }
        op = domain.coordinator.begin_durable("memory.add", payload)
        # simulate crash: a new coordinator replays intents
        co2 = WriteCoordinator(domain.store, name="replay")
        MM(domain.store, co2, events=domain.events, artifacts_root=str(domain.artifacts))
        assert co2.replay() == 1
        assert domain.store.scalar("SELECT COUNT(*) FROM memories WHERE id='mem_crash'") == 1
        assert co2.replay() == 0
        co2.stop()
        del op

    def test_survives_restart(self, domain, tmp_path):
        conv = domain.conversations.create("restart")
        memory = _make_active(domain, conv.id, content="survive restart").ok_or_raise()
        domain.coordinator.stop()
        domain.store.close()

        store = SqliteStore(domain.path)
        co = WriteCoordinator(store, name="restarted")
        manager = MemoryManager(store, co, artifacts_root=str(domain.artifacts))
        loaded = manager.require(memory.id)
        assert loaded.content == "survive restart"
        assert loaded.scope_id == conv.id
        co.stop()
        store.close()
        # reconnect the fixture's manager so teardown works
        domain.store = SqliteStore(domain.path)
        domain.coordinator = WriteCoordinator(domain.store, name="post")

    def test_policy_documents_every_kind(self, domain):
        policy = MemoryManager.policy()
        assert set(policy) == set(KINDS)
        for kind, entry in policy.items():
            assert entry["purpose"] and entry["scope"] and entry["requires"]
        assert policy["archival"]["injected"] is False

    def test_every_write_is_traced(self, domain):
        domain.memory.add("permanent", "T", "trace me", category="fact").ok_or_raise()
        domain.events.flush()
        names = [e.name for e in domain.events.query(kind="memory")]
        assert "memory.added" in names

    def test_stats(self, domain):
        domain.memory.add("permanent", "S", "s", category="fact").ok_or_raise()
        stats = domain.memory.stats()
        assert stats["by_kind"]["permanent"] == 1
        assert set(stats["by_kind"]) == set(KINDS)
