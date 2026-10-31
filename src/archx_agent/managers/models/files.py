"""Observe local catalogue files without claiming GGUF validity or inference proof."""

from __future__ import annotations

from pathlib import Path
import stat
from typing import Any

from archx_agent.helpers.jsonio import sha256_file

MIN_MODEL_BYTES = 1024


def observe_file(path: Path, *, hash_file: bool = False) -> dict[str, Any]:
    """Return filesystem facts; inaccessible/non-regular objects are never usable.

    The cheap signature detects ordinary replacements, not adversarial edits that
    preserve metadata. Only an explicitly requested whole-file hash measures bytes.
    """
    facts: dict[str, Any] = {
        "exists": False,
        "is_file": False,
        "suffix": path.suffix.lower(),
        "size_bytes": None,
        "mtime": None,
        "file_signature": None,
    }
    result = {
        "facts": facts,
        "state": "missing",
        "error": "model file disappeared",
        "sha256": None,
    }
    try:
        info = path.stat()
        facts["exists"] = True
        facts["is_file"] = stat.S_ISREG(info.st_mode)
        facts["size_bytes"] = info.st_size
        facts["mtime"] = info.st_mtime
        facts["file_signature"] = [
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        ]
        if not facts["is_file"]:
            result.update(state="invalid", error="model path is not a regular file")
        elif info.st_size < MIN_MODEL_BYTES:
            result.update(state="invalid", error="file too small to be a model")
        else:
            result.update(state="usable", error=None)
            if hash_file:
                result["sha256"] = sha256_file(path)
    except FileNotFoundError:
        facts.update(
            exists=False,
            is_file=False,
            size_bytes=None,
            mtime=None,
            file_signature=None,
        )
        result.update(state="missing", error="model file disappeared", sha256=None)
    except OSError as exc:
        result.update(
            state="invalid",
            error=f"cannot inspect model file: {exc.strerror or type(exc).__name__}",
        )
    return result


def file_changed(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """Conservatively invalidate legacy/missing observations as well as replacements."""
    old_facts = previous.get("facts") or {}
    new_facts = current["facts"]
    if old_facts.get("file_signature") != new_facts["file_signature"]:
        return True
    old_hash = previous.get("sha256")
    return bool(old_hash is not None and old_hash != current.get("sha256"))
