"""Input validation and decoding for tool execution."""

from __future__ import annotations

from typing import Any, Mapping

from archx_agent.helpers.exceptions import (
    ToolValidationError,
)
from archx_agent.managers.tools.records import ToolSpec


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "json":
        return isinstance(value, (dict, list, int, float, bool))
    return True


def _coerce(arguments: Mapping[str, Any], spec: ToolSpec) -> dict[str, Any]:
    unknown = sorted(set(arguments) - set(spec.inputs))
    if unknown:
        accepted = ", ".join(sorted(spec.inputs)) or "none"
        raise ToolValidationError(
            f"{spec.name} does not take {', '.join(unknown)} (accepted: {accepted})"
        )
    types = spec.types or {name: "str" for name in spec.inputs}
    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        kind = types.get(key, "str")
        if (
            kind == "int"
            and isinstance(value, str)
            and value.strip().lstrip("-").isdigit()
        ):
            value = int(value)
        elif (
            kind == "bool"
            and isinstance(value, str)
            and value.strip().lower()
            in {"1", "true", "yes", "on", "0", "false", "no", "off"}
        ):
            value = value.strip().lower() in {"1", "true", "yes", "on"}
        elif kind == "float" and isinstance(value, str):
            try:
                value = float(value)
            except ValueError as exc:
                raise ToolValidationError(
                    f"{spec.name}.{key} expects float, got {value!r}"
                ) from exc
        elif kind == "json" and isinstance(value, str):
            import json as _json

            try:
                value = _json.loads(value)
            except _json.JSONDecodeError as exc:
                raise ToolValidationError(
                    f"{spec.name}.{key} expects JSON, got {value[:60]!r}"
                ) from exc
        if not _type_ok(value, kind):
            raise ToolValidationError(
                f"{spec.name}.{key} expects {kind}, got {type(value).__name__}"
            )
        cleaned[key] = value
    missing = [name for name in spec.required if name not in cleaned]
    if missing:
        raise ToolValidationError(f"{spec.name} requires {', '.join(missing)}")
    return cleaned
