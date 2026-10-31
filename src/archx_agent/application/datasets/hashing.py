"""Content hashing for dataset preparation."""

from __future__ import annotations

import hashlib


def _norm_sha(content: str) -> str:
    """A hash of the text with runs of whitespace collapsed and case folded.

    Two files that differ only in how they were saved are the same document for the purposes of a
    train/test split, and treating them as different is how a corpus leaks into its own evaluation.
    """
    return _sha(" ".join(content.split()).lower())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
