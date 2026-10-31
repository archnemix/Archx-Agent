"""Content hashing for execution targets."""

from __future__ import annotations

import hashlib


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
