"""Usage operations for provider metadata."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from archx_agent.helpers.urls import is_loopback_url as is_loopback_url
from archx_agent.helpers.exceptions import (
    QuotaExhaustedError,
)
from archx_agent.helpers.result import Result
from archx_agent.managers.providers.records import Provider


class ProviderManagerUsageMixin:
    """Usage responsibility for ProviderManager."""

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
            "SELECT price_in_per_1k, price_out_per_1k, currency FROM providers WHERE id = ?",
            (provider_id,),
        )
        cost = None
        if provider and (
            provider["price_in_per_1k"] is not None
            or provider["price_out_per_1k"] is not None
        ):
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
        self,
        provider_id: str,
        *,
        max_requests_per_day: int | None = None,
        max_tokens_per_day: int | None = None,
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
        self._write(
            "provider.update", {"id": existing.value.id, "fields": {"quotas": quotas}}
        )
        self.trace(
            "provider",
            "provider.quota_set",
            payload={"provider_id": existing.value.id, "quotas": quotas},
        )
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
