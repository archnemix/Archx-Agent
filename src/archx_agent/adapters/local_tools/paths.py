"""LocalToolRuntime paths."""

from __future__ import annotations

import os
from pathlib import Path

from archx_agent.helpers.exceptions import (
    PathError,
    PathEscapesRootError,
    ToolValidationError,
)
from archx_agent.helpers.paths import resolve_within


class LocalToolRuntimePathsMixin:
    """Paths responsibility for LocalToolRuntime."""

    @property
    def resolved_roots(self) -> tuple[Path, ...]:
        return self._resolved_roots

    def resolve(self, path: str | os.PathLike[str]) -> Path:
        """Resolve ``path`` inside the roots, or refuse with the roots named."""
        candidate = str(path or "").strip()
        if not candidate:
            raise ToolValidationError("a path is required")
        if Path(candidate).expanduser().is_absolute():
            absolute = Path(candidate).expanduser()
            for root in self._resolved_roots:
                try:
                    return resolve_within(root, absolute)
                except PathEscapesRootError:
                    continue
            raise PathEscapesRootError(
                "path is outside every tool root",
                path=str(absolute),
                root=", ".join(str(r) for r in self._resolved_roots),
            )
        errors: list[str] = []
        for root in self._resolved_roots:
            try:
                return resolve_within(root, candidate)
            except PathEscapesRootError as exc:
                errors.append(exc.message)
            except PathError as exc:  # pragma: no cover - root missing at runtime
                errors.append(exc.message)
        raise PathEscapesRootError(
            "path is outside every tool root",
            path=candidate,
            root=", ".join(str(r) for r in self._resolved_roots),
        )

    def relative(self, path: Path) -> str:
        for root in self._resolved_roots:
            try:
                return str(path.relative_to(root)) or "."
            except ValueError:
                continue
        return str(path)  # pragma: no cover - resolve() guarantees containment
