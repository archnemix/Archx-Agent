"""ExperimentService records, constants and pure validation helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.managers.experiments import Experiment

_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:/=+@-]{0,200}$")

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

METRIC_SOURCES = ("none", "stdout-json", "file")

@dataclass
class ParamSpec:
    """One declared knob: a name, an optional default, and what it means."""

    name: str
    default: Any = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "default": self.default, "description": self.description}

def _resolve_params(experiment: Experiment, supplied: Mapping[str, Any]) -> dict[str, str]:
    """Merge the defaults with what was passed, and refuse anything ambiguous."""
    declared = {str(entry["name"]): entry.get("default") for entry in experiment.params}
    unknown = sorted(set(supplied) - set(declared))
    if unknown:
        raise ValidationError(
            f"{unknown[0]!r} is not a parameter of this experiment "
            f"(declared: {', '.join(sorted(declared)) or 'none'})"
        )
    merged = {**declared, **supplied}
    resolved: dict[str, str] = {}
    for name in sorted(merged):
        value = merged[name]
        if value is None:
            raise ValidationError(f"parameter {name!r} has no value; pass it or give it a default")
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, (int, float)):
            text = repr(value) if isinstance(value, float) else str(value)
        elif isinstance(value, str):
            text = value.strip()
        else:
            raise ValidationError(f"parameter {name!r} must be a number or a string")
        if not _SAFE_VALUE.match(text):
            raise ValidationError(
                f"parameter {name!r} is {value!r}; a substituted value has to be a single "
                "shell-safe token (letters, digits and _ . : / = + @ -)"
            )
        resolved[name] = text
    return resolved

def _parse_params(entries: Sequence[Mapping[str, Any]]) -> list[ParamSpec]:
    specs: list[ParamSpec] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, Mapping):
            raise ValidationError(f"parameter #{index} must be an object")
        extra = sorted(set(entry) - {"name", "default", "description"})
        if extra:
            raise ValidationError(f"parameter #{index} has unknown field(s): {', '.join(extra)}")
        name = str(entry.get("name") or "").strip()
        if not _IDENTIFIER.match(name):
            raise ValidationError(
                f"parameter #{index} needs a name like a Python identifier (got {name!r})"
            )
        if name in seen:
            raise ValidationError(f"two parameters are named {name!r}")
        seen.add(name)
        default = entry.get("default")
        if default is not None and not isinstance(default, (str, int, float, bool)):
            raise ValidationError(f"parameter {name!r} has a default that is not a value")
        specs.append(
            ParamSpec(name=name, default=default, description=str(entry.get("description") or ""))
        )
    return specs

def _parse_metrics_source(source: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise ValidationError('metrics must be an object such as {"kind": "none"}')
    extra = sorted(set(source) - {"kind", "path"})
    if extra:
        raise ValidationError(f"metrics has unknown field(s): {', '.join(extra)}")
    kind = str(source.get("kind") or "none")
    if kind not in METRIC_SOURCES:
        raise ValidationError(
            f"unknown metrics source {kind!r} (known: {', '.join(METRIC_SOURCES)})"
        )
    if kind != "file":
        if source.get("path"):
            raise ValidationError('only a "file" metrics source takes a path')
        return {"kind": kind}
    path = str(source.get("path") or "metrics.json").strip()
    if not path or path.startswith("/") or ".." in Path(path).parts:
        raise ValidationError("a metrics file must be a relative path inside the experiment directory")
    return {"kind": "file", "path": path}

def _metrics_from_json(text: str, where: str) -> tuple[dict[str, float], str | None]:
    """Read a flat object of numbers, or say precisely why it is not one."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"{where} is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return {}, f"{where} must be a JSON object of numbers"
    if not data:
        return {}, f"{where} had no metrics in it"
    metrics: dict[str, float] = {}
    for key, value in data.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return {}, f"{where} has a non-numeric value for {key!r}"
        metrics[str(key)] = float(value)
    return metrics, None

def _params_label(params: Mapping[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(params.items())) or "defaults"

def _metrics_label(metrics: Mapping[str, float]) -> str:
    return ", ".join(f"{key}={value:g}" for key, value in metrics.items())
