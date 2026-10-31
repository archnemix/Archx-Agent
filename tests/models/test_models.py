from __future__ import annotations

import os

import pytest

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.managers.models import ModelManager, parse_gguf_name


def _fake_gguf(directory, name="SmolLM2-135M-Instruct-Q8_0.gguf", size=4096):
    path = os.path.join(directory, name)
    with open(path, "wb") as fh:
        fh.write(b"GGUF" + b"\x00" * (size - 4))
    return path


@pytest.fixture()
def models(domain, tmp_path):
    manager = ModelManager(
        domain.store, domain.coordinator, events=domain.events, models_root=str(tmp_path / "models")
    )
    os.makedirs(tmp_path / "models", exist_ok=True)
    return manager


class TestDiscovery:
    def test_parse_gguf_claims(self):
        claims = parse_gguf_name("SmolLM2-135M-Instruct-Q8_0.gguf")
        assert claims["quantization"] == "Q8_0"
        assert claims["chat"] is True
        assert claims["source"] == "filename"
        vision = parse_gguf_name("llava-v1.6-vision-q4_k_m.gguf")
        assert vision["vision"] == "claimed"

    def test_register_local_file_and_states(self, models, tmp_path):
        path = _fake_gguf(tmp_path / "models")
        record = models.register_local_file(path)
        assert record.state == "usable"
        assert record.facts["exists"] is True
        assert record.size_bytes == 4096
        assert record.verified_capabilities == []
        assert record.verification_state == "unverified"
        tiny = tmp_path / "models" / "tiny.gguf"
        tiny.write_bytes(b"xx")
        assert models.register_local_file(tiny).state == "invalid"

    def test_discover_is_idempotent(self, models, tmp_path):
        _fake_gguf(tmp_path / "models")
        _fake_gguf(tmp_path / "models", name="other-model-q4_k_m.gguf")
        first = models.discover_local()
        second = models.discover_local()
        assert len(first) == 2 and len(second) == 2
        assert len(models.list()) == 2

    def test_missing_file_detected_and_restored(self, models, tmp_path):
        path = _fake_gguf(tmp_path / "models")
        record = models.register_local_file(path)
        os.remove(path)
        assert models.refresh_states()["missing"] == 1
        assert models.require(record.id).state == "missing"
        with pytest.raises(ValidationError):
            models.set_enabled(record.id, True)
        _fake_gguf(tmp_path / "models")
        assert models.refresh_states()["restored"] == 1
        assert models.require(record.id).state == "usable"

    def test_discover_missing_directory_is_empty(self, models, tmp_path):
        assert models.discover_local(str(tmp_path / "nope")) == []


class TestCatalogueRules:
    def test_facts_claims_and_user_metadata_stay_separate(self, models, tmp_path):
        record = models.register_local_file(_fake_gguf(tmp_path / "models"))
        assert record.claims["quantization"] == "Q8_0"
        assert record.user_metadata == {}
        updated = models.set_preferred_for(record.id, ["chat"])
        assert updated.user_metadata["preferred_for"] == ["chat"]
        assert updated.claims["quantization"] == "Q8_0"  # unchanged by user metadata
        assert "Q8_0" not in str(updated.facts)

    def test_registry_isolation(self, models):
        with pytest.raises(NotFoundError):
            models.update("missing-id", state="disabled")
        with pytest.raises(ValidationError):
            models.update(models.register_remote("r1", provider="p", model_ref="m").id, bogus=1)
        with pytest.raises(NotFoundError):
            models.require("nope")

    def test_remote_registration_requires_model_ref(self, models):
        with pytest.raises(ValidationError):
            models.register_remote("x", provider="p")
        record = models.register_remote("remote", provider="p", model_ref="m", capabilities=["chat"])
        assert record.state == "usable"
        assert record.verification_state == "inferred"
        assert record.supports("chat")

    def test_verification_recording(self, models):
        record = models.register_local_file(_fake_gguf(models.models_root))
        updated = models.set_verified_capabilities(record.id, ["chat"], basis="prompt smoke test")
        assert updated.verification_state == "verified"
        assert updated.capability_basis["chat"] == "prompt smoke test"
        models.record_capability_test(record.id, "ocr", "failed", detail="no image support", latency_ms=12.5)
        history = models.capability_history(record.id)
        assert history[0]["capability"] == "ocr"
        assert history[0]["outcome"] == "failed"
        with pytest.raises(ValidationError):
            models.record_capability_test(record.id, "chat", "maybe")
        with pytest.raises(ValidationError):
            models.set_verified_capabilities(record.id, ["chat"], verification_state="probably")

    def test_usage_and_compare(self, models):
        a = models.register_remote("a", provider="p", model_ref="m1", capabilities=["chat"])
        b = models.register_remote("b", provider="p", model_ref="m2", capabilities=["chat"])
        models.record_usage(a.id, success=True)
        models.record_usage(a.id, success=False, error="timeout")
        rows = models.compare([a.id, b.id, "missing"])
        assert len(rows) == 2
        assert rows[0]["success_count"] == 1 and rows[0]["failure_count"] == 1

    def test_preferred_for_task(self, models):
        a = models.register_remote("a", provider="p", model_ref="m1")
        b = models.register_remote("b", provider="p", model_ref="m2")
        models.set_preferred_for(b.id, ["embedding"])
        assert models.preferred_for("embedding").id == b.id
        assert models.preferred_for("chat") is None
        assert models.preferred_for("chat") is None or a.id

    def test_remove_and_capability_filter(self, models, tmp_path):
        record = models.register_local_file(_fake_gguf(tmp_path / "models"))
        models.set_verified_capabilities(record.id, ["chat"])
        assert len(models.list(capability="chat")) == 1
        assert models.list(capability="ocr") == []
        models.remove(record.id)
        assert models.list() == []
        assert models.list(include_removed=True) == []

    def test_storage_summary(self, models, tmp_path):
        models.register_local_file(_fake_gguf(tmp_path / "models"))
        summary = models.storage_summary()
        assert summary["total_bytes"] >= 4096
