"""Ngram operations for training workflows."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.application.training.tokenization import tokenize


class NGramModel:
    """A word-level n-gram model with add-k smoothing, scored by perplexity.

    Small is not the same as fake: the counts are real, the smoothing is stated, the perplexity is
    ``exp(-mean log p)`` over the evaluation text with ``<s>``/``</s>`` as boundaries, and an
    unknown word on the evaluation split is scored as ``<unk>`` rather than skipped - skipping is
    how a language model reports a number that no text could produce.
    """

    def __init__(self, order: int = 3, smoothing: float = 0.1) -> None:
        if order < 2 or order > 5:
            raise ValidationError("the n-gram order must be between 2 and 5")
        if smoothing <= 0:
            raise ValidationError("the smoothing constant must be positive")
        self.order = int(order)
        self.smoothing = float(smoothing)
        self.counts: dict[str, Counter[str]] = {}
        self.vocab: set[str] = set()

    # -- training -------------------------------------------------------
    def fit(self, texts: list[str]) -> "NGramModel":
        contexts: dict[str, Counter[str]] = defaultdict(Counter)
        vocab: set[str] = set()
        for text in texts:
            tokens = ["<s>"] * (self.order - 1) + tokenize(text) + ["</s>"]
            for index in range(self.order - 1, len(tokens)):
                history = " ".join(tokens[index - self.order + 1 : index])
                contexts[history][tokens[index]] += 1
                vocab.add(tokens[index])
        self.counts = {history: counter for history, counter in contexts.items()}
        self.vocab = vocab
        return self

    # -- scoring --------------------------------------------------------
    def _probability(self, history: str, word: str) -> float:
        counter = self.counts.get(history)
        if not counter:
            return 1.0 / (len(self.vocab) + 1)
        total = sum(counter.values()) + self.smoothing * (len(self.vocab) + 1)
        return (counter.get(word, 0) + self.smoothing) / total

    def perplexity(self, text: str) -> float:
        tokens = ["<s>"] * (self.order - 1) + tokenize(text) + ["</s>"]
        if len(tokens) <= self.order - 1:
            return float("inf")
        total = 0.0
        counted = 0
        for index in range(self.order - 1, len(tokens)):
            history = " ".join(tokens[index - self.order + 1 : index])
            word = tokens[index]
            if word != "</s>" and word not in self.vocab:
                # An unseen word is *scored*, as `<unk>`, not dropped: dropping it would make the
                # number look better the less the model knows.
                word_for_scoring = "<unk>"
            else:
                word_for_scoring = word
            total += -math.log(self._probability(history, word_for_scoring))
            counted += 1
        return math.exp(total / counted) if counted else float("inf")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "ngram",
            "order": self.order,
            "smoothing": self.smoothing,
            "vocab": sorted(self.vocab),
            "counts": {
                history: dict(counter)
                for history, counter in sorted(self.counts.items())
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NGramModel":
        model = cls(order=int(payload["order"]), smoothing=float(payload["smoothing"]))
        model.vocab = set(payload.get("vocab") or [])
        model.counts = {
            history: Counter(counter)
            for history, counter in (payload.get("counts") or {}).items()
        }
        return model
