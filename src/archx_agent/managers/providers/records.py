"""Record types and row conversion for provider metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from archx_agent.helpers.urls import is_loopback_url as is_loopback_url
from archx_agent.managers.providers.constants import CONSENT_VERSION, PRIVACY_FIELDS


@dataclass
class Provider:
    id: str
    name: str
    slug: str
    kind: str
    api_style: str
    base_url: str | None
    model_family: str | None
    auth_ref: str | None
    is_local: bool
    enabled: bool
    privacy_claims: dict[str, Any]
    privacy_confirmed: dict[str, Any]
    claim_source: str | None
    claims_verified: bool
    price_in_per_1k: float | None
    price_out_per_1k: float | None
    currency: str | None
    notes: str | None
    consent_at: str | None
    consent_version: str | None
    created_at: str
    updated_at: str
    quotas: dict[str, Any] = field(default_factory=dict)
    last_check: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    # -- derived state -----------------------------------------------------
    @property
    def privacy_known(self) -> bool:
        if self.is_local:
            return True
        return "data_leaves_device" in self.privacy_confirmed

    @property
    def effective_privacy(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        sources: dict[str, str] = {}
        for field_name in PRIVACY_FIELDS:
            if self.is_local and field_name == "data_leaves_device":
                merged[field_name] = False
                sources[field_name] = "derived from the loopback URL (fact)"
            elif field_name in self.privacy_confirmed:
                merged[field_name] = self.privacy_confirmed[field_name]
                sources[field_name] = "user-confirmed"
            elif field_name in self.privacy_claims:
                merged[field_name] = self.privacy_claims[field_name]
                sources[field_name] = "vendor claim (unverified)"
        return {"values": merged, "sources": sources, "verified": self.claims_verified}

    @property
    def data_leaves_device(self) -> bool | None:
        if self.is_local:
            return False
        value = self.effective_privacy["values"].get("data_leaves_device")
        return bool(value) if isinstance(value, bool) else None

    @property
    def requires_consent(self) -> bool:
        return bool(self.data_leaves_device)

    @property
    def consented(self) -> bool:
        return bool(self.consent_at) and self.consent_version == CONSENT_VERSION

    def blocking_reason(self) -> str | None:
        """Why this provider may not be used right now, or ``None``."""
        if not self.enabled:
            return "provider is disabled"
        if not self.privacy_known:
            return (
                "privacy terms are unknown; confirm them with "
                f"`archx-agent providers confirm {self.id} --data-leaves-device yes|no`"
            )
        if self.consent_at and self.consent_version != CONSENT_VERSION:
            return (
                f"consent was recorded against consent version {self.consent_version}; "
                f"the current version is {CONSENT_VERSION} - confirm again"
            )
        if self.requires_consent and not self.consented:
            return (
                "this provider receives your data remotely; record explicit consent with "
                f"`archx-agent providers consent {self.id}` before use"
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "kind": self.kind,
            "api_style": self.api_style,
            "base_url": self.base_url,
            "model_family": self.model_family,
            "auth_ref": self.auth_ref,
            "is_local": self.is_local,
            "enabled": self.enabled,
            "privacy_claims": self.privacy_claims,
            "privacy_confirmed": self.privacy_confirmed,
            "claim_source": self.claim_source,
            "claims_verified": self.claims_verified,
            "effective_privacy": self.effective_privacy,
            "data_leaves_device": self.data_leaves_device,
            "requires_consent": self.requires_consent,
            "consent_at": self.consent_at,
            "consent_version": self.consent_version,
            "consented": self.consented,
            "blocking_reason": self.blocking_reason(),
            "price_in_per_1k": self.price_in_per_1k,
            "price_out_per_1k": self.price_out_per_1k,
            "currency": self.currency,
            "notes": self.notes,
            "last_check": self.last_check,
            "usage": self.usage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _from_row(row: Any) -> Provider:
    return Provider(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        kind=row["kind"],
        api_style=row["api_style"],
        base_url=row["base_url"],
        model_family=row["model_family"],
        auth_ref=row["auth_ref"],
        is_local=bool(row["is_local"]),
        enabled=bool(row["enabled"]),
        privacy_claims=json.loads(row["privacy_claims"])
        if row["privacy_claims"]
        else {},
        privacy_confirmed=json.loads(row["privacy_confirmed"])
        if row["privacy_confirmed"]
        else {},
        claim_source=row["claim_source"],
        claims_verified=bool(row["claims_verified"]),
        price_in_per_1k=row["price_in_per_1k"],
        price_out_per_1k=row["price_out_per_1k"],
        currency=row["currency"],
        notes=row["notes"],
        consent_at=row["consent_at"],
        consent_version=row["consent_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        quotas=json.loads(row["quotas"]) if row["quotas"] else {},
    )
