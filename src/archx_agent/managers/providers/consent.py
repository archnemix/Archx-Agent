"""Consent operations for provider metadata."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.urls import is_loopback_url as is_loopback_url
from archx_agent.helpers.exceptions import (
    ConsentRequiredError,
    PrivacyUnknownError,
    ValidationError,
)
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.providers.constants import CONSENT_VERSION
from archx_agent.managers.providers.records import Provider


class ProviderManagerConsentMixin:
    """Consent responsibility for ProviderManager."""

    def confirm_privacy(
        self,
        provider_id: str,
        *,
        data_leaves_device: bool,
        training_use: str = "unknown",
        retention: str = "unknown",
        region: str = "unknown",
    ) -> Result[Provider]:
        """Record what the *user* confirms about the provider's data handling."""
        existing = self.get(provider_id)
        if existing.is_err:
            return existing
        provider = existing.value
        if provider.is_local and data_leaves_device:
            return Err(
                ValidationError(
                    "this provider's base_url is loopback, so data cannot leave the device; "
                    "a confirmation saying otherwise contradicts the URL"
                )
            )
        confirmed = {
            "data_leaves_device": bool(data_leaves_device),
            "training_use": training_use,
            "retention": retention,
            "region": region,
            "confirmed_at": iso_now(),
        }
        self._write(
            "provider.update",
            {"id": provider.id, "fields": {"privacy_confirmed": confirmed}},
        )
        self.trace(
            "provider",
            "provider.privacy_confirmed",
            payload={
                "provider_id": provider.id,
                "data_leaves_device": bool(data_leaves_device),
            },
        )
        return self.get(provider.id)

    def consent(self, provider_id: str, *, note: str = "") -> Result[Provider]:
        """Record explicit consent to send data to a remote provider."""
        existing = self.get(provider_id)
        if existing.is_err:
            return existing
        provider = existing.value
        if not provider.privacy_known:
            return Err(
                PrivacyUnknownError(
                    f"privacy terms for {provider.name} are not confirmed; run "
                    f"`archx-agent providers confirm {provider.id} --data-leaves-device yes|no` first"
                )
            )
        if provider.data_leaves_device is False:
            self.trace(
                "provider",
                "provider.consent_not_required",
                payload={"provider_id": provider.id},
            )
            return Ok(provider)
        self._write(
            "provider.update",
            {
                "id": provider.id,
                "fields": {
                    "consent_at": iso_now(),
                    "consent_version": CONSENT_VERSION,
                    "notes": (provider.notes or "")
                    + (f"\nconsent: {note}" if note else ""),
                },
            },
        )
        self.trace(
            "provider",
            "provider.consent_recorded",
            payload={
                "provider_id": provider.id,
                "consent_version": CONSENT_VERSION,
                "note": note,
            },
        )
        return self.get(provider.id)

    def revoke_consent(self, provider_id: str) -> Result[Provider]:
        existing = self.get(provider_id)
        if existing.is_err:
            return existing
        resolved = existing.value.id
        self._write(
            "provider.update",
            {"id": resolved, "fields": {"consent_at": None, "consent_version": None}},
        )
        self.trace(
            "provider", "provider.consent_revoked", payload={"provider_id": resolved}
        )
        return self.get(resolved)

    def require_usable(self, provider_id: str) -> Provider:
        """Raise the specific blocking error, or return the provider."""
        provider = self.require(provider_id)
        if not provider.privacy_known:
            raise PrivacyUnknownError(
                provider.blocking_reason() or "privacy terms unknown"
            )
        if provider.requires_consent and not provider.consented:
            raise ConsentRequiredError(provider.blocking_reason() or "consent required")
        if not provider.enabled:
            raise ValidationError(f"provider {provider.name} is disabled")
        return provider

    def privacy_report(self) -> list[dict[str, Any]]:
        rows = []
        for provider in self.list():
            rows.append(
                {
                    "id": provider.id,
                    "name": provider.name,
                    "kind": provider.kind,
                    "is_local": provider.is_local,
                    "data_leaves_device": provider.data_leaves_device,
                    "privacy_known": provider.privacy_known,
                    "consented": provider.consented,
                    "effective_privacy": provider.effective_privacy,
                    "blocking_reason": provider.blocking_reason(),
                }
            )
        return rows
