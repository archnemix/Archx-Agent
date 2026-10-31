"""Remote bundle identity and shape validation, without executing training."""

from __future__ import annotations
import hashlib, json
from typing import Any
from archx_agent.managers.remote import PROTOCOL as PROTOCOL


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


class WorkerRefusal(Exception):
    """The bundle cannot be trained on, and the reason is the interesting part."""


class WorkerBusy(WorkerRefusal):
    """No job was accepted because the worker has no available capacity."""


def check_bundle(request: dict[str, Any]) -> dict[str, Any]:
    """Everything that must be true before a worker spends a cycle on a stranger's request."""
    if not isinstance(request, dict):
        raise WorkerRefusal("worker request must be an object")
    if request.get("protocol") != PROTOCOL:
        raise WorkerRefusal(
            f"this worker speaks {PROTOCOL!r}, the request speaks {request.get('protocol')!r}"
        )
    bundle = request.get("bundle")
    if not isinstance(bundle, dict):
        raise WorkerRefusal("the request carries no bundle")
    try:
        body = _canonical(bundle)
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise WorkerRefusal("bundle must contain serializable JSON text") from exc
    try:
        measured = _sha(body)
    except UnicodeError as exc:
        raise WorkerRefusal("bundle must contain valid UTF-8 text") from exc
    claimed = str(request.get("bundle_sha256") or "")
    if not claimed:
        raise WorkerRefusal(
            "the request names no bundle hash, so the input cannot be identified"
        )
    if measured != claimed:
        raise WorkerRefusal(
            f"the bundle hashes to {measured[:16]} here and to {claimed[:16]} at the requester: "
            "the input moved in transit, so no number from it would mean anything"
        )
    dataset = bundle.get("dataset")
    if (
        not isinstance(dataset, dict)
        or not isinstance(dataset.get("id"), str)
        or not dataset["id"]
    ):
        raise WorkerRefusal("bundle dataset must be an object with an id")
    if bundle.get("run") is not None and not isinstance(bundle["run"], dict):
        raise WorkerRefusal("bundle run must be an object")
    entries = dataset.get("entries")
    if not isinstance(entries, list) or not entries:
        raise WorkerRefusal("the bundle carries no records")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("path"), str)
            or not isinstance(entry.get("text"), str)
        ):
            raise WorkerRefusal("each bundle record needs a text path and text content")
        try:
            measured_text = _sha(entry["text"])
        except UnicodeError as exc:
            raise WorkerRefusal("record content must be valid UTF-8 text") from exc
        if measured_text != entry.get("text_sha256"):
            raise WorkerRefusal(
                f"{entry.get('path')} does not hash to the text digest in the bundle: the corpus "
                "was edited in transit"
            )
    # The manifest is rebuilt from the *file* digests the dataset recorded, which is what it was
    # built from - not from the trimmed text this worker trains on.
    lines = sorted(
        f"{entry.get('split') or 'train'}\t{entry.get('file_sha256')}\t"
        f"{entry.get('file_bytes')}\t{entry.get('path')}"
        for entry in entries
    )
    if _sha("\n".join(lines)) != dataset.get("manifest_checksum"):
        raise WorkerRefusal(
            "the bundle's records do not rebuild the manifest checksum it claims: the request "
            "contradicts itself"
        )
    if not any((entry.get("split") or "train") == "train" for entry in entries):
        raise WorkerRefusal(
            "no record in the bundle is in the train split, so there is nothing to train"
        )
    return bundle
