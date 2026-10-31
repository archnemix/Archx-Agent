"""Transactional write handlers for provider metadata."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.urls import is_loopback_url as is_loopback_url
from archx_agent.helpers.exceptions import (
    NotFoundError,
)
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now


class ProviderManagerWritesMixin:
    """Writes responsibility for ProviderManager."""

    _COLUMN_FOR = {
        "auth_ref": "credential_ref",
        "privacy_claims": "privacy",
        "claims_verified": "verified",
        "credential_ref": "credential_ref",
        "privacy": "privacy",
        "verified": "verified",
    }

    def register_handlers(self) -> None:
        self.coordinator.register("provider.create", self._apply_create)
        self.coordinator.register("provider.update", self._apply_update)
        self.coordinator.register("provider.delete", self._apply_delete)
        self.coordinator.register("provider.check", self._apply_check)
        self.coordinator.register("provider.usage", self._apply_usage)

    def _apply_create(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        p = payload["provider"]
        tx.execute(
            "INSERT INTO providers (id, name, slug, kind, api_style, base_url, model_family,"
            " credential_ref, is_local, enabled, privacy, privacy_confirmed, claim_source, verified,"
            " price_in_per_1k, price_out_per_1k, currency, notes, consent_at, consent_version,"
            " created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                p["id"],
                p["name"],
                p["slug"],
                p["kind"],
                p["api_style"],
                p["base_url"],
                p["model_family"],
                p["auth_ref"],
                int(p["is_local"]),
                int(p["enabled"]),
                json_text(p["privacy_claims"]),
                json_text(p["privacy_confirmed"]),
                p["claim_source"],
                int(p["claims_verified"]),
                p["price_in_per_1k"],
                p["price_out_per_1k"],
                p["currency"],
                p["notes"],
                p["consent_at"],
                p["consent_version"],
                p["created_at"],
                p["updated_at"],
            ),
        )
        return {"id": p["id"]}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields: dict[str, Any] = {
            self._COLUMN_FOR.get(k, k): v for k, v in payload["fields"].items()
        }
        fields["updated_at"] = iso_now()
        columns = ", ".join(f"{name} = ?" for name in fields)
        values = [json_text(v) if isinstance(v, dict) else v for v in fields.values()]
        for index, name in enumerate(fields):
            if name in {"is_local", "enabled", "claims_verified"}:
                values[index] = int(bool(values[index]))
        affected = tx.execute(
            f"UPDATE providers SET {columns} WHERE id = ?", (*values, payload["id"])
        )
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
            (
                c["provider_id"],
                c["checked_at"],
                c["status"],
                c["latency_ms"],
                c["detail"],
                c["models_seen"],
            ),
        )
        return {"provider_id": c["provider_id"]}

    def _apply_usage(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        u = payload
        tx.execute(
            "INSERT INTO provider_usage (provider, model_id, kind, prompt_tokens, completion_tokens,"
            " cost_estimate, success, error_code, occurred_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                u["provider_id"],
                u.get("model_ref"),
                u.get("kind", "chat"),
                u["tokens_in"],
                u["tokens_out"],
                u.get("cost_estimate"),
                int(not u.get("errors")),
                (u.get("last_error") or None),
                iso_now(),
            ),
        )
        return {"provider_id": u["provider_id"]}
