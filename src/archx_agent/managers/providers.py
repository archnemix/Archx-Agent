"""Cloud and local provider catalogue with privacy metadata (M20).

The central rule: **a provider is not usable because it is configured, it is usable
because the user knows what happens to their data and said yes.** Two independent
conditions must hold before any request can be sent:

1. the provider's privacy metadata is *known* - either because it is local (derived
   from the URL, not from a claim) or because the user confirmed the terms;
2. the user recorded explicit consent for that provider (``consent_at``).

Documentation claims live in ``privacy_claims`` and are never presented as facts.
What the user confirmed lives in ``privacy_confirmed``. The effective view merges them
with the confirmed values winning, and reports which of the two supplied each field.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from archx_agent.helpers.exceptions import (
    ConsentRequiredError,
    NotFoundError,
    PrivacyUnknownError,
    QuotaExhaustedError,
    ValidationError,
)
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

PROVIDER_TABLES = ("providers", "provider_checks", "provider_usage")

_SELECT = (
    "SELECT id, name, slug, kind, api_style, base_url, model_family,"
    " credential_ref AS auth_ref, is_local, enabled, privacy AS privacy_claims,"
    " COALESCE(privacy_confirmed, '{}') AS privacy_confirmed, claim_source,"
    " verified AS claims_verified, price_in_per_1k, price_out_per_1k,"
    " COALESCE(currency, '') AS currency, notes, consent_at, consent_version,"
    " COALESCE(quotas, '{}') AS quotas, created_at, updated_at"
    " FROM providers"
)

KINDS = ("local", "cloud", "custom")
API_STYLES = ("openai", "anthropic", "gemini", "custom")
CONSENT_VERSION = "2026-10-1"
PRIVACY_FIELDS = ("data_leaves_device", "training_use", "retention", "region")

#: **Claims**, not facts. Each entry records where the claim came from so the UI can
#: show "this is what the vendor documents, and it was not verified here". The user
#: still has to confirm the terms before the provider can be used.
KNOWN_PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "label": "OpenAI API",
        "kind": "cloud",
        "api_style": "openai",
        "base_url": "https://api.openai.com/v1",
        "model_family": "gpt",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "vendor states API data is not used to train models by default",
            "retention": "vendor states abuse-monitoring logs are retained for up to 30 days",
            "region": "vendor-defined; may process outside your country",
        },
        "claim_source": "vendor API documentation (not verified in this environment)",
    },
    "anthropic": {
        "label": "Anthropic API",
        "kind": "cloud",
        "api_style": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model_family": "claude",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "vendor states API inputs are not used for training by default",
            "retention": "vendor states inputs may be retained briefly for abuse monitoring",
            "region": "vendor-defined; may process outside your country",
        },
        "claim_source": "vendor documentation (not verified in this environment)",
    },
    "google": {
        "label": "Google Gemini API",
        "kind": "cloud",
        "api_style": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "model_family": "gemini",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "unknown without reading the current terms; do not assume either way",
            "retention": "unknown without reading the current terms",
            "region": "vendor-defined",
        },
        "claim_source": "vendor documentation (not verified in this environment)",
    },
    # The four below ship the endpoint and the wire style only. Their privacy terms are
    # deliberately absent: transcribing a vendor's current policy from memory is exactly the
    # kind of claim this catalogue refuses to make, so the user confirms the terms they read
    # (`providers confirm`), and the refusal names that step.
    "groq": {
        "label": "Groq API",
        "kind": "cloud",
        "api_style": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "model_family": "llama, mixtral, qwen",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "not transcribed here - read the vendor's terms before sending data",
            "retention": "not transcribed here - read the vendor's terms before sending data",
            "region": "vendor-defined",
        },
        "claim_source": "endpoint only; privacy terms not transcribed (confirm them yourself)",
    },
    "together": {
        "label": "Together AI",
        "kind": "cloud",
        "api_style": "openai",
        "base_url": "https://api.together.xyz/v1",
        "model_family": "open models",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "not transcribed here - read the vendor's terms before sending data",
            "retention": "not transcribed here - read the vendor's terms before sending data",
            "region": "vendor-defined",
        },
        "claim_source": "endpoint only; privacy terms not transcribed (confirm them yourself)",
    },
    "cohere": {
        "label": "Cohere",
        "kind": "cloud",
        "api_style": "custom",
        "base_url": "https://api.cohere.com",
        "model_family": "command, embed",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "not transcribed here - read the vendor's terms before sending data",
            "retention": "not transcribed here - read the vendor's terms before sending data",
            "region": "vendor-defined",
        },
        "claim_source": "endpoint only; privacy terms not transcribed (confirm them yourself)",
    },
    "mistral": {
        "label": "Mistral AI",
        "kind": "cloud",
        "api_style": "openai",
        "base_url": "https://api.mistral.ai",
        "model_family": "mistral, codestral",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "not transcribed here - read the vendor's terms before sending data",
            "retention": "not transcribed here - read the vendor's terms before sending data",
            "region": "vendor-defined",
        },
        "claim_source": "endpoint only; privacy terms not transcribed (confirm them yourself)",
    },
    # Any third-party endpoint that speaks the OpenAI shape (Z.ai, DeepSeek, a company gateway).
    # The privacy block is deliberately empty of vendor specifics: inventing terms for a vendor is
    # worse than making the user state them, and `providers confirm` exists for exactly that.
    "openai-compatible": {
        "label": "Any OpenAI-compatible endpoint",
        "kind": "cloud",
        "api_style": "openai",
        "base_url": "",          # required: there is no default for "somebody else's server"
        "model_family": "whatever the endpoint serves",
        "is_local": False,
        "privacy_claims": {
            "data_leaves_device": True,
            "training_use": "unknown - not transcribed; ask the provider before sending data",
            "retention": "unknown - not transcribed; ask the provider before sending data",
            "region": "unknown",
        },
        "claim_source": "no claims recorded; run `providers confirm` with the terms you read",
    },
    "ollama": {
        "label": "Ollama (local daemon or Ollama Cloud)",
        "kind": "custom",
        # The daemon is on this machine; the cloud endpoint is not. `is_local` is derived from
        # the URL at registration, so this template does not get to decide.
        "api_style": "custom",
        "base_url": "http://127.0.0.1:11434",
        "model_family": "whatever you have pulled",
        "is_local": True,
        "privacy_claims": {
            "data_leaves_device": False,
            "training_use": "no: prompts stay on this machine when the daemon is local",
            "retention": "n/a on your own disk; Ollama Cloud would differ and is not assumed here",
            "region": "this machine",
        },
        "claim_source": "endpoint only; a loopback daemon sends nothing off the machine",
    },
    "openai-compatible-local": {
        "label": "Local OpenAI-compatible server (llama.cpp, Ollama, vLLM, LM Studio)",
        "kind": "local",
        "api_style": "openai",
        "base_url": "http://127.0.0.1:8080/v1",
        "model_family": "",
        "is_local": True,
        "privacy_claims": {
            "data_leaves_device": False,
            "training_use": "no; the server runs on this machine",
            "retention": "whatever your own server logs",
            "region": "this machine",
        },
        "claim_source": "derived from the loopback URL (a fact, not a vendor claim)",
    },
}

_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (value or "").lower()).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:64] or "provider"


def is_loopback_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return False
    return host in _LOOPBACK or host.startswith("127.")


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
        privacy_claims=json.loads(row["privacy_claims"]) if row["privacy_claims"] else {},
        privacy_confirmed=json.loads(row["privacy_confirmed"]) if row["privacy_confirmed"] else {},
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


class ProviderManager(BaseManager):
    """Provider catalogue, privacy metadata, availability checks and usage."""

    tables = PROVIDER_TABLES

    def register_handlers(self) -> None:
        self.coordinator.register("provider.create", self._apply_create)
        self.coordinator.register("provider.update", self._apply_update)
        self.coordinator.register("provider.delete", self._apply_delete)
        self.coordinator.register("provider.check", self._apply_check)
        self.coordinator.register("provider.usage", self._apply_usage)

    # -- write handlers ----------------------------------------------------
    def _apply_create(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        p = payload["provider"]
        tx.execute(
            "INSERT INTO providers (id, name, slug, kind, api_style, base_url, model_family,"
            " credential_ref, is_local, enabled, privacy, privacy_confirmed, claim_source, verified,"
            " price_in_per_1k, price_out_per_1k, currency, notes, consent_at, consent_version,"
            " created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                p["id"], p["name"], p["slug"], p["kind"], p["api_style"], p["base_url"],
                p["model_family"], p["auth_ref"], int(p["is_local"]), int(p["enabled"]),
                json_text(p["privacy_claims"]), json_text(p["privacy_confirmed"]),
                p["claim_source"], int(p["claims_verified"]), p["price_in_per_1k"],
                p["price_out_per_1k"], p["currency"], p["notes"], p["consent_at"],
                p["consent_version"], p["created_at"], p["updated_at"],
            ),
        )
        return {"id": p["id"]}

    _COLUMN_FOR = {
        "auth_ref": "credential_ref",
        "privacy_claims": "privacy",
        "claims_verified": "verified",
        "credential_ref": "credential_ref",
        "privacy": "privacy",
        "verified": "verified",
    }

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields: dict[str, Any] = {self._COLUMN_FOR.get(k, k): v for k, v in payload["fields"].items()}
        fields["updated_at"] = iso_now()
        columns = ", ".join(f"{name} = ?" for name in fields)
        values = [json_text(v) if isinstance(v, dict) else v for v in fields.values()]
        for index, name in enumerate(fields):
            if name in {"is_local", "enabled", "claims_verified"}:
                values[index] = int(bool(values[index]))
        affected = tx.execute(f"UPDATE providers SET {columns} WHERE id = ?", (*values, payload["id"]))
        # A silent no-op update is how "revoke consent" can appear to succeed while
        # changing nothing (e.g. when a slug is passed instead of an id).
        if affected == 0:
            raise NotFoundError(f"provider {payload['id']} not found", id=payload["id"])
        return {"id": payload["id"], "affected": affected}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute("DELETE FROM providers WHERE id = ?", (payload["id"],))
        return {"id": payload["id"]}

    def _apply_check(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        c = payload
        tx.execute(
            "INSERT INTO provider_checks (provider_id, checked_at, status, latency_ms, detail, models_seen)"
            " VALUES (?,?,?,?,?,?)",
            (c["provider_id"], c["checked_at"], c["status"], c["latency_ms"], c["detail"], c["models_seen"]),
        )
        return {"provider_id": c["provider_id"]}

    def _apply_usage(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        u = payload
        tx.execute(
            "INSERT INTO provider_usage (provider, model_id, kind, prompt_tokens, completion_tokens,"
            " cost_estimate, success, error_code, occurred_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                u["provider_id"], u.get("model_ref"), u.get("kind", "chat"),
                u["tokens_in"], u["tokens_out"], u.get("cost_estimate"), int(not u.get("errors")),
                (u.get("last_error") or None), iso_now(),
            ),
        )
        return {"provider_id": u["provider_id"]}

    # -- catalogue ---------------------------------------------------------
    @staticmethod
    def catalogue() -> list[dict[str, Any]]:
        """Known provider templates. Claims only; nothing is used until added."""
        out = []
        for slug, entry in KNOWN_PROVIDERS.items():
            out.append(
                {
                    "slug": slug,
                    "label": entry["label"],
                    "kind": entry["kind"],
                    "api_style": entry["api_style"],
                    "base_url": entry["base_url"],
                    "is_local": entry["is_local"],
                    "privacy_claims": entry["privacy_claims"],
                    "claim_source": entry["claim_source"],
                }
            )
        return out

    def add(
        self,
        name: str,
        *,
        template: str | None = None,
        kind: str | None = None,
        api_style: str | None = None,
        base_url: str | None = None,
        model_family: str | None = None,
        auth_ref: str | None = None,
        is_local: bool | None = None,
        notes: str = "",
        price_in_per_1k: float | None = None,
        price_out_per_1k: float | None = None,
        currency: str = "USD",
        enabled: bool = True,
    ) -> Result[Provider]:
        try:
            entry = KNOWN_PROVIDERS.get(template or "", {})
            kind = (kind or entry.get("kind") or "custom").lower()
            if kind not in KINDS:
                raise ValidationError(f"unknown provider kind {kind!r} (expected one of {list(KINDS)})")
            api_style = (api_style or entry.get("api_style") or "openai").lower()
            if api_style not in API_STYLES:
                raise ValidationError(f"unknown api style {api_style!r} (expected one of {list(API_STYLES)})")
            base_url = base_url or entry.get("base_url")
            if not base_url and template == "openai-compatible":
                # "somebody else's server" has no sensible default; guessing one would send a
                # request somewhere nobody chose
                raise ValidationError(
                    "the openai-compatible template needs --base-url: there is no default endpoint "
                    "for an arbitrary vendor (e.g. --base-url https://api.z.ai/api/paas/v4)"
                )
            if base_url:
                parsed = urllib.parse.urlparse(base_url)
                if parsed.scheme not in ("http", "https"):
                    raise ValidationError("provider base_url must be an http(s) URL")
                if not parsed.netloc:
                    raise ValidationError("provider base_url must include a host")
            if auth_ref and not str(auth_ref).startswith(("secret://", "env:")):
                raise ValidationError(
                    "auth must be a reference (secret://env/NAME or secret://file/PATH), never the key itself"
                )
            local = is_local if is_local is not None else (entry.get("is_local") or is_loopback_url(base_url))
            if kind == "local" and not local:
                raise ValidationError("a provider declared local must use a loopback base_url")
            if kind != "local" and local and base_url and not is_loopback_url(base_url):
                raise ValidationError("is_local is only allowed for a loopback base_url")
            slug = _slug(name)
            if self.by_slug(slug).is_ok:
                return Err(ValidationError(f"a provider named {name!r} already exists"))
            now = iso_now()
            provider = Provider(
                id=new_id("prov_"),
                name=name,
                slug=slug,
                kind=kind,
                api_style=api_style,
                base_url=base_url,
                model_family=model_family or entry.get("model_family"),
                auth_ref=auth_ref,
                is_local=bool(local),
                enabled=enabled,
                privacy_claims=dict(entry.get("privacy_claims") or {}),
                privacy_confirmed={},
                claim_source=entry.get("claim_source"),
                claims_verified=False,
                price_in_per_1k=price_in_per_1k,
                price_out_per_1k=price_out_per_1k,
                currency=currency,
                notes=notes or None,
                consent_at=None,
                consent_version=None,
                created_at=now,
                updated_at=now,
            )
            self._write("provider.create", {"provider": provider.to_dict()})
            self.trace(
                "provider",
                "provider.created",
                payload={
                    "provider_id": provider.id,
                    "kind": kind,
                    "is_local": provider.is_local,
                    "auth_ref": auth_ref,
                },
            )
            return Ok(provider)
        except (ValidationError, ValueError) as exc:
            return Err(exc if isinstance(exc, ValidationError) else ValidationError(str(exc)))

    # -- reads -------------------------------------------------------------
    def get(self, provider_id: str) -> Result[Provider]:
        row = self.store.query_one(f"{_SELECT} WHERE id = ?", (provider_id,))
        if row is None:
            row = self.store.query_one(f"{_SELECT} WHERE slug = ?", (_slug(provider_id),))
        if row is None:
            return Err(NotFoundError(f"provider {provider_id} not found", id=provider_id))
        provider = _from_row(row)
        provider.last_check = self.last_check(provider.id)
        provider.usage = self.usage(provider.id)
        return Ok(provider)

    def require(self, provider_id: str) -> Provider:
        return self.get(provider_id).ok_or_raise()

    def by_slug(self, slug: str) -> Result[Provider]:
        row = self.store.query_one(f"{_SELECT} WHERE slug = ?", (slug,))
        if row is None:
            return Err(NotFoundError(f"provider slug {slug!r} not found", slug=slug))
        return Ok(_from_row(row))

    def list(self, *, kind: str | None = None, include_disabled: bool = True) -> list[Provider]:
        clauses, params = [], []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if not include_disabled:
            clauses.append("enabled = 1")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.store.query(f"{_SELECT}{where} ORDER BY created_at", tuple(params))
        providers = [_from_row(r) for r in rows]
        for provider in providers:
            provider.last_check = self.last_check(provider.id)
            provider.usage = self.usage(provider.id)
        return providers

    def last_check(self, provider_id: str) -> dict[str, Any] | None:
        row = self.store.query_one(
            "SELECT * FROM provider_checks WHERE provider_id = ? ORDER BY id DESC LIMIT 1", (provider_id,)
        )
        return dict(row) if row else None

    def checks(self, provider_id: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.store.query(
            "SELECT * FROM provider_checks WHERE provider_id = ? ORDER BY id DESC LIMIT ?",
            (provider_id, limit),
        )

    def usage(self, provider_id: str, *, days: int = 30) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        row = self.store.query_one(
            "SELECT COUNT(*) AS requests,"
            " COALESCE(SUM(prompt_tokens),0) AS tokens_in,"
            " COALESCE(SUM(completion_tokens),0) AS tokens_out,"
            " COALESCE(SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END),0) AS errors"
            " FROM provider_usage WHERE provider = ? AND occurred_at >= ?",
            (provider_id, since),
        )
        provider = self.store.query_one(
            "SELECT price_in_per_1k, price_out_per_1k, currency FROM providers WHERE id = ?", (provider_id,)
        )
        cost = None
        if provider and (provider["price_in_per_1k"] is not None or provider["price_out_per_1k"] is not None):
            cost = round(
                (row["tokens_in"] / 1000.0) * (provider["price_in_per_1k"] or 0.0)
                + (row["tokens_out"] / 1000.0) * (provider["price_out_per_1k"] or 0.0),
                6,
            )
        return {
            "requests": row["requests"],
            "tokens_in": row["tokens_in"],
            "tokens_out": row["tokens_out"],
            "errors": row["errors"],
            "estimated_cost": cost,
            "currency": (provider["currency"] if provider else None) or None,
            "cost_is_estimate": cost is not None,
            "window_days": days,
        }

    def usage_by_day(self, provider_id: str, *, days: int = 30) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return self.store.query(
            "SELECT substr(occurred_at, 1, 10) AS day, model_id AS model_ref, COUNT(*) AS requests,"
            " COALESCE(SUM(prompt_tokens),0) AS tokens_in,"
            " COALESCE(SUM(completion_tokens),0) AS tokens_out,"
            " COALESCE(SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END),0) AS errors"
            " FROM provider_usage WHERE provider = ? AND occurred_at >= ?"
            " GROUP BY day, model_id ORDER BY day DESC",
            (provider_id, since),
        )

    def set_quota(
        self, provider_id: str, *, max_requests_per_day: int | None = None, max_tokens_per_day: int | None = None
    ) -> Result[Provider]:
        """Declare a daily quota. Purely advisory to the provider, enforced by us."""
        existing = self.get(provider_id)
        if existing.is_err:
            return existing
        quotas = dict(existing.value.quotas)
        if max_requests_per_day is not None:
            quotas["max_requests_per_day"] = int(max_requests_per_day)
        if max_tokens_per_day is not None:
            quotas["max_tokens_per_day"] = int(max_tokens_per_day)
        self._write("provider.update", {"id": existing.value.id, "fields": {"quotas": quotas}})
        self.trace("provider", "provider.quota_set", payload={"provider_id": existing.value.id, "quotas": quotas})
        return self.get(existing.value.id)

    def assert_quota(self, provider_id: str) -> None:
        """Raise ``QuotaExhaustedError`` when today's usage reaches a declared quota."""
        provider = self.require(provider_id)
        if not provider.quotas:
            return
        today = self.store.query_one(
            "SELECT COUNT(*) AS requests, COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS tokens"
            " FROM provider_usage WHERE provider = ? AND substr(occurred_at, 1, 10) = ?",
            (provider_id, date.today().isoformat()),
        )
        limit_requests = provider.quotas.get("max_requests_per_day")
        limit_tokens = provider.quotas.get("max_tokens_per_day")
        if limit_requests is not None and today["requests"] >= int(limit_requests):
            raise QuotaExhaustedError(
                f"daily request quota reached for {provider.name} "
                f"({today['requests']}/{limit_requests}); raise it with `providers quota`"
            )
        if limit_tokens is not None and today["tokens"] >= int(limit_tokens):
            raise QuotaExhaustedError(
                f"daily token quota reached for {provider.name} "
                f"({today['tokens']}/{limit_tokens}); raise it with `providers quota`"
            )

    # -- privacy and consent ----------------------------------------------
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
        self._write("provider.update", {"id": provider.id, "fields": {"privacy_confirmed": confirmed}})
        self.trace(
            "provider",
            "provider.privacy_confirmed",
            payload={"provider_id": provider.id, "data_leaves_device": bool(data_leaves_device)},
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
                "provider", "provider.consent_not_required", payload={"provider_id": provider.id}
            )
            return Ok(provider)
        self._write(
            "provider.update",
            {
                "id": provider.id,
                "fields": {
                    "consent_at": iso_now(),
                    "consent_version": CONSENT_VERSION,
                    "notes": (provider.notes or "") + (f"\nconsent: {note}" if note else ""),
                },
            },
        )
        self.trace(
            "provider",
            "provider.consent_recorded",
            payload={"provider_id": provider.id, "consent_version": CONSENT_VERSION, "note": note},
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
        self.trace("provider", "provider.consent_revoked", payload={"provider_id": resolved})
        return self.get(resolved)

    def require_usable(self, provider_id: str) -> Provider:
        """Raise the specific blocking error, or return the provider."""
        provider = self.require(provider_id)
        if not provider.privacy_known:
            raise PrivacyUnknownError(provider.blocking_reason() or "privacy terms unknown")
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

    # -- lifecycle ---------------------------------------------------------
    def enable(self, provider_id: str, enabled: bool = True) -> Result[Provider]:
        existing = self.get(provider_id)
        if existing.is_err:
            return existing
        self._write("provider.update", {"id": existing.value.id, "fields": {"enabled": enabled}})
        self.trace(
            "provider",
            "provider.enabled" if enabled else "provider.disabled",
            payload={"provider_id": existing.value.id},
        )
        return self.get(existing.value.id)

    def update(self, provider_id: str, **fields: Any) -> Result[Provider]:
        allowed = {
            "name", "kind", "api_style", "base_url", "model_family", "auth_ref", "notes",
            "price_in_per_1k", "price_out_per_1k", "currency",
        }
        existing = self.get(provider_id)
        if existing.is_err:
            return existing
        unknown = set(fields) - allowed
        if unknown:
            return Err(ValidationError(f"cannot update provider field(s) {sorted(unknown)}"))
        if "auth_ref" in fields and fields["auth_ref"] and not str(fields["auth_ref"]).startswith(
            ("secret://", "env:")
        ):
            return Err(ValidationError("auth must be a reference, never the key itself"))
        if fields:
            self._write("provider.update", {"id": existing.value.id, "fields": fields})
            self.trace("provider", "provider.updated", payload={"provider_id": existing.value.id, "fields": sorted(fields)})
        return self.get(existing.value.id)

    def remove(self, provider_id: str) -> Result[str]:
        existing = self.get(provider_id)
        if existing.is_err:
            return existing
        self._write("provider.delete", {"id": existing.value.id})
        self.trace("provider", "provider.removed", payload={"provider_id": existing.value.id})
        return Ok(existing.value.id)

    # -- availability ------------------------------------------------------
    def check(self, provider_id: str, *, timeout: float = 4.0) -> Result[dict[str, Any]]:
        """Perform a real reachability/auth probe and record the result.

        This never sends prompt content: it is a `GET /models` (or a HEAD of the base
        URL when the style has no models endpoint).
        """
        existing = self.get(provider_id)
        if existing.is_err:
            return existing
        provider = existing.value
        result = probe_provider(provider, timeout=timeout)
        result["provider_id"] = provider.id
        result["checked_at"] = iso_now()
        self._write("provider.check", {"provider_id": provider.id, **result})
        self.trace(
            "provider",
            "provider.checked",
            status="ok" if result["status"] in ("reachable", "model_missing") else "error",
            payload={
                "provider_id": provider.id,
                "status": result["status"],
                "latency_ms": result["latency_ms"],
                "models_seen": result.get("models_seen"),
            },
        )
        return Ok(result)

    def record_usage(
        self,
        provider_id: str,
        *,
        model_ref: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        self._write(
            "provider.usage",
            {
                "provider_id": provider_id,
                "model_ref": model_ref,
                "day": date.today().isoformat(),
                "requests": 1,
                "tokens_in": max(0, int(tokens_in)),
                "tokens_out": max(0, int(tokens_out)),
                "errors": 0 if ok else 1,
                "last_error": error[:300] if error else None,
            },
        )

    def stats(self) -> dict[str, Any]:
        rows = self.list()
        return {
            "providers": len(rows),
            "local": sum(1 for p in rows if p.is_local),
            "cloud": sum(1 for p in rows if not p.is_local),
            "with_consent": sum(1 for p in rows if p.consented),
            "blocked": sum(1 for p in rows if p.blocking_reason()),
            "checks": self.table_count("provider_checks"),
        }


def probe_provider(provider: Provider, *, timeout: float = 4.0) -> dict[str, Any]:
    """Reachability/auth probe. Returns a status dict; never raises for network errors."""
    if not provider.base_url:
        return {"status": "unreachable", "latency_ms": None, "detail": "no base_url configured", "models_seen": None}
    url = provider.base_url.rstrip("/")
    path = "/models"
    if provider.api_style == "anthropic":
        path = "/v1/models"
    elif provider.api_style == "gemini":
        path = "/v1beta/models"
    target = url + path
    headers = {"Accept": "application/json", "User-Agent": "archx-agent/probe"}
    if provider.auth_ref:
        try:
            from archx_agent.helpers.config import resolve_secret

            value = resolve_secret(provider.auth_ref)
            if provider.api_style == "anthropic":
                headers["x-api-key"] = value
                headers["anthropic-version"] = "2023-06-01"
            elif provider.api_style == "gemini":
                headers["x-goog-api-key"] = value
            else:
                headers["Authorization"] = f"Bearer {value}"
        except Exception as exc:  # noqa: BLE001 - a missing secret is a check result
            return {"status": "auth_failed", "latency_ms": None, "detail": f"cannot resolve secret: {exc}", "models_seen": None}
    started = time.monotonic()
    try:
        request = urllib.request.Request(target, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - http(s) validated
            body = response.read(200_000).decode("utf-8", "replace")
            latency = (time.monotonic() - started) * 1000.0
            models = _count_models(body)
            return {
                "status": "reachable",
                "latency_ms": round(latency, 1),
                "detail": f"HTTP {response.status}",
                "models_seen": models,
            }
    except urllib.error.HTTPError as exc:
        latency = (time.monotonic() - started) * 1000.0
        status = "reachable"
        if exc.code in (401, 403):
            status = "auth_failed"
        elif exc.code == 404:
            status = "model_missing"
        elif exc.code == 429:
            status = "rate_limited"
        elif exc.code >= 500:
            status = "unreachable"
        return {
            "status": status,
            "latency_ms": round(latency, 1),
            "detail": f"HTTP {exc.code}",
            "models_seen": None,
        }
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        latency = (time.monotonic() - started) * 1000.0
        reason = getattr(exc, "reason", exc)
        return {
            "status": "unreachable",
            "latency_ms": round(latency, 1),
            "detail": f"{type(exc).__name__}: {reason}",
            "models_seen": None,
        }


def _count_models(body: str) -> int | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    for key in ("data", "models"):
        if isinstance(payload.get(key), list):
            return len(payload[key])
    return None


__all__ = [
    "ProviderManager",
    "Provider",
    "KNOWN_PROVIDERS",
    "CONSENT_VERSION",
    "probe_provider",
    "is_loopback_url",
    "KINDS",
    "API_STYLES",
]
