"""JSON, hashing and atomic file helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .exceptions import ValidationError
from .paths import ensure_directory


def canonical_json(data: Any) -> str:
    """Deterministic JSON used for hashing and equality checks."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def json_text(data: Any, *, indent: int | None = 2) -> str:
    return json.dumps(data, indent=indent, ensure_ascii=False, sort_keys=False, default=_default)


def _default(obj: Any) -> Any:
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, bytes):
        return f"<{len(obj)} bytes>"
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


def loads(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc


def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return loads(p.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ValidationError(f"{p}: {exc.message}") from exc


def atomic_write_text(path: str | os.PathLike[str], text: str) -> Path:
    """Write via a temp file + ``os.replace`` so readers never see partial data."""
    p = Path(path)
    ensure_directory(p.parent)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def atomic_write_json(path: str | os.PathLike[str], data: Any) -> Path:
    return atomic_write_text(path, json_text(data) + "\n")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike[str], *, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def file_size(path: str | os.PathLike[str]) -> int:
    return Path(path).stat().st_size


def keyed_hash(data: dict[str, Any]) -> str:
    return sha256_text(canonical_json(data))


__all__ = [
    "canonical_json",
    "json_text",
    "loads",
    "read_json",
    "atomic_write_text",
    "atomic_write_json",
    "sha256_text",
    "sha256_bytes",
    "sha256_file",
    "file_size",
    "keyed_hash",
]
