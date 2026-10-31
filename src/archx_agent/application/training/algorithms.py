"""Algorithms operations for training workflows."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.application.training.tokenization import tokenize
from archx_agent.application.training.ngram import NGramModel
from archx_agent.application.training.centroid import CentroidModel


def train_records(
    entries: list[dict[str, Any]], method: str, config: dict[str, Any]
) -> dict[str, Any]:
    """Train on records that are already in memory: ``{"path", "split", "label", "text"}``.

    This is the whole trainer, in one place, because it has two callers: the local run, which reads
    the files itself, and the remote worker (M37), which must not train a *different* model from the
    one the local command would have trained. A worker that reimplemented the arithmetic would make
    every remote metric a claim about a second implementation.
    """
    texts: dict[str, list[tuple[str, str]]] = {"train": [], "val": [], "test": []}
    for entry in entries:
        texts.setdefault(entry.get("split") or "train", []).append(
            (entry["path"], entry["text"])
        )
    labels = {entry["path"]: entry.get("label") for entry in entries}

    if method == "ngram":
        model = NGramModel(
            order=int(config["order"]), smoothing=float(config["smoothing"])
        )
        model.fit([text for _path, text in texts.get("train", [])])
        metrics: dict[str, dict[str, float | None]] = {}
        for split, items in texts.items():
            if not items:
                continue
            perplexities = [model.perplexity(text) for _path, text in items]
            metrics[split] = {
                "perplexity": sum(perplexities) / len(perplexities),
                "records": float(len(items)),
                "tokens": float(sum(len(tokenize(text)) for _path, text in items)),
            }
        artifact = model.to_dict()
    elif method == "centroid":
        examples: dict[str, list[tuple[str, str]]] = {}
        for split, items in texts.items():
            examples[split] = [
                (text, labels[path])
                for path, text in items
                if labels.get(path) is not None
            ]
        model = CentroidModel()
        model.fit(examples.get("train") or [])
        metrics = {}
        for split, items in examples.items():
            if not items:
                continue
            # NaN is recorded as a null, with the reason in the job's notes: a metric that was not
            # measurable is not a metric of zero.
            accuracy = model.accuracy(items)
            metrics[split] = {
                "accuracy": accuracy if accuracy == accuracy else None,
                "records": float(len(items)),
                "labels": float(len(model.labels)),
            }
        artifact = model.to_dict()
    else:
        raise ValidationError(f"{method!r} is not a trainer this build can run")
    return {"metrics": metrics, "artifact": artifact}
