"""Catalogue file eligibility, replacement evidence and disabled user intent."""

from __future__ import annotations

from pathlib import Path

import pytest

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.managers.models import ModelManager
from archx_agent.managers.models.files import observe_file


@pytest.fixture
def catalogue(domain, tmp_path):
    return ModelManager(
        domain.store,
        domain.coordinator,
        events=domain.events,
        models_root=str(tmp_path),
    )


def model_file(path: Path, byte: bytes = b"x", size: int = 2048) -> Path:
    path.write_bytes(byte * size)
    return path


@pytest.mark.parametrize("hash_file", ["never", "always", None])
def test_directories_cannot_be_registered(catalogue, tmp_path, hash_file):
    directory = tmp_path / "directory.gguf"
    directory.mkdir()
    for i in range(100):
        (directory / str(i)).touch()
    with pytest.raises(ValidationError, match="regular file"):
        catalogue.register_local_file(directory, hash_file=hash_file)
    assert catalogue.list() == []


@pytest.mark.parametrize(
    "size,expected", [(0, "invalid"), (1023, "invalid"), (1024, "usable")]
)
def test_minimum_size_matches_native_threshold(catalogue, tmp_path, size, expected):
    record = catalogue.register_local_file(
        model_file(tmp_path / "model.gguf", size=size)
    )
    assert record.state == expected
    assert bool(record.last_error) == (expected == "invalid")
    assert record.verification_state == "unverified"


def test_missing_path_and_invalid_discovery_root(catalogue, tmp_path):
    with pytest.raises(NotFoundError):
        catalogue.register_local_file(tmp_path / "missing.gguf")
    with pytest.raises(ValidationError, match="directory"):
        catalogue.discover_local(str(model_file(tmp_path / "file.gguf")))


def test_unconfigured_discovery_does_not_scan_cwd(domain, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    model_file(tmp_path / "accidental.gguf")
    manager = ModelManager(domain.store, domain.coordinator)
    assert manager.discover_local() == []


def test_missing_restored_tiny_directory_and_valid_file(catalogue, tmp_path):
    path = model_file(tmp_path / "model.gguf")
    record = catalogue.register_local_file(path)
    path.unlink()
    assert catalogue.refresh_states()["missing"] == 1
    model_file(path, size=10)
    assert catalogue.refresh_states()["restored"] == 0
    assert catalogue.require(record.id).state == "invalid"
    path.unlink()
    path.mkdir()
    catalogue.refresh_states()
    assert catalogue.require(record.id).state == "invalid"
    path.rmdir()
    model_file(path)
    assert catalogue.refresh_states()["restored"] == 1
    assert catalogue.require(record.id).state == "usable"


def test_disabled_intent_survives_discovery_disappearance_and_restore(
    catalogue, tmp_path
):
    path = model_file(tmp_path / "model.gguf")
    record = catalogue.register_local_file(path)
    catalogue.set_enabled(record.id, False)
    assert catalogue.discover_local()[0].state == "disabled"
    path.unlink()
    catalogue.refresh_states()
    assert catalogue.require(record.id).state == "missing"
    model_file(path)
    catalogue.refresh_states()
    restored = catalogue.require(record.id)
    assert restored.state == "disabled" and restored.facts["user_disabled"]
    assert catalogue.set_enabled(record.id, True).state == "usable"
    catalogue.refresh_states()
    assert catalogue.require(record.id).state == "usable"


def test_enable_revalidates_file_instead_of_only_row_state(catalogue, tmp_path):
    path = model_file(tmp_path / "model.gguf")
    record = catalogue.register_local_file(path)
    model_file(path, size=1)
    with pytest.raises(ValidationError, match="too small"):
        catalogue.set_enabled(record.id, True)
    assert catalogue.require(record.id).state == "invalid"


@pytest.mark.parametrize("refresh", [True, False])
def test_changed_file_invalidates_probe_proof_but_retains_history(
    catalogue, tmp_path, refresh
):
    path = model_file(tmp_path / "model.gguf")
    record = catalogue.register_local_file(path, hash_file="always")
    catalogue.set_verified_capabilities(record.id, ["chat"], basis="verified")
    catalogue.record_capability_test(record.id, "chat", "passed")
    assert (
        catalogue.capability_state(catalogue.require(record.id), "chat")["state"]
        == "verified"
    )
    model_file(path, byte=b"z")
    if refresh:
        catalogue.refresh_states()
    else:
        catalogue.register_local_file(path)
    changed = catalogue.require(record.id)
    assert changed.verified_capabilities == []
    assert changed.verification_state == "unverified"
    assert catalogue.latest_tests(record.id) == {}
    assert len(catalogue.capability_history(record.id)) == 1
    assert catalogue.capability_state(changed, "chat")["state"] == "inferred"
    catalogue.record_capability_test(record.id, "chat", "passed")
    assert (
        catalogue.capability_state(catalogue.require(record.id), "chat")["state"]
        == "verified"
    )


def test_unchanged_file_preserves_digest_probes_and_user_metadata(catalogue, tmp_path):
    path = model_file(tmp_path / "model.gguf")
    record = catalogue.register_local_file(path, hash_file="always")
    catalogue.update(
        record.id,
        name="My model",
        context_length=8192,
        user_metadata={"preferred_for": ["chat"]},
    )
    catalogue.record_capability_test(record.id, "chat", "passed")
    same = catalogue.register_local_file(path, hash_file="never")
    assert same.name == "My model" and same.context_length == 8192
    assert same.sha256 == record.sha256 and same.preferred_for() == ["chat"]
    assert catalogue.latest_tests(record.id)["chat"]["outcome"] == "passed"


def test_unavailable_file_does_not_advertise_old_passed_probe(catalogue, tmp_path):
    path = model_file(tmp_path / "model.gguf")
    record = catalogue.register_local_file(path)
    catalogue.record_capability_test(record.id, "chat", "passed")
    path.unlink()
    catalogue.refresh_states()
    assert (
        catalogue.capability_state(catalogue.require(record.id), "chat")["state"]
        == "unavailable"
    )


def test_legacy_rows_without_signature_lose_unbound_proofs(catalogue, tmp_path):
    record = catalogue.register_local_file(model_file(tmp_path / "model.gguf"))
    facts = dict(record.facts)
    facts.pop("file_signature")
    catalogue._write("model.update", {"id": record.id, "fields": {"facts": facts}})
    catalogue.record_capability_test(record.id, "chat", "passed")
    catalogue.refresh_states()
    assert catalogue.latest_tests(record.id) == {}
    assert len(catalogue.capability_history(record.id)) == 1


def test_all_rows_are_refreshed_not_only_first_presentation_page(catalogue, tmp_path):
    # Insert >200 catalogue rows sharing one real file via the normal write handler.
    path = model_file(tmp_path / "model.gguf")
    template = catalogue.register_local_file(path).to_dict()
    for i in range(201):
        row = {
            **template,
            "id": f"test-{i}",
            "name": f"model-{i}",
            "path": str(tmp_path / f"missing-{i}.gguf"),
        }
        catalogue._write("model.register", {"model": row})
    assert catalogue.refresh_states()["missing"] == 201
    assert len(catalogue.list(state="missing", limit=1000)) == 201


def test_filesystem_stat_errors_never_become_usable(monkeypatch, tmp_path):
    path = tmp_path / "protected.gguf"

    def denied(self, *args, **kwargs):
        raise PermissionError(13, "permission denied")

    monkeypatch.setattr(Path, "stat", denied)
    observation = observe_file(path)
    assert observation["state"] == "invalid"
    assert "cannot inspect" in observation["error"]


def test_file_disappearing_during_hash_is_not_usable(monkeypatch, tmp_path):
    path = model_file(tmp_path / "model.gguf")

    def vanished(*args):
        raise FileNotFoundError("deleted while hashing")

    monkeypatch.setattr("archx_agent.managers.models.files.sha256_file", vanished)
    observation = observe_file(path, hash_file=True)
    assert observation["state"] == "missing" and observation["sha256"] is None
    assert not observation["facts"]["exists"]


@pytest.mark.parametrize("refresh", [True, False])
def test_unchanged_file_observation_preserves_inference_failure(
    catalogue, tmp_path, refresh
):
    path = model_file(tmp_path / "model.gguf")
    record = catalogue.register_local_file(path)
    catalogue.record_usage(
        record.id, success=False, error="inference allocation failed"
    )
    if refresh:
        catalogue.refresh_states()
    else:
        catalogue.register_local_file(path)
    assert catalogue.require(record.id).last_error == "inference allocation failed"
    path.unlink()
    catalogue.refresh_states()
    assert catalogue.require(record.id).last_error == "model file disappeared"
    model_file(path)
    catalogue.refresh_states()
    assert catalogue.require(record.id).last_error is None
