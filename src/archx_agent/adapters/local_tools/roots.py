"""LocalToolRuntime roots."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def default_roots(*candidates: str | None) -> tuple[str, ...]:
    """First non-empty candidate wins; used to pick project root over home workspace."""
    for candidate in candidates:
        if candidate:
            return (str(candidate),)
    return ()


def ensure_roots(candidates: Iterable[str]) -> tuple[str, ...]:
    roots = []
    for candidate in candidates:
        path = Path(candidate).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        roots.append(str(path))
    return tuple(roots)
