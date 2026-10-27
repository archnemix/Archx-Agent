"""M20: provider catalogue, privacy metadata, consent, availability, usage/quotas."""

from __future__ import annotations

import json
import os

import pytest

from archx_agent.application.workspace import Workspace, open_workspace
from archx_agent.helpers.exceptions import (
    ConsentRequiredError,
    NotFoundError,
    PermissionDeniedError,
    PrivacyUnknownError,
    QuotaExhaustedError,
    ValidationError,
)
from archx_agent.managers.providers import CONSENT_VERSION, KNOWN_PROVIDERS, ProviderManager, is_loopback_url


@pytest.fixture()
def providers(domain):
    manager = ProviderManager(domain.store, domain.coordinator, events=domain.events)
    return manager


class TestCatalogue:
    def test_templates_are_claims_with_a_source(self):
        rows = ProviderManager.catalogue()
        assert {r["slug"] for r in rows} >= {"openai", "anthropic", "google", "openai-compatible-local"}
        for row in rows:
            assert row["claim_source"], "every claim must say where it came from"
            assert "data_leaves_device" in row["privacy_claims"]

    def test_loopback_detection(self):
        assert is_loopback_url("http://127.0.0.1:8080/v1")
        assert is_loopback_url("http://localhost:11434")
        assert is_loopback_url("http://127.0.0.5:9000")
        assert not is_loopback_url("https://api.openai.com/v1")
        assert not is_loopback_url(None)


class TestRegistration:
    def test_cloud_provider_starts_blocked_on_privacy(self, providers):
        provider = providers.add("staging", template="openai").ok_or_raise()
        assert provider.kind == "cloud"
        assert provider.data_leaves_device is True  # vendor claim only
        assert provider.privacy_known is False
        assert "confirm" in (provider.blocking_reason() or "")
        with pytest.raises(PrivacyUnknownError):
            providers.require_usable(provider.id)

    def test_local_provider_needs_no_consent(self, providers):
        provider = providers.add("ollama", template="openai-compatible-local").ok_or_raise()
        assert provider.is_local is True
        assert provider.data_leaves_device is False
        assert provider.blocking_reason() is None
        assert providers.require_usable(provider.id).id == provider.id
        # consent is a no-op and says so in the trace rather than pretending to matter
        result = providers.consent(provider.id)
        assert result.is_ok and result.value.consent_at is None

    def test_raw_api_key_is_refused(self, providers):
        result = providers.add("bad", base_url="https://example.invalid/v1", auth_ref="sk-abcdef123456789")
        assert result.is_err
        assert "reference" in result.error.message
        result = providers.add("bad2", base_url="ftp://example.invalid", template=None, kind="custom")
        assert result.is_err

    def test_local_kind_requires_loopback_url(self, providers):
        result = providers.add("liar", kind="local", base_url="https://api.openai.com/v1")
        assert result.is_err
        assert "loopback" in result.error.message

    def test_duplicate_names_refused(self, providers):
        providers.add("dup", template="openai").ok_or_raise()
        assert providers.add("dup", template="openai").is_err

    def test_confirmation_cannot_contradict_a_loopback_url(self, providers):
        provider = providers.add("local", template="openai-compatible-local").ok_or_raise()
        result = providers.confirm_privacy(provider.id, data_leaves_device=True)
        assert result.is_err
        assert "contradicts" in result.error.message

    def test_missing_provider(self, providers):
        assert isinstance(providers.get("nope").error, NotFoundError)
        with pytest.raises(NotFoundError):
            providers.require("nope")


class TestConsent:
    def _cloud(self, providers):
        return providers.add("cloud", template="openai").ok_or_raise()

    def test_consent_requires_confirmed_privacy(self, providers):
        provider = self._cloud(providers)
        assert isinstance(providers.consent(provider.id).error, PrivacyUnknownError)
        providers.confirm_privacy(provider.id, data_leaves_device=True, retention="30 days").ok_or_raise()
        consented = providers.consent(provider.id, note="personal testing").ok_or_raise()
        assert consented.consented is True
        assert consented.consent_version == CONSENT_VERSION
        assert consented.blocking_reason() is None
        providers.require_usable(provider.id)

    def test_revocation_blocks_again(self, providers):
        provider = self._cloud(providers)
        providers.confirm_privacy(provider.id, data_leaves_device=True).ok_or_raise()
        providers.consent(provider.id).ok_or_raise()
        providers.revoke_consent(provider.id).ok_or_raise()
        with pytest.raises(ConsentRequiredError):
            providers.require_usable(provider.id)

    def test_old_consent_version_requires_reconfirmation(self, providers):
        provider = self._cloud(providers)
        providers.confirm_privacy(provider.id, data_leaves_device=True).ok_or_raise()
        providers.consent(provider.id).ok_or_raise()
        with providers.store.write_tx() as tx:
            tx.execute("UPDATE providers SET consent_version = '2020-01-1' WHERE id = ?", (provider.id,))
        refreshed = providers.require(provider.id)
        assert "confirm again" in (refreshed.blocking_reason() or "")
        with pytest.raises(ConsentRequiredError):
            providers.require_usable(provider.id)

    def test_disabled_provider_is_blocked_but_privacy_is_kept(self, providers):
        provider = self._cloud(providers)
        providers.confirm_privacy(provider.id, data_leaves_device=True).ok_or_raise()
        providers.consent(provider.id).ok_or_raise()
        providers.enable(provider.id, False).ok_or_raise()
        refreshed = providers.require(provider.id)
        assert refreshed.consent_at is not None
        assert refreshed.blocking_reason() == "provider is disabled"
        with pytest.raises(ValidationError):
            providers.require_usable(provider.id)

    def test_revoke_by_slug_actually_persists(self, providers):
        """Regression: revoke used the caller's string as the row id, so a slug silently
        updated nothing while reporting success."""
        provider = self._cloud(providers)
        providers.confirm_privacy(provider.id, data_leaves_device=True).ok_or_raise()
        providers.consent(provider.id).ok_or_raise()
        by_slug = providers.by_slug("cloud").ok_or_raise()
        providers.revoke_consent(by_slug.slug).ok_or_raise()
        assert providers.require(provider.id).consent_at is None
        with pytest.raises(NotFoundError):
            providers._apply_update(
                type("Tx", (), {"execute": lambda self, sql, params: 0})(),
                {"id": "no-such-provider", "fields": {"notes": "x"}},
            )

    def test_privacy_report_explains_each_provider(self, providers):
        local = providers.add("ollama", template="openai-compatible-local").ok_or_raise()
        cloud = self._cloud(providers)
        rows = {r["id"]: r for r in providers.privacy_report()}
        assert rows[local.id]["data_leaves_device"] is False
        assert rows[local.id]["blocking_reason"] is None
        assert rows[cloud.id]["privacy_known"] is False
        assert rows[cloud.id]["blocking_reason"]


class TestAvailability:
    def test_reachable_endpoint_reports_models(self, providers, stub_server):
        base, handler = stub_server
        handler.routes = {"GET /v1/models": (200, {"data": [{"id": "a"}, {"id": "b"}]})}
        provider = providers.add("stub", kind="local", base_url=base + "/v1", is_local=True).ok_or_raise()
        result = providers.check(provider.id, timeout=2).ok_or_raise()
        assert result["status"] == "reachable"
        assert result["models_seen"] == 2
        assert result["latency_ms"] is not None
        assert providers.last_check(provider.id)["status"] == "reachable"
        assert providers.checks(provider.id)

    def test_auth_failure_is_distinguished(self, providers, stub_server):
        base, handler = stub_server
        handler.routes = {"GET /v1/models": (401, {"error": {"message": "bad key"}})}
        provider = providers.add("stub", kind="local", base_url=base + "/v1", is_local=True).ok_or_raise()
        assert providers.check(provider.id, timeout=2).ok_or_raise()["status"] == "auth_failed"

    def test_server_error_is_not_reported_as_reachable(self, providers, stub_server):
        base, handler = stub_server
        handler.routes = {"GET /v1/models": (500, {"error": {"message": "boom"}})}
        provider = providers.add("stub", kind="local", base_url=base + "/v1", is_local=True).ok_or_raise()
        assert providers.check(provider.id, timeout=2).ok_or_raise()["status"] == "unreachable"

    def test_missing_route_means_model_missing(self, providers, stub_server):
        base, _handler = stub_server
        provider = providers.add("stub", kind="local", base_url=base + "/v1", is_local=True).ok_or_raise()
        assert providers.check(provider.id, timeout=2).ok_or_raise()["status"] == "model_missing"

    def test_unreachable_port(self, providers):
        provider = providers.add(
            "dead", kind="local", base_url="http://127.0.0.1:9/v1", is_local=True
        ).ok_or_raise()
        assert providers.check(provider.id, timeout=1).ok_or_raise()["status"] == "unreachable"

    def test_auth_header_is_sent_from_a_secret_reference(self, providers, stub_server, monkeypatch):
        base, handler = stub_server
        seen: list[str] = []
        original = handler._respond

        def capture(self, method, body):  # noqa: ANN001
            seen.append(self.headers.get("Authorization") or "")
            original(self, method, body)

        monkeypatch.setattr(handler, "_respond", capture, raising=False)
        handler.routes = {"GET /v1/models": (200, {"data": []})}
        monkeypatch.setenv("ARCHX_STUB_KEY", "test-key-value-1234567890")
        provider = providers.add(
            "stub",
            kind="local",
            base_url=base + "/v1",
            is_local=True,
            auth_ref="secret://env/ARCHX_STUB_KEY",
        ).ok_or_raise()
        assert providers.check(provider.id, timeout=2).ok_or_raise()["status"] == "reachable"
        assert seen and seen[0] == "Bearer test-key-value-1234567890"

    def test_missing_secret_reports_auth_failure(self, providers):
        provider = providers.add(
            "stub",
            kind="local",
            base_url="http://127.0.0.1:9/v1",
            is_local=True,
            auth_ref="secret://env/ARCHX_DOES_NOT_EXIST",
        ).ok_or_raise()
        result = providers.check(provider.id, timeout=1).ok_or_raise()
        assert result["status"] == "auth_failed"
        assert "cannot resolve secret" in result["detail"]


class TestUsageAndQuota:
    def test_usage_aggregation_and_cost_only_with_prices(self, providers):
        provider = providers.add("p", template="openai").ok_or_raise()
        providers.record_usage(provider.id, model_ref="m", tokens_in=1000, tokens_out=500, ok=True)
        providers.record_usage(provider.id, model_ref="m", tokens_in=1000, tokens_out=500, ok=False, error="429")
        usage = providers.usage(provider.id)
        assert usage["requests"] == 2
        assert usage["tokens_in"] == 2000
        assert usage["tokens_out"] == 1000
        assert usage["errors"] == 1
        assert usage["estimated_cost"] is None and usage["cost_is_estimate"] is False

        providers.update(provider.id, price_in_per_1k=0.5, price_out_per_1k=1.5).ok_or_raise()
        priced = providers.usage(provider.id)
        assert priced["estimated_cost"] == pytest.approx(2.5)
        assert priced["cost_is_estimate"] is True

        daily = providers.usage_by_day(provider.id)
        assert daily and daily[0]["requests"] == 2

    def test_quota_is_enforced_and_advisory_until_set(self, providers):
        provider = providers.add("q", template="openai").ok_or_raise()
        providers.assert_quota(provider.id)  # no quota declared -> no restriction
        providers.set_quota(provider.id, max_requests_per_day=2).ok_or_raise()
        providers.assert_quota(provider.id)
        providers.record_usage(provider.id, tokens_in=10, tokens_out=10)
        providers.record_usage(provider.id, tokens_in=10, tokens_out=10)
        with pytest.raises(QuotaExhaustedError):
            providers.assert_quota(provider.id)
        providers.set_quota(provider.id, max_requests_per_day=5).ok_or_raise()
        providers.assert_quota(provider.id)
        providers.set_quota(provider.id, max_tokens_per_day=1).ok_or_raise()
        with pytest.raises(QuotaExhaustedError):
            providers.assert_quota(provider.id)

    def test_every_privacy_action_is_traced(self, providers):
        provider = providers.add("t", template="openai").ok_or_raise()
        providers.confirm_privacy(provider.id, data_leaves_device=True).ok_or_raise()
        providers.consent(provider.id, note="test").ok_or_raise()
        providers.revoke_consent(provider.id).ok_or_raise()
        providers.events.flush()
        names = [e.name for e in providers.events.query(kind="provider")]
        assert "provider.created" in names
        assert "provider.privacy_confirmed" in names
        assert "provider.consent_recorded" in names
        assert "provider.consent_revoked" in names
        # the consent note is recorded, the key never is
        for event in providers.events.query(kind="provider"):
            assert "sk-" not in json.dumps(event.payload)


class TestWorkspaceEnforcement:
    """The application, not the manager, is what refuses to send data off-machine."""

    def _workspace(self, tmp_path, **overrides):
        return open_workspace(home=str(tmp_path / "home"), env={}, overrides=overrides)

    def test_remote_model_is_refused_in_local_only_mode(self, tmp_path):
        with self._workspace(tmp_path) as ws:
            record = ws.models.register_remote(
                "cloud-model", provider="openai", model_ref="gpt-x", base_url="https://api.example.invalid/v1"
            )
            with pytest.raises(PermissionDeniedError) as exc:
                ws.runtime_for(record)
            assert "local_only" in exc.value.message

    def test_remote_model_without_provider_requires_registration(self, tmp_path):
        with self._workspace(tmp_path, **{"model.local_only": False}) as ws:
            record = ws.models.register_remote(
                "cloud-model", provider="nobody", model_ref="gpt-x", base_url="https://api.example.invalid/v1"
            )
            with pytest.raises(ConsentRequiredError):
                ws.runtime_for(record)

    def test_registered_but_unconfirmed_provider_is_blocked(self, tmp_path):
        with self._workspace(tmp_path, **{"model.local_only": False}) as ws:
            provider = ws.providers.add("cloud", template="openai").ok_or_raise()
            record = ws.models.register_remote(
                "cloud-model", provider="cloud", model_ref="gpt-x", base_url="https://api.openai.com/v1"
            )
            with pytest.raises(PrivacyUnknownError):
                ws.runtime_for(record)
            ws.providers.confirm_privacy(provider.id, data_leaves_device=True).ok_or_raise()
            with pytest.raises(ConsentRequiredError):
                ws.runtime_for(record)
            ws.providers.consent(provider.id).ok_or_raise()
            runtime = ws.runtime_for(record)  # constructing the client sends nothing
            assert runtime is not None
            assert ws.providers.require(provider.id).consented is True

    def test_loopback_endpoint_needs_no_consent(self, tmp_path):
        with self._workspace(tmp_path) as ws:
            record = ws.models.register_remote(
                "local-model", provider="local", model_ref="m", base_url="http://127.0.0.1:8080/v1"
            )
            assert ws.runtime_for(record) is not None

    def test_usage_is_attributed_to_the_provider(self, tmp_path):
        with self._workspace(tmp_path, **{"model.local_only": False}) as ws:
            provider = ws.providers.add("cloud", template="openai").ok_or_raise()
            record = ws.models.register_remote(
                "cloud-model", provider="cloud", model_ref="gpt-x", base_url="https://api.openai.com/v1"
            )
            ws.record_usage(record, tokens_in=120, tokens_out=30, ok=True)
            usage = ws.providers.usage(provider.id)
            assert usage["requests"] == 1 and usage["tokens_in"] == 120
