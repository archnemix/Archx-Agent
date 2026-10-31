"""Tokenization operations for training workflows."""

from __future__ import annotations

import hashlib

from archx_agent.application.training.constants import FEATURE_DIM, _WORD


def tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _hash_feature(word: str) -> int:
    return int(hashlib.sha256(word.encode("utf-8")).hexdigest()[:8], 16) % FEATURE_DIM
