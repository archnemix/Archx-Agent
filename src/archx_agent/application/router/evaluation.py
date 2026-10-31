"""ModelRouter: evaluation operations."""

from __future__ import annotations

from typing import Any, Iterable, Sequence
from archx_agent.helpers.exceptions import (
    ArchxError,
    ValidationError,
)
from archx_agent.managers.models import CAPABILITY_STATES, ModelRecord

from .records import PROBEABLE, Candidate, _is_loopback

class ModelRouterEvaluationMixin:
    def policy(self, *, allow_unverified: bool | None = None, allow_cloud: bool | None = None) -> dict[str, Any]:
        return {
            "require_verified": bool(self.config.get("router.require_verified")),
            "allow_unverified_chat": bool(self.config.get("router.allow_unverified_chat")),
            "allow_unverified": allow_unverified,
            "allow_cloud": (
                bool(self.config.get("router.allow_cloud")) if allow_cloud is None else bool(allow_cloud)
            ),
            "prefer_local": bool(self.config.get("router.prefer_local")),
            "fallback": bool(self.config.get("router.fallback")),
            "max_fallbacks": int(self.config.get("router.max_fallbacks")),
            "default_id": self.config.get("model.default_id") or None,
            "local_only": bool(self.config.get("model.local_only")),
        }

    def evaluate(
        self,
        record: ModelRecord,
        *,
        task: str,
        required: Sequence[str],
        policy: dict[str, Any],
        allow_simulated: bool,
        min_context_tokens: int | None,
    ) -> Candidate:
        simulated = record.runtime == "scripted" or bool((record.claims or {}).get("simulated"))
        base_url = (record.facts or {}).get("base_url") if record.facts else None
        local = True if record.runtime in ("llama-cpp", "scripted") else _is_loopback(base_url)
        candidate = Candidate(
            model_id=record.id,
            name=record.name,
            runtime=record.runtime,
            provider=record.provider,
            local=local,
            simulated=simulated,
            capability_states={cap: self.models.capability_state(record, cap) for cap in required},
        )

        if not record.is_usable:
            candidate.blockers.append(f"model is {record.state}")
        else:
            available, why = self._runtime_available(record)
            if not available:
                candidate.blockers.append(f"runtime unavailable: {why}")
        if simulated and not allow_simulated:
            candidate.blockers.append(
                "simulated test double; run with --allow-simulated to use it deliberately"
            )
        if simulated and allow_simulated:
            candidate.notes.append("simulated: performs no inference")

        for capability in required:
            state = candidate.capability_states.get(capability, {}).get("state", "unverified")
            basis = candidate.capability_states.get(capability, {}).get("basis", "-")
            if state in ("unsupported", "unavailable"):
                candidate.blockers.append(f"{capability} is {state} ({basis})")
                continue
            if state == "verified":
                continue
            if state == "inferred" and not policy["require_verified"]:
                continue
            if policy["require_verified"]:
                candidate.blockers.append(
                    f"{capability} is {state}, not verified (router.require_verified is true)"
                )
                continue
            chat_exception = (
                capability == "chat"
                and policy["allow_unverified_chat"]
                and policy["allow_unverified"] is not False
            )
            if chat_exception or policy["allow_unverified"]:
                candidate.notes.append(f"{capability} is {state} ({basis}); allowed by policy")
                continue
            if capability in PROBEABLE:
                hint = (
                    f"probe it with `archx-agent models probe {record.name} "
                    f"--capability {capability}` or pass --allow-unverified"
                )
            else:
                hint = (
                    f"no runtime in this build provides or can measure {capability}; "
                    "add the adapter that does (capabilities are never assumed)"
                )
            candidate.blockers.append(f"{capability} is {state} ({basis}); {hint}")

        if min_context_tokens is not None:
            available = record.context_length or 0
            if available < min_context_tokens:
                candidate.blockers.append(
                    f"context window {available} is smaller than the {min_context_tokens} tokens needed"
                )

        if not local:
            if not policy["allow_cloud"]:
                candidate.blockers.append(
                    "remote endpoint; the router does not choose remote models by itself "
                    "(router.allow_cloud is false) - name it with --model to use it deliberately"
                )
            elif self.remote_check is not None:
                try:
                    self.remote_check(record)
                except ArchxError as exc:
                    candidate.blockers.append(f"remote policy: {exc.message}")

        candidate.score = self._score(record, candidate, task=task, policy=policy)
        return candidate

    def _runtime_available(self, record: ModelRecord) -> tuple[bool, str]:
        """Ask the adapter whether it can run here - without loading anything.

        Offering a model whose runtime cannot start is how a system advertises a
        capability it does not have, so this is part of eligibility, not a post-check.
        """
        if self.availability_check is not None:
            try:
                return self.availability_check(record)
            except Exception as exc:  # noqa: BLE001 - an availability check must not raise
                return False, f"{type(exc).__name__}: {exc}"
        try:
            runtime = self.runtime_for(record)  # may load; only used when no cheap check exists
        except ArchxError as exc:
            return False, exc.message
        probe = getattr(runtime, "available", None)
        return probe() if probe is not None else (True, "ready")

    def _score(self, record: ModelRecord, candidate: Candidate, *, task: str, policy: dict[str, Any]) -> float:
        score = 0.0
        for state in candidate.capability_states.values():
            level = state.get("state")
            score += {"verified": 100.0, "inferred": 60.0, "unverified": 10.0}.get(level, 0.0)
        if task in record.preferred_for():
            score += 40.0
        if policy.get("default_id") in {record.id, record.name}:
            score += 20.0
        if candidate.local and policy["prefer_local"]:
            score += 25.0
        if candidate.simulated:
            score -= 80.0
        score -= 5.0 * float(record.failure_count or 0)
        return score

    def candidates(
        self,
        *,
        task: str = "chat",
        required: Sequence[str] | None = None,
        allow_unverified: bool | None = None,
        allow_cloud: bool | None = None,
        allow_simulated: bool = False,
        min_context_tokens: int | None = None,
        include: Iterable[ModelRecord] | None = None,
    ) -> tuple[list[Candidate], dict[str, Any]]:
        policy = self.policy(allow_unverified=allow_unverified, allow_cloud=allow_cloud)
        required = tuple(required) if required is not None else ((task,) if task else ())
        from archx_agent.adapters.model_runtime import CAPABILITIES as RUNTIME_CAPABILITIES

        known = set(CAPABILITY_STATES) | set(RUNTIME_CAPABILITIES) | set(PROBEABLE)
        unknown = [cap for cap in required if cap not in known]
        if unknown:
            raise ValidationError(f"unknown capability {unknown[0]!r}")
        records = list(include) if include is not None else self.models.list(include_removed=False)
        evaluated = [
            self.evaluate(
                record,
                task=task,
                required=required,
                policy=policy,
                allow_simulated=allow_simulated,
                min_context_tokens=min_context_tokens,
            )
            for record in records
        ]
        evaluated.sort(key=lambda c: (-c.score, c.name))
        return evaluated, policy
