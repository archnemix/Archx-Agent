"""ModelRouter: selection operations."""

from __future__ import annotations

from typing import Any, Sequence
from archx_agent.helpers.exceptions import (
    ModelNotFoundError,
    UnsupportedCapabilityError,
    ValidationError,
)

from .records import Candidate, RoutingDecision

class ModelRouterSelectionMixin:
    def route(
        self,
        task: str = "chat",
        *,
        required: Sequence[str] | None = None,
        model_id: str | None = None,
        allow_unverified: bool | None = None,
        allow_cloud: bool | None = None,
        allow_simulated: bool = False,
        min_context_tokens: int | None = None,
        exclude: Sequence[str] = (),
        record_decision: bool = True,
    ) -> RoutingDecision:
        """Choose a model, or raise with the reasons nothing was eligible."""
        if model_id:
            return self._explicit(
                model_id,
                task=task,
                required=required,
                allow_unverified=allow_unverified,
                allow_cloud=allow_cloud,
                allow_simulated=allow_simulated,
                min_context_tokens=min_context_tokens,
                record_decision=record_decision,
            )

        evaluated, policy = self.candidates(
            task=task,
            required=required,
            allow_unverified=allow_unverified,
            allow_cloud=allow_cloud,
            allow_simulated=allow_simulated,
            min_context_tokens=min_context_tokens,
        )
        excluded = set(exclude)
        eligible = [c for c in evaluated if c.eligible and c.model_id not in excluded]
        for index, candidate in enumerate(eligible, start=1):
            candidate.rank = index

        required_tuple = tuple(required) if required is not None else ((task,) if task else ())
        if not eligible:
            decision = RoutingDecision(
                task=task,
                required=required_tuple,
                chosen=None,
                candidates=evaluated,
                policy=policy,
                notes=self._no_model_notes(evaluated, task),
            )
            self._record(decision, status="error")
            raise ModelNotFoundError(
                self._no_model_message(evaluated, task),
                task=task,
            )

        chosen_candidate = eligible[0]
        chosen = self.models.require(chosen_candidate.model_id)
        fallbacks = (
            [self.models.require(c.model_id) for c in eligible[1 : 1 + policy["max_fallbacks"]]]
            if policy["fallback"]
            else []
        )
        decision = RoutingDecision(
            task=task,
            required=required_tuple,
            chosen=chosen,
            candidates=evaluated,
            fallbacks=fallbacks,
            policy=policy,
            notes=[
                f"{len(evaluated) - len(eligible)} candidate(s) rejected",
                *[n for n in chosen_candidate.notes],
            ],
        )
        self._record(decision, status="ok")
        return decision

    def _explicit(self, model_id: str, **kwargs: Any) -> RoutingDecision:
        record = self.models.get(model_id)
        if record.is_err:
            record = self.models.by_name(model_id)
        if record.is_err:
            raise ModelNotFoundError(f"no model matches {model_id!r}", model=model_id)
        task = kwargs.pop("task")
        record_decision = kwargs.pop("record_decision")
        # Naming a model is itself the user's choice: the "router picks only local models"
        # policy exists to stop the router choosing a remote model on its own. The consent
        # gates still apply (they are checked inside evaluate()).
        if kwargs.get("allow_cloud") is None:
            kwargs["allow_cloud"] = True
        evaluated, policy = self.candidates(include=[record.value], task=task, **kwargs)
        candidate = evaluated[0]
        required_tuple = tuple(candidate.capability_states)
        if candidate.blockers:
            decision = RoutingDecision(
                task=task,
                required=required_tuple,
                chosen=None,
                candidates=evaluated,
                policy=policy,
                notes=["explicitly requested model is not eligible"],
            )
            self._record(decision, status="error")
            message = f"model {record.value.name!r} cannot be used: " + "; ".join(candidate.blockers)
            if any("is unsupported" in b or "is unavailable" in b for b in candidate.blockers):
                raise UnsupportedCapabilityError(message, model=record.value.id)
            raise ValidationError(message)
        decision = RoutingDecision(
            task=task,
            required=required_tuple,
            chosen=record.value,
            candidates=evaluated,
            fallbacks=[],
            policy=policy,
            notes=["explicitly requested by the user", *candidate.notes],
        )
        if record_decision:
            self._record(decision, status="ok")
        return decision

    def _record(self, decision: RoutingDecision, *, status: str) -> None:
        if self.events is None:
            return
        self.events.record(
            "model",
            "model.routed" if status == "ok" else "model.route_failed",
            status="ok" if status == "ok" else "error",
            payload={
                "task": decision.task,
                "required": list(decision.required),
                "chosen": decision.chosen.id if decision.chosen else None,
                "fallbacks": [m.id for m in decision.fallbacks],
                "rejected": [
                    {"model": c.name, "reasons": c.blockers} for c in decision.candidates if not c.eligible
                ],
                "policy": decision.policy,
            },
        )

    @staticmethod
    def _no_model_notes(evaluated: list[Candidate], task: str) -> list[str]:
        return [f"every candidate was rejected for {task}"] if evaluated else ["no models are registered"]

    @staticmethod
    def _no_model_message(evaluated: list[Candidate], task: str) -> str:
        if not evaluated:
            return (
                f"no usable model is configured for task {task!r}: no models are registered. "
                "Run `archx-agent models discover` for local files, `models add-http` for an endpoint, "
                "or `models add-scripted` for the labelled test double."
            )
        lines = [f"no usable model can perform {task!r}:"]
        for candidate in evaluated[:6]:
            lines.append(f"  - {candidate.name}: {'; '.join(candidate.blockers) or 'not eligible'}")
        return "\n".join(lines)
