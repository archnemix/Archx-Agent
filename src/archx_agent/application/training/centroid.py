"""Centroid operations for training workflows."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.application.training.constants import FEATURE_DIM
from archx_agent.application.training.tokenization import _hash_feature, tokenize


class CentroidModel:
    """Nearest-centroid classifier over hashed bag-of-words features.

    The point of a centroid is that its arithmetic can be checked by hand: a document's vector is
    term counts, a class's centroid is the mean of its documents, and the prediction is the nearest
    centroid by cosine. A tiny model that can be verified beats a large one nobody can inspect.
    """

    def __init__(self) -> None:
        self.centroids: dict[str, list[float]] = {}
        self.labels: list[str] = []

    @staticmethod
    def _vector(text: str) -> list[float]:
        vector = [0.0] * FEATURE_DIM
        for word in tokenize(text):
            vector[_hash_feature(word)] += 1.0
        return vector

    @staticmethod
    def _normalise(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def fit(self, examples: list[tuple[str, str]]) -> "CentroidModel":
        if not examples:
            raise ValidationError("a classifier needs at least one labelled record")
        sums: dict[str, list[float]] = defaultdict(lambda: [0.0] * FEATURE_DIM)
        counts: Counter[str] = Counter()
        for text, label in examples:
            vector = self._normalise(self._vector(text))
            target = sums[label]
            for index, value in enumerate(vector):
                target[index] += value
            counts[label] += 1
        self.centroids = {
            label: self._normalise([value / counts[label] for value in vector])
            for label, vector in sums.items()
        }
        self.labels = sorted(self.centroids)
        return self

    def predict(self, text: str) -> str:
        vector = self._normalise(self._vector(text))
        best, best_score = self.labels[0], -2.0
        for label in self.labels:
            score = sum(a * b for a, b in zip(vector, self.centroids[label]))
            if score > best_score:
                best, best_score = label, score
        return best

    def accuracy(self, examples: list[tuple[str, str]]) -> float:
        if not examples:
            return float("nan")
        hits = sum(1 for text, label in examples if self.predict(text) == label)
        return hits / len(examples)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "centroid", "labels": self.labels, "centroids": self.centroids}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CentroidModel":
        model = cls()
        model.labels = list(payload.get("labels") or [])
        model.centroids = {
            label: [float(value) for value in vector]
            for label, vector in (payload.get("centroids") or {}).items()
        }
        return model
