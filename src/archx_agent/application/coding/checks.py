"""Checks operations for coding sessions."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.managers.coding import CodeRun
from archx_agent.application.coding.constants import CHECKS_FILE, _CHECK_NAME
from archx_agent.application.coding.records import Check


def _parse_checks(data: Any) -> list[Check]:
    """Strict: an unknown field is a typo, and a typo in a test command is a wasted afternoon."""
    if not isinstance(data, dict):
        raise ValidationError(f'{CHECKS_FILE} must be an object with a "checks" list')
    unknown = sorted(set(data) - {"checks", "version"})
    if unknown:
        raise ValidationError(
            f"{CHECKS_FILE} has unknown field(s): {', '.join(unknown)}"
        )
    entries = data.get("checks")
    if not isinstance(entries, list):
        raise ValidationError(f'{CHECKS_FILE} needs a "checks" list')
    checks: list[Check] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValidationError(f"check #{index + 1} must be an object")
        extra = sorted(set(entry) - {"name", "command", "timeout", "description"})
        if extra:
            raise ValidationError(
                f"check #{index + 1} has unknown field(s): {', '.join(extra)}"
            )
        name = str(entry.get("name") or "").strip()
        command = str(entry.get("command") or "").strip()
        if not _CHECK_NAME.match(name):
            raise ValidationError(
                f"check #{index + 1} needs a name of a-z, 0-9, '-' or '_' (got {name!r})"
            )
        if name in seen:
            raise ValidationError(f"two checks are named {name!r}")
        seen.add(name)
        if not command:
            raise ValidationError(f"check {name!r} has no command")
        timeout = entry.get("timeout")
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            raise ValidationError(
                f"check {name!r} has a timeout that is not a positive integer"
            )
        checks.append(
            Check(
                name=name,
                command=command,
                timeout=timeout,
                description=str(entry.get("description") or ""),
            )
        )
    return checks


def _timeout_of(run: CodeRun) -> int | None:
    """The timeout a run used, so a replay is subject to the same bound."""
    return run.timeout_seconds
