"""ModelRouter records, constants and pure validation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.managers.models import ModelRecord

PROBEABLE = ("chat", "tools", "json")

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
