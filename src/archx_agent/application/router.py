"""Capability-safe model router (M21).

The router answers one question - *which model may perform this task, and why* - with
rules strict enough that the answer is auditable:

* a capability is **verified** when a recorded probe of that model succeeded;
* **inferred** when our own adapter implements it (a fact about our code, not a claim
  about the model);
* **unverified** when it was claimed and never exercised;
* **unsupported** when a probe measured it as broken;
* **unavailable** when the artifact or runtime is missing.

`unverified` is not good enough for a capability the user asked for, except chat, which
is the baseline interaction and can be enabled per workspace
(``router.allow_unverified_chat``) with the decision recording that. `unsupported` and
`unavailable` are never routed to.

Every rejected candidate keeps its reasons, so "why did it pick that one?" is answerable
without guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from archx_agent.helpers.exceptions import (
    ArchxError,
    ModelNotFoundError,
    UnsupportedCapabilityError,
    ValidationError,
)
from archx_agent.managers.models import CAPABILITY_STATES, ModelManager, ModelRecord

#: Capabilities that can be proven by driving a chat-style runtime.
PROBEABLE = ("chat", "tools", "json")

#: States that may satisfy a requirement without an explicit opt-in.
ACCEPTED_BY_DEFAULT = ("verified", "inferred")


@dataclass
class Candidate:
    """One evaluated model, kept even when rejected so the decision is explainable."""

    model_id: str
    name: str
    runtime: str
    provider: str
    local: bool
    simulated: bool
    capability_states: dict[str, dict[str, Any]]
    score: float = 0.0
    rank: int | None = None
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "runtime": self.runtime,
            "provider": self.provider,
            "local": self.local,
            "simulated": self.simulated,
            "eligible": self.eligible,
            "rank": self.rank,
            "score": round(self.score, 2),
            "capabilities": self.capability_states,
            "blockers": self.blockers,
            "notes": self.notes,
        }


@dataclass
class RoutingDecision:
    """The full, explainable outcome of a routing request."""

    task: str
    required: tuple[str, ...]
    chosen: ModelRecord | None
    candidates: list[Candidate]
    fallbacks: list[ModelRecord] = field(default_factory=list)
    policy: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def chosen_candidate(self) -> Candidate | None:
        if self.chosen is None:
            return None
        return next((c for c in self.candidates if c.model_id == self.chosen.id), None)

    def explanation(self) -> str:
        if self.chosen is None:
            rejected = [f"{c.name}: {'; '.join(c.blockers)}" for c in self.candidates]
            return "no eligible model" + (" - " + " | ".join(rejected) if rejected else "")
        chosen = self.chosen_candidate
        parts = [f"chose {self.chosen.name} for {self.task}"]
        if chosen:
            for capability in self.required:
                state = chosen.capability_states.get(capability, {})
                parts.append(f"{capability}={state.get('state', 'unknown')} ({state.get('basis', '-')})")
        parts.append(f"{len([c for c in self.candidates if not c.eligible])} candidate(s) rejected")
        return "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "required": list(self.required),
            "chosen": self.chosen.id if self.chosen else None,
            "chosen_name": self.chosen.name if self.chosen else None,
            "fallbacks": [m.id for m in self.fallbacks],
            "explanation": self.explanation(),
            "policy": self.policy,
            "notes": self.notes,
            "candidates": [c.to_dict() for c in self.candidates],
            "acceptable": bool(self.chosen),
        }


class ModelRouter:
    """Selects models for tasks using capability states and workspace policy."""

    def __init__(
        self,
        models: ModelManager,
        *,
        config: Any,
        runtime_for: Callable[[ModelRecord], Any],
        availability_check: Callable[[ModelRecord], tuple[bool, str]] | None = None,
        remote_check: Callable[[ModelRecord], None] | None = None,
        events: Any | None = None,
    ) -> None:
        self.models = models
        self.config = config
        self.runtime_for = runtime_for
        self.availability_check = availability_check
        self.remote_check = remote_check
        self.events = events

    # -- policy ------------------------------------------------------------
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

    # -- evaluation --------------------------------------------------------
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

    # -- routing -----------------------------------------------------------
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

    # -- probes ------------------------------------------------------------
    def probe(
        self,
        model_id: str,
        capability: str = "chat",
        *,
        record: bool = True,
    ) -> dict[str, Any]:
        """Actually exercise a capability and record the measurement.

        Nothing here is a simulation of a test: the runtime is driven, the result is
        inspected, and the outcome is written to ``model_capability_tests`` where the
        router reads it back.
        """
        if capability not in PROBEABLE:
            raise ValidationError(
                f"cannot probe {capability!r} here (probeable: {', '.join(PROBEABLE)}); "
                "capabilities such as vision or OCR need their own adapter and are not invented"
            )
        record_obj = self.models.get(model_id)
        if record_obj.is_err:
            record_obj = self.models.by_name(model_id)
        if record_obj.is_err:
            raise ModelNotFoundError(f"no model matches {model_id!r}", model=model_id)
        model = record_obj.value
        from archx_agent.adapters.model_runtime import GenerationParams  # local import: adapter layer

        runtime = self.runtime_for(model)
        messages: list[dict[str, str]] = [{"role": "user", "content": _probe_prompt(capability)}]
        params = GenerationParams(temperature=0.0, max_tokens=16)
        import time

        started = time.perf_counter()
        try:
            if capability == "tools":
                # The tool has to *be offered* for the reply to mean anything: a model that is
                # never given a tool cannot demonstrate calling one.
                caller = getattr(runtime, "chat_with_tools", None)
                if caller is None:
                    raise ValidationError(
                        f"the {model.runtime} runtime has no tool-calling path, so tool use "
                        "cannot be probed (evidence is not invented)"
                    )
                result = caller(messages, params)
            else:
                result = runtime.chat(messages, params)
            latency = (time.perf_counter() - started) * 1000.0
            text = (result.text or "").strip()
            raw = getattr(result, "raw", {}) or {}
            tool_calls = raw.get("tool_calls") or []
            if capability == "tools":
                if not tool_calls:
                    raise ValidationError(
                        "the runtime answered but did not return a tool call; tool use is not proven"
                    )
                name = tool_calls[0].get("name") or "a tool"
                text = f"called {name} with {tool_calls[0].get('arguments') or '{}'}"
            elif not text:
                raise ValidationError("the runtime returned an empty reply")
            if capability == "json":
                _require_json(text)
            if capability == "tools":
                detail = f"{text}, finish_reason={result.finish_reason}"
            else:
                detail = f"{len(text)} chars, finish_reason={result.finish_reason}"
            outcome = "passed"
            payload = {"capability": capability, "outcome": outcome, "detail": detail}
        except Exception as exc:  # noqa: BLE001 - any failure is a measurement
            latency = (time.perf_counter() - started) * 1000.0
            outcome = "failed"
            detail = f"{type(exc).__name__}: {getattr(exc, 'message', str(exc))}"[:400]
            payload = {"capability": capability, "outcome": outcome, "detail": detail}
            text = ""

        if record:
            self.models.record_capability_test(
                model.id, capability, outcome, detail=detail, latency_ms=round(latency, 1)
            )
            if outcome == "passed":
                self.models.set_verified_capabilities(
                    model.id,
                    sorted(set(model.verified_capabilities) | {capability}),
                    basis=f"probe passed at {latency:.0f} ms",
                )
            elif self.events is not None:
                self.events.record(
                    "model",
                    "model.probe_failed",
                    status="error",
                    payload={"model_id": model.id, "capability": capability, "detail": detail},
                )
        if self.events is not None:
            self.events.record(
                "model",
                "model.probed",
                status="ok" if outcome == "passed" else "error",
                duration_ms=round(latency, 1),
                payload={
                    "model_id": model.id,
                    "capability": capability,
                    "outcome": outcome,
                    "simulated": model.runtime == "scripted",
                },
            )
        return {
            "model_id": model.id,
            "model": model.name,
            "capability": capability,
            "outcome": outcome,
            "detail": detail,
            "latency_ms": round(latency, 1),
            "state_after": self.models.capability_state(self.models.require(model.id), capability),
            "message": text[:120],
        }

    # -- helpers -----------------------------------------------------------
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


def _is_loopback(url: str | None) -> bool:
    from archx_agent.managers.providers import is_loopback_url

    return is_loopback_url(url)


def _probe_prompt(capability: str) -> str:
    if capability == "chat":
        return "Reply with the single word: ready"
    if capability == "tools":
        return "Call the provided tool with value 1."
    if capability == "json":
        return 'Reply with exactly this JSON object and nothing else: {"ok": true}'
    return "Reply briefly."


def _require_json(text: str) -> None:
    import json

    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
    try:
        json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"reply was not valid JSON: {exc}") from exc


__all__ = [
    "ModelRouter",
    "Candidate",
    "RoutingDecision",
    "PROBEABLE",
    "ACCEPTED_BY_DEFAULT",
]
