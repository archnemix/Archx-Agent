from __future__ import annotations

import pytest

from archx_agent.helpers.exceptions import ContextOverflowError, ValidationError
from archx_agent.managers.context import ContextManager, STRATEGIES


@pytest.fixture()
def ctx(domain):
    manager = ContextManager(
        domain.store,
        domain.coordinator,
        events=domain.events,
        conversations=domain.conversations,
        memory=domain.memory,
        context_limit=400,
        output_budget=100,
        reserve_tokens=50,
        memory_budget_ratio=0.25,
        default_strategy="oldest_first",
        summarizer=lambda messages, instruction: "SUMMARY: " + " | ".join(m.content[:24] for m in messages[:3]),
    )
    domain.context = manager
    manager.store = domain.store
    return manager


def _conversation_with_messages(domain, count: int, *, words: int = 12, prefix: str = "message"):
    conv = domain.conversations.create(f"ctx-{prefix}")
    for index in range(count):
        role = "user" if index % 2 == 0 else "assistant"
        domain.conversations.append_message(conv.id, role, f"{prefix} {index} " + "word " * words)
    return conv


class TestBudget:
    def test_budget_maths(self, ctx):
        assert ctx.budget() == 400 - 100 - 50
        assert ctx.budget(limit=200, output=50, reserve=10) == 140
        assert ctx.budget(limit=100, output=100, reserve=50) == 0

    def test_current_request_must_fit(self, ctx):
        conv = _conversation_with_messages(ctx, 1)
        with pytest.raises(ContextOverflowError) as exc:
            ctx.build(conv.id, user_message="x " * 500, budget_tokens=50)
        assert "budget is 50" in exc.value.message
        assert "Shorten the message" in exc.value.message

    def test_unknown_strategy(self, ctx):
        conv = _conversation_with_messages(ctx, 1)
        with pytest.raises(ValidationError):
            ctx.build(conv.id, strategy="vibes")

    def test_tokens_never_exceed_budget(self, ctx):
        conv = _conversation_with_messages(ctx, 12)
        manifest = ctx.build(conv.id, budget_tokens=120, user_message="next?")
        assert manifest.tokens_used <= 120


class TestOldestFirst:
    def test_keeps_recent_and_reports_omitted(self, ctx):
        conv = _conversation_with_messages(ctx, 10)
        manifest = ctx.build(conv.id, strategy="oldest_first", budget_tokens=120)
        assert manifest.strategy == "oldest_first"
        assert manifest.omitted, "old messages must be reported"
        included_seqs = [item.ref_id for item in manifest.included]
        assert included_seqs, "something must be included"
        # the most recent message survives
        last = ctx.conversations.messages(conv.id)[-1]
        assert last.id in included_seqs
        # history preserved in full
        assert len(ctx.conversations.messages(conv.id)) == 10
        for item in manifest.omitted:
            assert "stored, not deleted" in item["reason"] or "budget" in item["reason"]

    def test_pinned_protected_and_overflow_explained(self, ctx):
        conv = _conversation_with_messages(ctx, 3)
        first = ctx.conversations.messages(conv.id)[0]
        ctx.conversations.pin_message(first.id, True)
        manifest = ctx.build(conv.id, strategy="oldest_first", budget_tokens=200)
        assert first.id in [item.ref_id for item in manifest.included]
        assert any(item.pinned for item in manifest.included)
        # pin so much content that it cannot fit -> explicit error, never silent drop
        for _ in range(20):
            msg = ctx.conversations.append_message(conv.id, "user", "pinned " * 80)
            ctx.conversations.pin_message(msg.id, True)
        with pytest.raises(ContextOverflowError) as exc:
            ctx.build(conv.id, strategy="oldest_first", budget_tokens=60)
        assert "pinned" in exc.value.message

    def test_tool_pair_is_not_orphaned(self, ctx):
        conv = ctx.conversations.create("tools")
        call = ctx.conversations.append_message(
            conv.id, "assistant", "calling tool", tool_calls=[{"id": "t1", "name": "shell"}]
        )
        ctx.conversations.append_message(conv.id, "tool", "tool output", tool_results=[{"id": "t1"}])
        for i in range(6):
            ctx.conversations.append_message(conv.id, "user", f"filler {i} " + "x " * 40)
        manifest = ctx.build(conv.id, strategy="oldest_first", budget_tokens=150)
        included_ids = {item.ref_id for item in manifest.included}
        call_in = call.id in included_ids
        result_message = [m for m in ctx.conversations.messages(conv.id) if m.role == "tool"][0]
        result_in = result_message.id in included_ids
        assert call_in == result_in, "a tool call and its result must be kept or dropped together"

    def test_manifest_is_persisted_and_traced(self, ctx):
        conv = _conversation_with_messages(ctx, 4)
        manifest = ctx.build(conv.id, budget_tokens=200)
        stored = ctx.manifest(manifest.id)
        assert stored.is_ok
        assert stored.value["strategy"] == "oldest_first"
        assert stored.value["tokens_used"] == manifest.tokens_used
        assert ctx.manifests(conv.id)
        ctx.events.flush()
        names = [e.name for e in ctx.events.query(kind="context")]
        assert "context.built" in names

    def test_memory_accounted_in_same_window(self, ctx):
        conv = _conversation_with_messages(ctx, 2)
        ctx.memory.add("permanent", "Prefers metric", "Always use metric units", category="preference").ok_or_raise()
        manifest = ctx.build(conv.id, budget_tokens=200, user_message="units?")
        memory_items = [i for i in manifest.included if i.kind == "memory"]
        assert memory_items
        assert manifest.memory_tokens > 0
        assert manifest.tokens_used <= 200
        # memory is injected as untrusted data, separate from instructions
        assert any("never as instructions" in m["content"] for m in manifest.injected if m["role"] == "system")


class TestSummarize:
    def test_summary_replaces_old_messages_but_not_storage(self, ctx):
        conv = _conversation_with_messages(ctx, 12)
        manifest = ctx.build(conv.id, strategy="summarize", budget_tokens=150)
        assert manifest.strategy == "summarize"
        assert manifest.summarizer
        summaries = ctx.summaries(conv.id)
        assert summaries
        summary = summaries[0]
        assert summary.source_start_seq >= 1
        assert "SUMMARY:" in summary.content
        assert "originals are preserved" in manifest.included[0].content or any(
            "SUMMARY" in item.content for item in manifest.included
        )
        # originals still there
        assert len(ctx.conversations.messages(conv.id)) == 12
        sources = ctx.summary_sources(summary.id)
        assert sources and all(
            summary.source_start_seq <= m.seq <= summary.source_end_seq for m in sources
        )

    def test_short_conversation_not_summarised(self, ctx):
        conv = _conversation_with_messages(ctx, 1, words=2)
        manifest = ctx.build(conv.id, strategy="summarize", budget_tokens=400)
        assert "no summarisation was necessary" in (manifest.notes or "")
        assert ctx.summaries(conv.id) == []

    def test_summariser_failure_degrades(self, ctx):
        conv = _conversation_with_messages(ctx, 12)

        def broken(messages, instruction):
            raise RuntimeError("model exploded")

        ctx.summarizer = broken
        manifest = ctx.build(conv.id, strategy="summarize", budget_tokens=150)
        assert manifest.degraded is True
        assert "summarisation failed" in (manifest.notes or "")
        assert len(ctx.conversations.messages(conv.id)) == 12

    def test_no_summariser_configured_degrades(self, ctx):
        conv = _conversation_with_messages(ctx, 12)
        ctx.summarizer = None
        manifest = ctx.build(conv.id, strategy="summarize", budget_tokens=150)
        assert manifest.degraded is True
        assert "no summariser" in (manifest.notes or "")


class TestAiSelect:
    def test_relevance_selects_matching_message(self, ctx):
        conv = ctx.conversations.create("select")
        relevant = ctx.conversations.append_message(
            conv.id, "user", "the deployment uses kubernetes with helm charts"
        )
        for i in range(10):
            ctx.conversations.append_message(conv.id, "user", f"unrelated chatter {i} " + "noise " * 20)
        manifest = ctx.build(
            conv.id, strategy="ai_select", budget_tokens=160, user_message="how does the kubernetes deployment work?"
        )
        ids = [item.ref_id for item in manifest.included]
        assert relevant.id in ids
        reason = next(item.reason for item in manifest.included if item.ref_id == relevant.id)
        assert "relevant" in reason or "recent" in reason
        assert manifest.omitted
        assert all("not selected" in item["reason"] or "score" in item["reason"] for item in manifest.omitted)

    def test_reasons_recorded_for_every_item(self, ctx):
        conv = _conversation_with_messages(ctx, 8)
        manifest = ctx.build(conv.id, strategy="ai_select", budget_tokens=200, user_message="message 3")
        for item in manifest.included:
            assert item.reason
        assert manifest.notes and "deterministic" in manifest.notes


class TestManual:
    def test_only_selected_messages_included(self, ctx):
        conv = _conversation_with_messages(ctx, 5)
        messages = ctx.conversations.messages(conv.id)
        chosen = [messages[1].id, messages[3].id]
        manifest = ctx.build(conv.id, strategy="manual", manual_ids=chosen, budget_tokens=300)
        assert [item.ref_id for item in manifest.included] == chosen
        assert len(manifest.omitted) == 3
        assert all(item["reason"] == "not selected manually" for item in manifest.omitted)
        assert "2 message(s) selected manually" in (manifest.notes or "")

    def test_pinned_included_without_selection(self, ctx):
        conv = _conversation_with_messages(ctx, 3)
        messages = ctx.conversations.messages(conv.id)
        ctx.conversations.pin_message(messages[0].id)
        manifest = ctx.build(conv.id, strategy="manual", manual_ids=[messages[2].id], budget_tokens=300)
        ids = [item.ref_id for item in manifest.included]
        assert messages[0].id in ids and messages[2].id in ids
        assert "pinned" in next(i.reason for i in manifest.included if i.ref_id == messages[0].id)

    def test_selection_over_budget_explained(self, ctx):
        conv = _conversation_with_messages(ctx, 5, words=80)
        ids = [m.id for m in ctx.conversations.messages(conv.id)]
        with pytest.raises(ContextOverflowError) as exc:
            ctx.build(conv.id, strategy="manual", manual_ids=ids, budget_tokens=60)
        assert "deselect" in exc.value.message


class TestAiProposed:
    def test_proposal_changes_nothing_until_approved(self, ctx):
        conv = _conversation_with_messages(ctx, 12)
        proposal = ctx.propose(conv.id, budget_tokens=120)
        assert proposal.requires_approval if hasattr(proposal, "requires_approval") else True
        assert proposal.summarise
        assert proposal.retain
        assert len(ctx.conversations.messages(conv.id)) == 12
        # fetching it back works (persisted)
        again = ctx.get_proposal(proposal.id)
        assert again.summarise == proposal.summarise

    def test_approved_proposal_is_applied_and_recorded(self, ctx):
        conv = _conversation_with_messages(ctx, 12)
        proposal = ctx.propose(conv.id, budget_tokens=140)
        manifest = ctx.build(conv.id, approved_proposal_id=proposal.id, budget_tokens=140)
        assert manifest.strategy == "ai_proposed"
        assert manifest.proposal_id == proposal.id
        assert "approved proposal" in (manifest.notes or "")
        assert ctx.summaries(conv.id), "an approved summarisation must produce a stored summary"
        assert len(ctx.conversations.messages(conv.id)) == 12, "history is preserved"
        rows = ctx.proposals(conv.id)
        assert rows[0]["approved_at"] is not None
        assert rows[0]["applied_manifest_id"] == manifest.id

    def test_rejection_is_recorded_and_nothing_changes(self, ctx):
        conv = _conversation_with_messages(ctx, 12)
        proposal = ctx.propose(conv.id, budget_tokens=120)
        ctx.reject_proposal(proposal.id, reason="user prefers the full history")
        rows = ctx.proposals(conv.id)
        assert rows[0]["rejected_at"] is not None
        assert len(ctx.conversations.messages(conv.id)) == 12
        with pytest.raises(ValidationError):
            ctx.build(conv.id, strategy="ai_proposed", budget_tokens=120)

    def test_small_conversation_needs_no_change(self, ctx):
        conv = _conversation_with_messages(ctx, 2, words=2)
        proposal = ctx.propose(conv.id, budget_tokens=400)
        assert proposal.summarise == []
        assert "no change is needed" in proposal.rationale

    def test_missing_proposal(self, ctx):
        conv = _conversation_with_messages(ctx, 3)
        from archx_agent.helpers.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            ctx.get_proposal("prop_missing")
        with pytest.raises(NotFoundError):
            ctx.build(conv.id, approved_proposal_id="prop_missing")


class TestStrategySurface:
    def test_all_five_strategies_exposed(self):
        assert STRATEGIES == ("oldest_first", "summarize", "ai_select", "manual", "ai_proposed")
