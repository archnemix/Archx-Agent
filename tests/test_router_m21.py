"""M21: capability-safe router, capability states, probes and fallbacks."""

from __future__ import annotations

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import (
    ModelNotFoundError,
    UnsupportedCapabilityError,
    ValidationError,
)
from archx_agent.managers.models import RUNTIME_BASELINE_CAPABILITIES


@pytest.fixture()
def ws(tmp_path):
    with open_workspace(
        home=str(tmp_path / "home"),
        env={"ARCHX_ALLOW_SIMULATED": "1"},
    ) as workspace:
        yield workspace


def _simulated(ws, name="sim"):
    return ws.models.register_remote(
        name,
        provider="test-double",
        runtime="scripted",
        model_ref="simulated",
        context_length=8192,
        capabilities=["chat"],
        verification="unverified",
        claims={"simulated": True},
    )


def _llama(ws, name="gguf", tmp_path=None, size=4096):
    import os

    directory = ws.config.path("paths.models")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{name}.gguf")
    with open(path, "wb") as fh:
        fh.write(b"GGUF" + b"\x00" * (size - 4))
    return ws.models.register_local_file(path)


def _http(ws, name="local-http", base="http://127.0.0.1:8111/v1", capabilities=("chat",)):
    # distinct model_ref per name: the catalogue is unique on (provider, model_ref)
    return ws.models.register_remote(
        name,
        provider="local-http",
        runtime="openai-http",
        model_ref=f"m-{name}",
        base_url=base,
        capabilities=list(capabilities),
    )


class TestCapabilityStates:
    def test_adapter_implemented_capability_is_inferred_not_verified(self, ws):
        record = _llama(ws)
        state = ws.models.capability_state(record, "chat")
        assert state["state"] == "inferred"
        assert "adapter" in state["basis"]

    def test_a_passed_probe_is_verified(self, ws):
        record = _simulated(ws)
        result = ws.router.probe(record.id, "chat")
        assert result["outcome"] == "passed"
        assert result["state_after"]["state"] == "verified"
        assert ws.models.capability_state(ws.models.require(record.id), "chat")["state"] == "verified"

    def test_a_failed_probe_marks_unsupported_and_overrides_claims(self, ws):
        record = _llama(ws)
        ws.models.set_verified_capabilities(record.id, ["vision"], basis="user claim")
        ws.models.record_capability_test(record.id, "vision", "failed", detail="no image support")
        state = ws.models.capability_state(ws.models.require(record.id), "vision")
        assert state["state"] == "unsupported"
        assert state["basis"] == "probe failed"

    def test_latest_probe_wins(self, ws):
        record = _simulated(ws)
        ws.models.record_capability_test(record.id, "chat", "failed", detail="first attempt")
        ws.models.record_capability_test(record.id, "chat", "passed", detail="second attempt")
        assert ws.models.capability_state(ws.models.require(record.id), "chat")["state"] == "verified"

    def test_unusable_model_reports_unavailable(self, ws, tmp_path):
        import os

        record = _llama(ws)
        os.remove(record.path)
        ws.models.refresh_states()
        state = ws.models.capability_state(ws.models.require(record.id), "chat")
        assert state["state"] == "unavailable"

    def test_matrix_includes_declared_baseline_and_tested(self, ws):
        record = _llama(ws)
        ws.models.record_capability_test(record.id, "ocr", "failed", detail="no")
        matrix = ws.models.capability_matrix(record.id)
        assert set(matrix) >= {"chat", "streaming", "ocr"}
        assert matrix["ocr"]["state"] == "unsupported"

    def test_probe_refuses_capabilities_it_cannot_measure(self, ws):
        record = _llama(ws)
        with pytest.raises(ValidationError) as exc:
            ws.router.probe(record.id, "vision")
        assert "cannot probe" in exc.value.message
        assert "vision" in exc.value.message

    def test_probe_of_missing_model(self, ws):
        with pytest.raises(ModelNotFoundError):
            ws.router.probe("nope", "chat")

    def test_probe_of_a_broken_endpoint_is_recorded_as_failure(self, ws):
        record = _http(ws, base="http://127.0.0.1:9/v1")
        result = ws.router.probe(record.id, "chat")
        assert result["outcome"] == "failed"
        assert result["state_after"]["state"] == "unsupported"
        history = ws.models.capability_history(record.id)
        assert history and history[0]["outcome"] == "failed"


class TestRouting:
    def test_unknown_capability_is_rejected(self, ws):
        _llama(ws)
        with pytest.raises(ValidationError):
            ws.router.route("chat", required=["telepathy"])

    def test_no_models_explains_how_to_add_one(self, ws):
        with pytest.raises(ModelNotFoundError) as exc:
            ws.route_model(task="chat")
        assert "no usable model" in exc.value.message
        assert "models add-http" in exc.value.message

    def test_simulated_model_needs_the_flag(self, ws):
        _simulated(ws)
        with pytest.raises(ModelNotFoundError) as exc:
            ws.router.route("chat", allow_simulated=False)
        assert "simulated" in exc.value.message
        decision = ws.router.route("chat", allow_simulated=True)
        assert decision.chosen is not None
        assert any("simulated" in note for note in decision.notes)

    def test_local_model_is_preferred_over_remote(self, ws):
        remote = _http(ws, name="remote", base="https://api.example.invalid/v1")
        local = _http(ws, name="local", base="http://127.0.0.1:8111/v1")
        decision = ws.router.route("chat", allow_cloud=True)
        assert decision.chosen.id == local.id
        rejected = {c.model_id: c.blockers for c in decision.candidates}
        assert rejected[remote.id], "the remote model must say why it was not picked"

    def test_remote_is_never_chosen_without_permission(self, ws):
        _http(ws, name="remote", base="https://api.example.invalid/v1")
        with pytest.raises(ModelNotFoundError) as exc:
            ws.router.route("chat", allow_cloud=False)
        assert "remote" in exc.value.message
        assert "allow_cloud" in exc.value.message

    def test_remote_candidate_reports_the_consent_gate(self, ws):
        ws.config.values["model.local_only"] = False
        _http(ws, name="remote", base="https://api.example.invalid/v1")
        with pytest.raises(ModelNotFoundError) as exc:
            ws.router.route("chat", allow_cloud=True)
        message = exc.value.message
        assert "registered provider" in message or "consent" in message

    def test_same_model_ref_on_a_different_endpoint_is_refused(self, ws):
        """Regression: a second registration silently overwrote the first model's endpoint,
        so two services collapsed into one catalogue entry (this masked a routing bug)."""
        first = _http(ws, name="one", base="http://127.0.0.1:8111/v1")
        from archx_agent.helpers.exceptions import ConflictError

        with pytest.raises(ConflictError) as exc:
            ws.models.register_remote(
                "two", provider="local-http", runtime="openai-http", model_ref=first.model_ref,
                base_url="http://127.0.0.1:8112/v1", capabilities=["chat"],
            )
        assert first.name in exc.value.message
        assert [m.name for m in ws.models.list()] == ["one"]

    def test_re_registering_the_same_endpoint_is_idempotent(self, ws):
        first = _http(ws, name="one", base="http://127.0.0.1:8111/v1")
        again = _http(ws, name="one", base="http://127.0.0.1:8111/v1")
        assert again.id == first.id
        assert len(ws.models.list()) == 1

    def test_explicit_model_bypasses_the_cloud_policy_but_not_consent(self, ws):
        record = _http(ws, name="remote", base="https://api.example.invalid/v1")
        with pytest.raises(ValidationError) as exc:
            ws.route_model(task="chat", model_id=record.id)
        assert "local_only" in exc.value.message

    def test_min_context_excludes_small_models(self, ws):
        record = ws.models.register_remote(
            "tiny", provider="test-double", runtime="scripted", model_ref="simulated", context_length=256,
            capabilities=["chat"], verification="unverified", claims={"simulated": True},
        )
        with pytest.raises(ModelNotFoundError) as exc:
            ws.router.route("chat", allow_simulated=True, min_context_tokens=4096)
        assert "context window" in exc.value.message
        assert ws.models.require(record.id).context_length == 256

    def test_require_verified_policy_rejects_unproven_models(self, ws):
        record = _simulated(ws)
        ws.config.values["router.require_verified"] = True
        with pytest.raises(ModelNotFoundError) as exc:
            ws.router.route("chat", allow_simulated=True)
        assert "not verified" in exc.value.message
        ws.router.probe(record.id, "chat")
        assert ws.router.route("chat", allow_simulated=True).chosen.id == record.id

    def test_unverified_capability_can_be_allowed_explicitly(self, ws):
        record = _http(ws, name="ocr-model", base="http://127.0.0.1:8111/v1", capabilities=["ocr"])
        with pytest.raises(ModelNotFoundError):
            ws.router.route("chat", required=["ocr"])
        decision = ws.router.route("chat", required=["ocr"], allow_unverified=True)
        assert decision.chosen.id == record.id
        candidate = decision.chosen_candidate
        assert candidate and any("allowed by policy" in note for note in candidate.notes)

    def test_unsupported_capability_is_never_routed(self, ws):
        record = _simulated(ws)
        ws.models.record_capability_test(record.id, "chat", "failed", detail="broken")
        with pytest.raises(ModelNotFoundError) as exc:
            ws.router.route("chat", allow_simulated=True, allow_unverified=True)
        assert "unsupported" in exc.value.message

    def test_explicit_model_with_unsupported_capability_raises_unsupported(self, ws):
        record = _simulated(ws)
        ws.models.record_capability_test(record.id, "chat", "failed", detail="broken")
        with pytest.raises(UnsupportedCapabilityError):
            ws.route_model(task="chat", model_id=record.id)

    def test_decision_is_recorded_in_the_trace(self, ws):
        record = _simulated(ws)
        ws.router.route("chat", allow_simulated=True)
        ws.events.flush()
        names = [e.name for e in ws.events.query(kind="model")]
        assert "model.routed" in names
        routed = [e for e in ws.events.query(kind="model") if e.name == "model.routed"][-1]
        assert routed.payload["chosen"] == record.id
        assert "policy" in routed.payload

    def test_preferred_model_wins_a_tie(self, ws):
        a = _simulated(ws, "a")
        b = _simulated(ws, "b")
        ws.models.set_preferred_for(b.id, ["chat"])
        assert ws.router.route("chat", allow_simulated=True).chosen.id == b.id

    def test_fallbacks_are_ranked(self, ws):
        a = _simulated(ws, "a")
        b = _simulated(ws, "b")
        decision = ws.router.route("chat", allow_simulated=True)
        assert decision.chosen is not None
        assert {m.id for m in decision.fallbacks} <= {a.id, b.id}
        assert decision.chosen.id not in {m.id for m in decision.fallbacks}

    def test_explicit_choice_excludes_fallbacks(self, ws):
        a = _simulated(ws)
        decision = ws.route_model(task="chat", model_id=a.id)
        assert decision.chosen.id == a.id
        assert decision.fallbacks == []
        assert any("explicitly requested" in n for n in decision.notes)

    def test_baseline_capabilities_cover_every_runtime_we_ship(self):
        assert set(RUNTIME_BASELINE_CAPABILITIES) >= {"llama-cpp", "openai-http", "scripted"}
        for capabilities in RUNTIME_BASELINE_CAPABILITIES.values():
            assert "chat" in capabilities


class TestChatFallback:
    """Fallback is an application behaviour, not a router detail: it must be visible."""

    def _workspace(self, tmp_path):
        return open_workspace(home=str(tmp_path / "fb"), env={"ARCHX_ALLOW_SIMULATED": "1"})

    def test_retryable_failure_falls_back_and_records_it(self, tmp_path):
        with self._workspace(tmp_path) as ws:
            # A dead endpoint that yields a *retryable* network failure, plus a working double.
            failing = ws.models.register_remote(
                "flaky", provider="local-http", runtime="openai-http", model_ref="flaky-1",
                base_url="http://127.0.0.1:9/v1", capabilities=["chat"],
            )
            backup = _simulated(ws, "backup")
            ws.models.set_preferred_for(failing.id, ["chat"])
            reply = ws.chat.send("hello")
            assert reply.model["name"] == backup.name, "the working model must answer"
            assert reply.model["fallback_from"] == failing.id
            assert reply.text
            assert any("falling back" in w for w in reply.warnings)
            ws.events.flush()
            names = [e.name for e in ws.events.query(kind="model_call")]
            assert "model.failed" in names and "model.fallback" in names
            # the failed model keeps the failure, the answering model owns the reply
            failures = [e for e in ws.events.query(kind="model_call") if e.name == "model.failed"]
            assert failures[-1].payload["model_id"] == failing.id
            assert failures[-1].payload["retryable"] is True

    def test_non_retryable_failure_does_not_fall_back(self, tmp_path, stub_server):
        base, handler = stub_server
        handler.routes = {"POST /v1/chat/completions": (401, {"error": {"message": "bad key"}})}
        with self._workspace(tmp_path) as ws:
            ws.models.register_remote(
                "denied", provider="local-http", runtime="openai-http", model_ref="denied-1",
                base_url=f"{base}/v1", capabilities=["chat"],
            )
            _simulated(ws, "backup")
            from archx_agent.helpers.exceptions import AuthDeniedError

            with pytest.raises(AuthDeniedError):
                ws.chat.send("hello")
            ws.events.flush()
            assert "model.fallback" not in [e.name for e in ws.events.query(kind="model_call")]
            # the failure is recorded against the model and the provider usage
            assert ws.models.require(ws.models.by_name("denied").value.id).failure_count == 1


class TestRuntimeAvailability:
    """A model whose runtime cannot start here must never be offered."""

    def test_missing_llama_cpp_dependency_blocks_the_model(self, ws):
        record = _llama(ws)
        from archx_agent.adapters.llama_cpp_runtime import llama_cpp_available

        if llama_cpp_available():  # pragma: no cover - depends on the environment
            assert ws.router.route("chat").chosen.id == record.id
        else:
            with pytest.raises(ModelNotFoundError) as exc:
                ws.router.route("chat")
            assert "runtime unavailable" in exc.value.message
            assert "llama-cpp-python" in exc.value.message
            # and the decision that produced it is recorded, candidates included
            ws.events.flush()
            failed = [e for e in ws.events.query(kind="model") if e.name == "model.route_failed"]
            assert failed and failed[-1].payload["rejected"]

    def test_scripted_runtime_is_unavailable_without_the_flag(self, tmp_path):
        with open_workspace(home=str(tmp_path / "no-flag"), env={}) as workspace:
            _simulated(workspace)
            with pytest.raises(ModelNotFoundError) as exc:
                workspace.router.route("chat")
            assert "simulated" in exc.value.message

    def test_availability_check_never_loads_weights(self, ws):
        """The router's check must not instantiate a runtime (which would load a model)."""
        record = _llama(ws)
        ok, why = ws.runtime_availability(record)
        from archx_agent.adapters.llama_cpp_runtime import llama_cpp_available

        assert ok is llama_cpp_available()
        assert isinstance(why, str) and why
