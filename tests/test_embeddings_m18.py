from __future__ import annotations

import json
import math

import pytest

from archx_agent.adapters.embedding_runtime import (
    HashEmbeddingProvider,
    HttpEmbeddingProvider,
    build_provider,
)
from archx_agent.application.retrieval_eval import (
    evaluate_mode,
    load_dataset,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    ndcg_at_k,
    render_markdown,
    run_evaluation,
)
from archx_agent.helpers.exceptions import ProviderError, ValidationError
from archx_agent.helpers.vectors import cosine, dimension, dot, normalize, pack, top_k, unpack
from archx_agent.managers.embeddings import EmbeddingManager


class TestVectors:
    def test_roundtrip_float32(self):
        vector = [0.1, -0.25, 1e-7, 42.0]
        blob = pack(vector)
        assert dimension(blob) == 4
        restored = unpack(blob)
        assert restored == pytest.approx(vector, rel=1e-6)
        assert blob == pack(vector)  # deterministic

    def test_empty_and_bad_blobs(self):
        with pytest.raises(ValidationError):
            pack([])
        with pytest.raises(ValidationError):
            unpack(b"")
        with pytest.raises(ValidationError):
            unpack(b"\x00\x00\x00")

    def test_cosine_and_dot(self):
        assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
        assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
        assert cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)
        assert cosine([0, 0], [1, 1]) == 0.0
        assert dot([1, 2, 3], [4, 5, 6]) == 32
        with pytest.raises(ValidationError):
            cosine([1, 2], [1, 2, 3])

    def test_normalize(self):
        assert normalize([3, 4]) == pytest.approx([0.6, 0.8])
        assert normalize([0, 0]) == [0.0, 0.0]

    def test_top_k_ordering_threshold_and_mismatch(self):
        query = [1.0, 0.0]
        candidates = [("a", [1.0, 0.0]), ("b", [0.9, 0.1]), ("c", [0.0, 1.0]), ("d", [1.0, 0.0, 0.0])]
        ranked = top_k(query, candidates, k=3)
        assert [item for item, _ in ranked] == ["a", "b", "c"]
        assert all(score >= 0 for _, score in ranked)
        assert top_k(query, candidates, k=0) == []


class TestHashProvider:
    def test_deterministic_and_labelled(self):
        provider = HashEmbeddingProvider(dim=64)
        first = provider.embed(["hello world"]).vectors[0]
        second = HashEmbeddingProvider(dim=64).embed(["hello world"]).vectors[0]
        assert first == second
        assert len(first) == 64
        assert provider.semantic is False
        assert provider.health().ok and "not semantic" in provider.health().detail

    def test_normalized_and_empty_text(self):
        vector = HashEmbeddingProvider(dim=32).embed([""]).vectors[0]
        assert len(vector) == 32
        assert math.isclose(sum(v * v for v in vector) ** 0.5, 1.0, rel_tol=1e-6)

    def test_related_text_scores_higher_than_unrelated(self):
        provider = HashEmbeddingProvider(dim=256)
        a, b, c = provider.embed(
            ["database locked error fixed by retry", "database locked errors need retries", "banana bread recipe"]
        ).vectors
        assert cosine(a, b) > cosine(a, c)

    def test_validation(self):
        with pytest.raises(ValidationError):
            HashEmbeddingProvider(dim=8)
        with pytest.raises(ValidationError):
            HashEmbeddingProvider().embed([1, 2])  # type: ignore[list-item]

    def test_build_provider(self):
        assert isinstance(build_provider("hash"), HashEmbeddingProvider)
        with pytest.raises(ValidationError):
            build_provider("magic")


class TestHttpProvider:
    def test_success_and_dimension_discovery(self, stub_server):
        base, handler = stub_server
        handler.routes["POST /v1/embeddings"] = (
            200,
            {"data": [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}], "usage": {"prompt_tokens": 5}},
        )
        provider = HttpEmbeddingProvider(base, model="embed-1")
        result = provider.embed(["a", "b"])
        assert result.dim == 3 and provider.dim == 3
        assert result.semantic is True
        assert len(result.vectors) == 2

    def test_dimension_change_rejected(self, stub_server):
        base, handler = stub_server
        handler.routes["POST /v1/embeddings"] = (200, {"data": [{"embedding": [0.1, 0.2]}]})
        provider = HttpEmbeddingProvider(base, model="embed-1", dim=8)
        with pytest.raises(ProviderError):
            provider.embed(["a"])

    def test_malformed_and_count_mismatch(self, stub_server):
        base, handler = stub_server
        provider = HttpEmbeddingProvider(base, model="embed-1")
        handler.routes["POST /v1/embeddings"] = (200, {"nope": True})
        with pytest.raises(ProviderError):
            provider.embed(["a"])
        handler.routes["POST /v1/embeddings"] = (200, {"data": []})
        with pytest.raises(ProviderError):
            provider.embed(["a"])

    def test_http_error(self, stub_server):
        base, handler = stub_server
        handler.routes["POST /v1/embeddings"] = (401, {"error": {"message": "nope"}})
        with pytest.raises(ProviderError):
            HttpEmbeddingProvider(base, model="m").embed(["a"])


@pytest.fixture()
def emb_domain(domain):
    provider = HashEmbeddingProvider(dim=128)
    manager = EmbeddingManager(
        domain.store,
        domain.coordinator,
        events=domain.events,
        conversations=domain.conversations,
        memory=domain.memory,
        provider=provider,
    )
    domain.memory.embedding_index = manager
    domain.embeddings = manager
    domain.embedding_provider = provider
    return domain


class TestEmbeddingManager:
    def test_embed_memory_stores_model_and_dim(self, emb_domain):
        memory = emb_domain.memory.add(
            "permanent", "Locking", "database locked errors need retries", category="fact"
        ).ok_or_raise()
        outcome = emb_domain.embeddings.embed_text("memory", memory.id, memory.title + "\n" + memory.content)
        assert outcome.is_ok
        row = emb_domain.store.query_one(
            "SELECT model_id, dim, state, length(vector) AS bytes FROM embeddings WHERE owner_id=?",
            (memory.id,),
        )
        assert row["model_id"] == "archx-hash-v1"
        assert row["dim"] == 128
        assert row["bytes"] == 128 * 4
        assert row["state"] == "embedded"

    def test_cache_checksum_prevents_reembedding(self, emb_domain):
        memory = emb_domain.memory.add("permanent", "Cache", "same text", category="fact").ok_or_raise()
        first = emb_domain.embeddings.embed_text("memory", memory.id, "same text")
        second = emb_domain.embeddings.embed_text("memory", memory.id, "same text")
        assert first.value == "embedded"
        assert second.value == "cached"

    def test_failed_embedding_keeps_memory_searchable_by_keyword(self, emb_domain):
        class BrokenProvider(HashEmbeddingProvider):
            provider_id = "broken"

            def embed(self, texts):
                raise ProviderError("boom", provider="broken")

        memory = emb_domain.memory.add(
            "permanent", "Broken", "unique-keyword-zebra content", category="fact"
        ).ok_or_raise()
        emb_domain.embeddings.provider = BrokenProvider(dim=128)
        result = emb_domain.embeddings.embed_text("memory", memory.id, "unique-keyword-zebra content")
        assert result.is_err
        row = emb_domain.store.query_one("SELECT state FROM embeddings WHERE owner_id=?", (memory.id,))
        assert row["state"] == "failed"
        emb_domain.memory.embedding_index = None
        outcome = emb_domain.memory.search("unique-keyword-zebra")
        assert memory.id in [h.memory.id for h in outcome.hits]

    def test_semantic_search_and_hybrid_mode(self, emb_domain):
        target = emb_domain.memory.add(
            "permanent",
            "Atomic writes",
            "write to a temporary file then call os.replace so readers never see partial content",
            category="fact",
        ).ok_or_raise()
        emb_domain.memory.add(
            "permanent", "Unrelated", "the cat sat on the mat", category="fact"
        ).ok_or_raise()
        emb_domain.embeddings.embed_memories()
        found = emb_domain.embeddings.search("temporary file os.replace", owner_types=("memory",), k=5, threshold=0.1)
        assert found.neighbours and found.neighbours[0].owner_id == target.id
        assert found.degraded is False
        outcome = emb_domain.memory.search("temporary file os.replace")
        assert outcome.mode == "hybrid"
        assert outcome.hits[0].memory.id == target.id
        assert "semantic=" in outcome.hits[0].reason

    def test_model_change_makes_old_vectors_uncomparable(self, emb_domain):
        memory = emb_domain.memory.add("permanent", "Switch", "vector text", category="fact").ok_or_raise()
        emb_domain.embeddings.embed_memories()
        other = HashEmbeddingProvider(dim=128)
        other.model_id = "archx-hash-v2"
        emb_domain.embeddings.provider = other
        found = emb_domain.embeddings.search("vector text", owner_types=("memory",), k=5, threshold=0.0)
        assert found.neighbours == []
        assert emb_domain.embeddings.status()["stale_vectors"] == 1
        assert emb_domain.embeddings.stale_items()
        removed = emb_domain.embeddings.purge(model_id="archx-hash-v1")
        assert removed == 1

    def test_cross_model_similarity_is_refused(self, emb_domain):
        a = emb_domain.memory.add("permanent", "A", "alpha", category="fact").ok_or_raise()
        b = emb_domain.memory.add("permanent", "B", "beta", category="fact").ok_or_raise()
        emb_domain.embeddings.embed_text("memory", a.id, "alpha")
        emb_domain.store.execute(
            "UPDATE embeddings SET model_id='other-model' WHERE owner_id=?", (b.id,)
        )
        emb_domain.embeddings.embed_text("memory", b.id, "beta") if False else None
        emb_domain.store.execute(
            "INSERT INTO embeddings(owner_type, owner_id, model_id, dim, vector, checksum, state, created_at)"
            " VALUES ('memory', ?, 'other-model', 128, ?, 'x', 'embedded', '2026-01-01T00:00:00Z')",
            (b.id, pack([0.0] * 128)),
        )
        with pytest.raises(ValidationError):
            emb_domain.embeddings.similarity(a.id, b.id)
        assert emb_domain.embeddings.similarity(a.id, a.id) == pytest.approx(1.0, rel=1e-6)

    def test_message_and_conversation_embeddings(self, emb_domain):
        conv = emb_domain.conversations.create("emb")
        emb_domain.conversations.append_message(conv.id, "user", "hello database")
        emb_domain.conversations.append_message(conv.id, "assistant", "hello there")
        stats = emb_domain.embeddings.embed_conversation(conv.id)
        assert stats["messages"] == 2
        rows = emb_domain.store.query(
            "SELECT owner_type, COUNT(*) n FROM embeddings GROUP BY owner_type"
        )
        counts = {row["owner_type"]: row["n"] for row in rows}
        assert counts["message"] == 2
        assert counts["conversation"] == 1

    def test_backfill_covers_missing(self, emb_domain):
        emb_domain.memory.add("permanent", "B1", "first text", category="fact").ok_or_raise()
        conv = emb_domain.conversations.create("b")
        emb_domain.conversations.append_message(conv.id, "user", "message text")
        result = emb_domain.embeddings.backfill()
        assert result["embedded"] >= 2
        second = emb_domain.embeddings.backfill()
        assert second["embedded"] == 0

    def test_no_provider_reports_degraded(self, domain):
        manager = EmbeddingManager(domain.store, domain.coordinator, events=domain.events)
        assert manager.available is False
        outcome = manager.search("anything")
        assert outcome.degraded is True
        assert "no embedding provider" in (outcome.degraded_reason or "")

    def test_status_and_stats(self, emb_domain):
        emb_domain.memory.add("permanent", "S", "status text", category="fact").ok_or_raise()
        emb_domain.embeddings.embed_memories()
        status = emb_domain.embeddings.status()
        assert status["provider"]["model_id"] == "archx-hash-v1"
        assert status["states"]["embedded"] >= 1
        assert status["stale_vectors"] == 0
        assert emb_domain.embeddings.stats()["embeddings"] >= 1

    def test_remote_provider_requires_opt_in(self, domain):
        from archx_agent.adapters.embedding_runtime import HashEmbeddingProvider as Hash

        class FakeRemote(Hash):
            provider_id = "remote-fake"
            is_local = False
            semantic = True

        manager = EmbeddingManager(
            domain.store, domain.coordinator, events=domain.events, provider=FakeRemote(dim=64)
        )
        outcome = manager.embed_text("memory", "mem_x", "some text")
        assert outcome.is_err and "opt-in" in outcome.error.message


class TestRetrievalMetrics:
    def test_precision_recall_mrr_ndcg(self):
        relevant = {"a": 3, "b": 2}
        ranked = ["x", "a", "b"]
        assert precision_at_k(ranked, relevant, 3) == pytest.approx(2 / 3)
        assert recall_at_k(ranked, relevant, 3) == pytest.approx(1.0)
        assert reciprocal_rank(ranked, relevant) == pytest.approx(0.5)
        assert reciprocal_rank(["x", "y"], relevant) == 0.0
        perfect = ndcg_at_k(["a", "b"], relevant, 2)
        assert perfect == pytest.approx(1.0)
        assert ndcg_at_k(["b", "a"], relevant, 2) < perfect
        assert precision_at_k([], relevant, 3) == 0.0
        assert recall_at_k(["a"], relevant, 1) == pytest.approx(0.5)

    def test_evaluate_mode(self):
        dataset = load_dataset("data/retrieval_set.json")

        def retrieve(query, k):
            return ["d1", "d2"], False, None

        score = evaluate_mode("fake", dataset, retrieve, k=2)
        assert score.mode == "fake"
        assert 0.0 <= score.ndcg <= 1.0
        assert len(score.per_query) == len(dataset.cases)

    def test_dataset_validation(self, tmp_path):
        good = load_dataset("data/retrieval_set.json")
        assert good.size["queries"] == 12
        bad = tmp_path / "bad.json"
        bad.write_text(
            json.dumps({"name": "bad", "corpus": [{"id": "a", "text": "t"}], "queries": [{"query": "q", "relevant": {"zzz": 1}}]})
        )
        with pytest.raises(ValidationError):
            load_dataset(str(bad))
        with pytest.raises(ValidationError):
            load_dataset(str(tmp_path / "missing.json"))

    def test_full_evaluation_report(self, emb_domain):
        report = run_evaluation(load_dataset("data/retrieval_set.json"), memory=emb_domain.memory, embeddings=emb_domain.embeddings, k=5)
        assert set(mode["mode"] for mode in report["modes"]) == {"keyword", "semantic", "hybrid"}
        for mode in report["modes"]:
            for metric in ("precision@k", "recall@k", "mrr", "ndcg@k"):
                assert 0.0 <= mode[metric] <= 1.0
        markdown = render_markdown(report)
        assert "| keyword |" in markdown
        # hybrid must not be worse than pure keyword on this labelled set
        keyword = next(m for m in report["modes"] if m["mode"] == "keyword")
        hybrid = next(m for m in report["modes"] if m["mode"] == "hybrid")
        assert hybrid["ndcg@k"] >= keyword["ndcg@k"]
