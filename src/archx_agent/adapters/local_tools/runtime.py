"""Compose filesystem and process operations with explicit resource limits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ToolValidationError,
)
from archx_agent.adapters.local_tools.paths import LocalToolRuntimePathsMixin
from archx_agent.adapters.local_tools.reading import LocalToolRuntimeReadingMixin
from archx_agent.adapters.local_tools.writing import LocalToolRuntimeWritingMixin
from archx_agent.adapters.local_tools.processes import LocalToolRuntimeProcessesMixin


@dataclass
class LocalToolRuntime(
    LocalToolRuntimePathsMixin,
    LocalToolRuntimeReadingMixin,
    LocalToolRuntimeWritingMixin,
    LocalToolRuntimeProcessesMixin,
):
    """Runs local operations inside a fixed set of roots."""

    roots: tuple[str, ...]

    max_file_bytes: int = 2_000_000

    max_output_bytes: int = 200_000

    timeout_seconds: int = 60

    denylist: tuple[str, ...] = ()

    home: str | None = None

    def __post_init__(self) -> None:
        for name in ("max_file_bytes", "max_output_bytes", "timeout_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ToolValidationError(f"{name} must be a positive integer")
        if not self.roots:
            raise ToolValidationError("tool runtime needs at least one root directory")
        self._resolved_roots = tuple(Path(r).expanduser().resolve() for r in self.roots)
        for root in self._resolved_roots:
            if not root.is_dir():
                raise ToolValidationError(f"tool root is not a directory: {root}")

    def limits(self) -> dict[str, Any]:
        return {
            "roots": [str(r) for r in self._resolved_roots],
            "max_file_bytes": self.max_file_bytes,
            "max_output_bytes": self.max_output_bytes,
            "timeout_seconds": self.timeout_seconds,
            "shell_denylist": list(self.denylist),
        }
