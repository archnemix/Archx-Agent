"""Rendering operations for workflow definitions."""

from __future__ import annotations

import re
from typing import Any, Mapping

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.managers.workflows.constants import _TEMPLATE_RE


def render(template: str, context: Mapping[str, Any]) -> str:
    """Substitute ``{{name}}`` placeholders, refusing anything unknown.

    A silently-rendered-as-empty placeholder would let a plan run with an argument the
    author did not intend, so an unknown name is a validation error naming what is
    available.
    """

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            available = ", ".join(sorted(context)) or "none"
            raise ValidationError(
                f"unknown template variable {{{{{key}}}}} (available: {available})"
            )
        value = context[key]
        return value if isinstance(value, str) else json_text(value)

    return _TEMPLATE_RE.sub(replace, template)


def render_inputs(value: Any, inputs: Mapping[str, Any]) -> Any:
    """Substitute only ``{{input.*}}`` placeholders, leaving run-time ones alone.

    Templates are rendered twice in their life: inputs when the workflow is created, and
    step references when a step actually runs. Replacing everything now would fail on
    ``{{step.1.output}}`` - which is not known yet - so this pass is deliberately partial.
    """

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if not key.startswith("input."):
            return match.group(0)
        name = key[len("input.") :]
        if name not in inputs:
            raise ValidationError(
                f"template needs --input {name}=... (given: {', '.join(sorted(inputs)) or 'none'})"
            )
        value = inputs[name]
        return value if isinstance(value, str) else json_text(value)

    if isinstance(value, str):
        return _TEMPLATE_RE.sub(replace, value)
    if isinstance(value, Mapping):
        return {key: render_inputs(item, inputs) for key, item in value.items()}
    if isinstance(value, list):
        return [render_inputs(item, inputs) for item in value]
    return value


def render_value(value: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        return render(value, context)
    if isinstance(value, Mapping):
        return {key: render_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [render_value(item, context) for item in value]
    return value
