"""Path safety helpers.

Every filesystem access driven by user input, imports, tool arguments or model
output must go through :func:`child_path` so that ``..`` traversal and symlink
escapes are rejected *before* any IO happens.
"""

from __future__ import annotations

import os
from pathlib import Path

from .exceptions import PathError, PathEscapesRootError


def ensure_directory(path: str | os.PathLike[str]) -> Path:
    """Create ``path`` (and parents) if missing and return it resolved."""
    p = Path(path).expanduser()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PathError(f"cannot create directory {p}: {exc.strerror or exc}", path=str(p)) from exc
    if not p.is_dir():
        raise PathError(f"{p} exists but is not a directory", path=str(p))
    return p.resolve()


def resolve_within(root: str | os.PathLike[str], candidate: str | os.PathLike[str]) -> Path:
    """Resolve ``candidate`` inside ``root``, following symlinks.

    Raises :class:`PathEscapesRootError` when the resolved real path is outside
    ``root`` or when a symlink inside the tree points outside it.
    """
    root_p = Path(root).expanduser()
    try:
        root_real = root_p.resolve(strict=True)
    except OSError as exc:
        raise PathError(f"root does not exist: {root_p}", path=str(root_p)) from exc
    cand = Path(candidate).expanduser()
    if not cand.is_absolute():
        cand = root_real / cand
    # Reject obvious traversal even before it exists on disk.
    normalized = Path(os.path.normpath(str(cand)))
    rel_to_root = _relative(normalized, root_real)
    if rel_to_root is not None and _has_dotdot(rel_to_root):
        raise PathEscapesRootError("path traversal detected", path=str(candidate), root=str(root_real))
    try:
        real = cand.resolve(strict=False)
    except (OSError, RuntimeError) as exc:  # RuntimeError: symlink loop
        raise PathError(f"cannot resolve path {candidate}: {exc}", path=str(candidate)) from exc
    try:
        real.relative_to(root_real)
    except ValueError as exc:
        raise PathEscapesRootError("path escapes the permitted root", path=str(candidate), root=str(root_real)) from exc
    return real


def _relative(path: Path, root: Path) -> str | None:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return None


def _has_dotdot(rel: str) -> bool:
    return any(part == ".." for part in Path(rel).parts)


def child_path(root: str | os.PathLike[str], *parts: str) -> Path:
    """Join ``parts`` onto ``root`` and guarantee the result stays inside it.

    The child does not need to exist yet.
    """
    if not parts:
        raise PathError("child_path requires at least one path component")
    candidate = Path(parts[0])
    if candidate.is_absolute():
        # Absolute children must already be inside root.
        return resolve_within(root, candidate)
    for part in parts[1:]:
        candidate = candidate / part
    return resolve_within(root, candidate)


def is_within(root: str | os.PathLike[str], candidate: str | os.PathLike[str]) -> bool:
    """Non-raising containment check (used by policy code and tests)."""
    try:
        resolve_within(root, candidate)
        return True
    except (PathError, PathEscapesRootError):
        return False


def safe_filename(name: str, *, max_length: int = 120) -> str:
    """Produce a filesystem-safe single path component."""
    if not name or not name.strip():
        raise PathError("filename must not be empty")
    cleaned = "".join(ch if (ch.isalnum() or ch in "-_. ") else "_" for ch in name).strip()
    cleaned = cleaned.replace(" ", "_")
    while ".." in cleaned:
        cleaned = cleaned.replace("..", "_")
    cleaned = cleaned.lstrip("._-") or "file"
    if set(cleaned) <= {".", "_"}:
        cleaned = "file"
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{n}B"  # pragma: no cover


def relative_to_root(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError as exc:
        raise PathEscapesRootError("path outside root", path=str(path), root=str(root)) from exc


__all__ = [
    "ensure_directory",
    "resolve_within",
    "child_path",
    "is_within",
    "safe_filename",
    "human_size",
    "relative_to_root",
]
