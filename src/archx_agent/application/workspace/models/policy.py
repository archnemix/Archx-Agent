"""Policy operations for workspace composition."""

from __future__ import annotations

from archx_agent.helpers.exceptions import (
    ConsentRequiredError,
    PermissionDeniedError,
    PrivacyUnknownError,
)
from archx_agent.managers.models import ModelRecord
from archx_agent.managers.providers import is_loopback_url
from archx_agent.application.workspace.constants import NETWORK_RUNTIMES


class WorkspaceModelsPolicyMixin:
    """Models Policy responsibility for Workspace."""

    def assert_remote_allowed(self, record: ModelRecord) -> None:
        """Refuse to send data off this machine unless the user opted in.

        Three independent gates, all of which must pass for a non-loopback endpoint:

        1. ``model.local_only`` must be false (it is true by default);
        2. the endpoint must belong to a registered provider;
        3. that provider must have *known* privacy terms and recorded consent.
        """
        base_url = (record.facts or {}).get("base_url") if record.facts else None
        # Every runtime that can talk to a network endpoint is gated, not just the
        # OpenAI-compatible one: a new adapter must not become a way around the consent rules.
        if record.runtime not in NETWORK_RUNTIMES or not base_url:
            return
        if is_loopback_url(base_url):
            return
        if self.config.get("model.local_only"):
            raise PermissionDeniedError(
                "refusing to send data to a remote endpoint: model.local_only is true. "
                "Register the endpoint as a provider and set model.local_only=false deliberately."
            )
        provider = self._provider_for(record)
        if provider is None:
            if record.runtime == "gemini":
                template = "google"
            elif record.runtime == "sdk":
                template = (record.facts or {}).get("sdk") or "openai"
            else:
                template = "openai"
            raise ConsentRequiredError(
                f"the endpoint {base_url} is not a registered provider. Add it with "
                f"`archx-agent providers add <name> --template {template}` (or --base-url), confirm its "
                "privacy terms and record consent before sending anything."
            )
        if not provider.privacy_known:
            raise PrivacyUnknownError(
                provider.blocking_reason() or "provider privacy terms unknown"
            )
        if not provider.consented:
            raise ConsentRequiredError(
                provider.blocking_reason() or "provider consent missing"
            )

    def provider_for(self, record: ModelRecord):
        """The registered provider that owns this model's endpoint, if any."""
        return self._provider_for(record)

    def _provider_for(self, record: ModelRecord):
        if self.providers is None:
            return None
        base_url = (record.facts or {}).get("base_url")
        for provider in self.providers.list():
            if (
                base_url
                and provider.base_url
                and provider.base_url.rstrip("/") == str(base_url).rstrip("/")
            ):
                return provider
            if (
                provider.slug == (record.provider or "").lower()
                or provider.name == record.provider
            ):
                return provider
        return None

    def record_usage(
        self,
        record: ModelRecord,
        *,
        tokens_in: int,
        tokens_out: int,
        ok: bool,
        error: str | None = None,
    ) -> None:
        """Attribute usage to the owning provider when one is registered."""
        if self.providers is None:
            return
        provider = self._provider_for(record)
        if provider is None:
            return
        self.providers.record_usage(
            provider.id,
            model_ref=record.model_ref or record.name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            ok=ok,
            error=error,
        )
