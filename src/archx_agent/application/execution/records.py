"""Record types and row conversion for execution targets."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any


@dataclass
class Probe:
    """Whether a backend can be used here, and what it would take."""

    kind: str
    available: bool
    summary: str
    why_not: list[str]
    enable: str | None = None
    isolation: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "available": self.available,
            "summary": self.summary,
            "why_not": list(self.why_not),
            "enable": self.enable,
            "isolation": self.isolation,
            "this_machine": platform.system(),
        }
