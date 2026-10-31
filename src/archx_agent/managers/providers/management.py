"""Management operations for provider metadata."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.urls import is_loopback_url as is_loopback_url
from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.providers.records import Provider
from archx_agent.managers.providers.probing import probe_provider


class ProviderManagerManagementMixin:
    """Management responsibility for ProviderManager."""

    def last_check(self, provider_id: str) -> dict[str, Any] | None:
        row = self.store.query_one(
            "SELECT * FROM provider_checks WHERE provider_id = ? ORDER BY id DESC LIMIT 1",
            (provider_id,),
        )
        return dict(row) if row else None

    def checks(self, provider_id: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.store.query(
            "SELECT * FROM provider_checks WHERE provider_id = ? ORDER BY id DESC LIMIT ?",
            (provider_id, limit),
        )

    def enable(self, provider_id: str, enabled: bool = True) -> Result[Provider]:
        existing = self.get(provider_id)
        if existing.is_err:
            return existing
        self._write(
            "provider.update", {"id": existing.value.id, "fields": {"enabled": enabled}}
        )
        self.trace(
            "provider",
            "provider.enabled" if enabled else "provider.disabled",
            payload={"provider_id": existing.value.id},
        )
        return self.get(existing.value.id)

    def update(self, provider_id: str, **fields: Any) -> Result[Provider]:
        allowed = {
            "name",
            "kind",
            "api_style",
            "base_url",
            "model_family",
            "auth_ref",
            "notes",
            "price_in_per_1k",
            "price_out_per_1k",
            "currency",
        }
        existing = self.get(provider_id)
        if existing.is_err:
            return existing
        unknown = set(fields) - allowed
        if unknown:
            return Err(
                ValidationError(f"cannot update provider field(s) {sorted(unknown)}")
            )
        if (
            "auth_ref" in fields
            and fields["auth_ref"]
            and not str(fields["auth_ref"]).startswith(("secret://", "env:"))
        ):
            return Err(
                ValidationError("auth must be a reference, never the key itself")
            )
        if fields:
            self._write("provider.update", {"id": existing.value.id, "fields": fields})
            self.trace(
                "provider",
                "provider.updated",
                payload={"provider_id": existing.value.id, "fields": sorted(fields)},
            )
        return self.get(existing.value.id)

    def remove(self, provider_id: str) -> Result[str]:
        existing = self.get(provider_id)
        if existing.is_err:
            return existing
        self._write("provider.delete", {"id": existing.value.id})
        self.trace(
            "provider", "provider.removed", payload={"provider_id": existing.value.id}
        )
        return Ok(existing.value.id)

    def check(
        self, provider_id: str, *, timeout: float = 4.0
    ) -> Result[dict[str, Any]]:
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
            status="ok"
            if result["status"] in ("reachable", "model_missing")
            else "error",
            payload={
                "provider_id": provider.id,
                "status": result["status"],
                "latency_ms": result["latency_ms"],
                "models_seen": result.get("models_seen"),
            },
        )
        return Ok(result)

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
