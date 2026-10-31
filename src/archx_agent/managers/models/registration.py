"""ModelManager registration."""

from __future__ import annotations

import json
from typing import Any, Sequence

from archx_agent.helpers.exceptions import ConflictError, ValidationError
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.models.records import ModelRecord


class ModelManagerRegistrationMixin:
    """Registration responsibility for ModelManager."""

    def register_remote(
        self,
        name: str,
        *,
        provider: str,
        runtime: str = "openai-http",
        model_ref: str | None = None,
        base_url: str | None = None,
        context_length: int = 8192,
        capabilities: Sequence[str] | None = None,
        verification: str = "inferred",
        claims: dict[str, Any] | None = None,
    ) -> ModelRecord:
        if not name.strip():
            raise ValidationError("model name must not be empty")
        if not model_ref:
            raise ValidationError("remote models require model_ref")
        # Identity for a remote model is (provider, model_ref). Registering the same
        # identity for a *different* endpoint used to silently overwrite the first entry,
        # which made two distinct services indistinguishable. Refuse instead.
        existing = self.store.query_one(
            "SELECT id, name, facts FROM models WHERE provider = ? AND path IS NULL AND model_ref = ?"
            " AND state != 'removed'",
            (provider, model_ref),
        )
        if existing is not None:
            previous = json.loads(existing["facts"] or "{}").get("base_url")
            if previous == base_url:
                return self.require(existing["id"])
            raise ConflictError(
                f"provider {provider!r} already has a model {existing['name']!r} with reference "
                f"{model_ref!r} at {previous!r}; keep the model reference unique per endpoint "
                "(or remove the old entry first)",
                model=existing["id"],
            )
        record = ModelRecord(
            id=new_id("mdl_"),
            name=name.strip(),
            provider=provider,
            runtime=runtime,
            path=None,
            model_ref=model_ref,
            format="http",
            quantization=None,
            param_count=None,
            context_length=context_length,
            size_bytes=None,
            sha256=None,
            facts={"configured": True, "base_url": base_url},
            claims=dict(claims or {}),
            user_metadata={},
            verified_capabilities=list(capabilities or []),
            capability_basis={c: verification for c in (capabilities or [])},
            verification_state=verification,
            state="usable",
            tags=[],
            notes=None,
            success_count=0,
            failure_count=0,
            discovered_at=iso_now(),
            updated_at=iso_now(),
            last_used_at=None,
            last_error=None,
        )
        result = self._write("model.register", {"model": record.to_dict()})
        return self.require(result["id"])
