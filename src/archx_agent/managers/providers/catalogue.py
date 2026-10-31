"""Catalogue operations for provider metadata."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from archx_agent.helpers.urls import is_loopback_url as is_loopback_url
from archx_agent.helpers.exceptions import (
    NotFoundError,
    ValidationError,
)
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.providers.constants import (
    _SELECT,
    KINDS,
    API_STYLES,
    KNOWN_PROVIDERS,
)
from archx_agent.managers.providers.records import Provider, _from_row
from archx_agent.managers.providers.naming import _slug


class ProviderManagerCatalogueMixin:
    """Catalogue responsibility for ProviderManager."""

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
                raise ValidationError(
                    f"unknown provider kind {kind!r} (expected one of {list(KINDS)})"
                )
            api_style = (api_style or entry.get("api_style") or "openai").lower()
            if api_style not in API_STYLES:
                raise ValidationError(
                    f"unknown api style {api_style!r} (expected one of {list(API_STYLES)})"
                )
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
            local = (
                is_local
                if is_local is not None
                else (entry.get("is_local") or is_loopback_url(base_url))
            )
            if kind == "local" and not local:
                raise ValidationError(
                    "a provider declared local must use a loopback base_url"
                )
            if kind != "local" and local and base_url and not is_loopback_url(base_url):
                raise ValidationError(
                    "is_local is only allowed for a loopback base_url"
                )
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
            return Err(
                exc if isinstance(exc, ValidationError) else ValidationError(str(exc))
            )

    def get(self, provider_id: str) -> Result[Provider]:
        row = self.store.query_one(f"{_SELECT} WHERE id = ?", (provider_id,))
        if row is None:
            row = self.store.query_one(
                f"{_SELECT} WHERE slug = ?", (_slug(provider_id),)
            )
        if row is None:
            return Err(
                NotFoundError(f"provider {provider_id} not found", id=provider_id)
            )
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

    def list(
        self, *, kind: str | None = None, include_disabled: bool = True
    ) -> list[Provider]:
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
