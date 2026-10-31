"""Capabilities operations for permission policy."""

from __future__ import annotations

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.managers.permissions.constants import CAPABILITIES
from archx_agent.managers.permissions.records import Capability


def capability_names() -> list[str]:
    return sorted(CAPABILITIES)


def _validate_capability(name: str) -> Capability:
    if name not in CAPABILITIES:
        raise ValidationError(
            f"unknown capability {name!r} (known: {', '.join(capability_names())})"
        )
    return CAPABILITIES[name]
