"""Token counting.

Contract: :class:`Tokenizer` wraps either a real model tokenizer or the
documented approximation. Every context decision records which one was used so
a truncated prompt can always be explained.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol, Sequence

_WORD = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class Tokenizer(Protocol):
    name: str
    exact: bool

    def count(self, text: str) -> int: ...

    def count_messages(self, messages: Sequence[dict[str, str]]) -> int: ...


@dataclass
class HeuristicTokenizer:
    """Conservative approximation: ~1 token per 3.6 chars, min 1 per word.

    Deliberately over-estimates slightly. Under-estimating silently truncates
    the user's request; over-estimating only wastes a little context.
    """

    name: str = "heuristic(3.6 chars/token)"
    exact: bool = False
    chars_per_token: float = 3.6
    per_message_overhead: int = 4

    def count(self, text: str) -> int:
        if not text:
            return 0
        by_chars = math.ceil(len(text) / self.chars_per_token)
        by_words = len(_WORD.findall(text))
        return max(1, by_chars, int(by_words * 1.15))

    def count_messages(self, messages: Sequence[dict[str, str]]) -> int:
        total = 0
        for msg in messages:
            content = msg.get("content") or ""
            role = msg.get("role") or ""
            total += self.count(content) + self.count(role) + self.per_message_overhead
        return total + 3


class CallableTokenizer:
    """Adapter around a real tokenizer (e.g. ``llama_cpp`` or ``tiktoken``)."""

    def __init__(self, name: str, encode: object, *, per_message_overhead: int = 4) -> None:
        self.name = name
        self.exact = True
        self._encode = encode
        self.per_message_overhead = per_message_overhead

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._encode(text))  # type: ignore[operator]

    def count_messages(self, messages: Sequence[dict[str, str]]) -> int:
        total = 0
        for msg in messages:
            total += self.count(msg.get("content") or "") + self.per_message_overhead
        return total + 3


_DEFAULT = HeuristicTokenizer()


def get_tokenizer(name: str | None = None) -> Tokenizer | None:
    """Return a tokenizer by name, or ``None`` when ``name`` is unknown.

    Callers that need an exact tokenizer must handle ``None`` by falling back to
    the heuristic *and* labelling the approximation.
    """
    if not name:
        return _DEFAULT
    try:
        import tiktoken  # type: ignore
    except Exception:  # noqa: BLE001 - optional dependency
        tiktoken = None
    if tiktoken is not None:
        try:
            enc = tiktoken.get_encoding(name)
        except Exception:  # noqa: BLE001
            return None
        return CallableTokenizer(f"tiktoken:{name}", enc.encode)
    return None


def default_tokenizer() -> Tokenizer:
    return _DEFAULT


__all__ = ["Tokenizer", "HeuristicTokenizer", "CallableTokenizer", "get_tokenizer", "default_tokenizer"]
