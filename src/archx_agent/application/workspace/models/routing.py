"""Routing operations for workspace composition."""

from __future__ import annotations

from typing import Any, Sequence

from archx_agent.helpers.exceptions import (
    ConfigError,
    ModelNotFoundError,
)
from archx_agent.managers.models import ModelRecord
from archx_agent.managers.providers import is_loopback_url


class WorkspaceModelsRoutingMixin:
    """Models Routing responsibility for Workspace."""

    def resolve_model(
        self, model_id: str | None = None, *, task: str = "chat"
    ) -> ModelRecord:
        """Resolve which model to use for a task (capability-safe routing, M21)."""
        decision = self.route_model(task=task, model_id=model_id)
        if decision.chosen is None:  # pragma: no cover - route_model raises instead
            raise ModelNotFoundError("no model is eligible", task=task)
        return decision.chosen

    def route_model(
        self,
        *,
        task: str = "chat",
        model_id: str | None = None,
        required: Sequence[str] | None = None,
        allow_unverified: bool | None = None,
        allow_cloud: bool | None = None,
        min_context_tokens: int | None = None,
        exclude: Sequence[str] = (),
    ) -> Any:
        """Route a task to a model, returning the full decision."""
        if self.router is None:  # pragma: no cover - always built in from_config
            raise ConfigError("workspace has no router")
        return self.router.route(
            task,
            required=required,
            model_id=model_id,
            allow_unverified=allow_unverified,
            allow_cloud=allow_cloud,
            allow_simulated=self.allow_test_double,
            min_context_tokens=min_context_tokens,
            exclude=exclude,
        )

    def model_choice_explanation(self, record: ModelRecord) -> dict[str, Any]:
        return {
            "model_id": record.id,
            "name": record.name,
            "provider": record.provider,
            "runtime": record.runtime,
            # Locality is derived from the endpoint, never from a label: a model
            # called "local-http" pointing at api.openai.com is not local.
            "local": (
                True
                if record.runtime in ("llama-cpp", "scripted")
                else is_loopback_url((record.facts or {}).get("base_url"))
            ),
            "verified_capabilities": record.verified_capabilities,
            "verification_state": record.verification_state,
            "policy_local_only": bool(self.config.get("model.local_only")),
            "baseline": record.user_metadata.get("baseline", False),
        }
