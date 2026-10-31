"""Record types and row conversion for coding sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Check:
    """One named command a project says is worth running."""

    name: str
    command: str
    timeout: int | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "timeout": self.timeout,
            "description": self.description,
        }


@dataclass
class _Before:
    text: str
    sha: str | None
    available: bool
    reason: str = ""
