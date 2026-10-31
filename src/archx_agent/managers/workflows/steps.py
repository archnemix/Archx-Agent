"""Steps operations for workflow definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.managers.workflows.constants import MODES, STEP_KINDS, _STEP_KEYS


@dataclass
class StepSpec:
    kind: str
    title: str = ""
    prompt: str | None = None
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    query: str | None = None
    text: str | None = None
    goal: str | None = None
    steps: list["StepSpec"] = field(default_factory=list)
    model: str | None = None
    continue_on_error: bool = False
    limit: int = 5

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "title": self.title or self.kind}
        for key in ("prompt", "tool", "query", "text", "goal", "model"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        if self.args:
            data["args"] = self.args
        if self.steps:
            data["steps"] = [step.to_dict() for step in self.steps]
        if self.continue_on_error:
            data["continue_on_error"] = True
        if self.kind == "memory" and self.limit != 5:
            data["limit"] = self.limit
        return data


def parse_step(raw: Mapping[str, Any], *, index: int = 0) -> StepSpec:
    if not isinstance(raw, Mapping):
        raise ValidationError(
            f"step {index + 1} must be an object, got {type(raw).__name__}"
        )
    unknown = sorted(set(raw) - _STEP_KEYS)
    if unknown:
        raise ValidationError(
            f"step {index + 1} has unknown field(s): {', '.join(unknown)} "
            f"(known: {', '.join(sorted(_STEP_KEYS))})"
        )
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in STEP_KINDS:
        raise ValidationError(
            f"step {index + 1} has unknown kind {kind!r} (known: {', '.join(STEP_KINDS)})"
        )
    title = str(raw.get("title") or "").strip()
    step = StepSpec(
        kind=kind,
        title=title,
        prompt=_text_or_none(raw.get("prompt")),
        tool=_text_or_none(raw.get("tool")),
        query=_text_or_none(raw.get("query")),
        text=_text_or_none(raw.get("text")),
        goal=_text_or_none(raw.get("goal")),
        model=_text_or_none(raw.get("model")),
        continue_on_error=bool(raw.get("continue_on_error")),
        limit=_limit(raw.get("limit")),
    )
    args = raw.get("args") or {}
    if not isinstance(args, Mapping):
        raise ValidationError(f"step {index + 1} ({kind}) args must be an object")
    step.args = {str(key): value for key, value in args.items()}
    nested = raw.get("steps") or []
    if not isinstance(nested, list):
        raise ValidationError(f"step {index + 1} ({kind}) steps must be a list")
    step.steps = [
        parse_step(item, index=position) for position, item in enumerate(nested)
    ]
    if step.kind == "model" and not step.prompt:
        raise ValidationError(f"step {index + 1} is a model step without a prompt")
    if step.kind == "tool" and not step.tool:
        raise ValidationError(f"step {index + 1} is a tool step without a tool name")
    if step.kind == "memory" and not step.query:
        raise ValidationError(f"step {index + 1} is a memory step without a query")
    if step.kind == "note" and not step.text:
        raise ValidationError(f"step {index + 1} is a note step without text")
    if step.kind == "subagent" and not step.goal:
        raise ValidationError(f"step {index + 1} is a subagent step without a goal")
    if step.kind != "subagent" and step.steps:
        raise ValidationError(f"step {index + 1} ({kind}) cannot contain nested steps")
    if step.limit < 1 or step.limit > 50:
        raise ValidationError(f"step {index + 1} limit must be between 1 and 50")
    if not step.title:
        step.title = _default_title(step)
    return step


def _limit(value: Any) -> int:
    if value is None:
        return 5
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"step limit must be an integer, got {value!r}") from exc


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _default_title(step: StepSpec) -> str:
    if step.kind == "model":
        return (step.prompt or "model")[:60]
    if step.kind == "tool":
        return f"{step.tool}"
    if step.kind == "memory":
        return f"recall: {step.query}"
    if step.kind == "subagent":
        return f"subagent: {step.goal}"[:60]
    return step.kind


def parse_steps(raw: Any) -> list[StepSpec]:
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:  # pragma: no cover - callers parse first
            raise ValidationError(f"steps are not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise ValidationError("steps must be a list")
    return [parse_step(item, index=position) for position, item in enumerate(raw)]


def count_steps(steps: Sequence[StepSpec]) -> int:
    total = 0
    for step in steps:
        total += 1
        total += count_steps(step.steps)
    return total


def validate_definition(
    definition: Mapping[str, Any],
    *,
    tools=None,
    max_steps: int = 40,
) -> dict[str, Any]:
    """Validate a workflow definition and return a normalised copy.

    ``tools`` is the live registry (or ``None`` to skip the tool-existence check). A tool
    that does not exist is refused here rather than silently skipped at run time: a plan
    that names a tool the machine does not have is wrong, not merely unlucky.
    """
    if not isinstance(definition, Mapping):
        raise ValidationError("a workflow definition must be a JSON object")
    known = {"name", "goal", "mode", "steps", "model", "metadata", "description"}
    unknown = sorted(set(definition) - known)
    if unknown:
        raise ValidationError(
            f"unknown workflow field(s): {', '.join(unknown)} (known: {', '.join(sorted(known))})"
        )
    name = str(definition.get("name") or "").strip()
    if not name:
        raise ValidationError("a workflow needs a name")
    if len(name) > 120:
        raise ValidationError("a workflow name must be 120 characters or fewer")
    goal = str(definition.get("goal") or "").strip()
    mode = str(definition.get("mode") or "user").strip().lower()
    if mode not in MODES:
        raise ValidationError(
            f"unknown workflow mode {mode!r} (known: {', '.join(MODES)})"
        )
    steps = parse_steps(definition.get("steps"))
    if not steps:
        raise ValidationError("a workflow needs at least one step")
    total = count_steps(steps)
    if total > max_steps:
        raise ValidationError(
            f"the workflow has {total} steps, above agent.max_steps={max_steps}"
        )
    metadata = definition.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        raise ValidationError("workflow metadata must be an object")
    model = _text_or_none(definition.get("model"))

    if tools is not None:
        for step in _walk(steps):
            if step.kind != "tool":
                continue
            try:
                tools.spec(str(step.tool))
            except Exception as exc:  # noqa: BLE001 - ToolNotFoundError is the normal case
                message = getattr(exc, "message", None) or str(exc)
                raise ValidationError(
                    f"step '{step.title}' names a tool that is not registered: {message}"
                ) from exc

    return {
        "name": name,
        "goal": goal,
        "mode": mode,
        "model": model,
        "steps": [step.to_dict() for step in steps],
        "metadata": dict(metadata),
    }


def _walk(steps: Sequence[StepSpec]):
    for step in steps:
        yield step
        yield from _walk(step.steps)
