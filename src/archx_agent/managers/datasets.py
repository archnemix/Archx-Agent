"""Rows for datasets: candidates kept, candidates dropped, and where each decision came from.

A dataset is the first artifact in this repository whose *content* is the product rather than a
description of one, so the tables are built around three claims that are easy to make and hard to
keep:

``datasets``
    One row per dataset, and the narrow table the v8 schema reserved (``name``, ``source``,
    ``revision``, ``license``, ``format``, ``record_count``, ``path``, ``checksum``) is adopted
    with ``ALTER TABLE`` rather than redefined, so a home that already has rows keeps them.
    ``checksum`` is the hash over the manifest's sorted lines - the dataset's claim about itself.

``dataset_records``
    One row per **candidate**, whether it survived cleaning or not. A record removed by a rule
    keeps ``status = 'dropped'`` and the reason, because a pipeline that deletes quietly cannot be
    audited, and "why is this file not in my dataset" is the first question anyone asks.

``dataset_transforms``
    One row per step that changed the set - clean, split, build - with what went in and what came
    out, so the pipeline is a ledger rather than a state you have to reconstruct.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

DATASET_TABLES = ("datasets", "dataset_records", "dataset_transforms")

#: The lifecycle, as a list so the CLI, the GUI and `stats` cannot disagree about the order.
DATASET_STATES = ("draft", "scanned", "cleaned", "split", "built")

RECORD_STATUSES = ("kept", "dropped")
SPLITS = ("train", "val", "test")


@dataclass
class DatasetRecord:
    id: str
    dataset_id: str
    seq: int
    path: str
    sha256: str
    bytes: int
    kind: str
    status: str
    created_at: str
    chars: int | None = None
    lines: int | None = None
    split: str | None = None
    reason: str | None = None
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def kept(self) -> bool:
        return self.status == "kept"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "seq": self.seq,
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "kind": self.kind,
            "chars": self.chars,
            "lines": self.lines,
            "split": self.split,
            "status": self.status,
            "reason": self.reason,
            "label": self.label,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class Dataset:
    id: str
    name: str
    source: str
    created_at: str
    status: str = "draft"
    revision: str | None = None
    license: str | None = None
    format: str = "jsonl"
    record_count: int | None = None
    dropped_count: int = 0
    path: str | None = None
    checksum: str | None = None
    seed: str = ""
    splits: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "status": self.status,
            "revision": self.revision,
            "license": self.license,
            "format": self.format,
            "record_count": self.record_count,
            "dropped_count": self.dropped_count,
            "path": self.path,
            "checksum": self.checksum,
            "seed": self.seed,
            "splits": dict(self.splits),
            "task_id": self.task_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at or self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class Transform:
    id: int
    dataset_id: str
    seq: int
    kind: str
    config: dict[str, Any]
    records_in: int | None
    records_out: int | None
    created_at: str
    report: dict[str, Any] = field(default_factory=dict)
    output_path: str | None = None
    input_checksum: str | None = None
    output_checksum: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "seq": self.seq,
            "kind": self.kind,
            "config": dict(self.config),
            "records_in": self.records_in,
            "records_out": self.records_out,
            "report": dict(self.report),
            "output_path": self.output_path,
            "input_checksum": self.input_checksum,
            "output_checksum": self.output_checksum,
            "created_at": self.created_at,
        }


def _loads(raw: Any, fallback: Any) -> Any:
    if raw in (None, ""):
        return fallback
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):  # pragma: no cover - a hand-edited row
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _dataset_from_row(row: Mapping[str, Any]) -> Dataset:
    return Dataset(
        id=row["id"],
        name=row["name"],
        source=row["source"],
        status=row.get("status") or "draft",
        revision=row["revision"],
        license=row["license"],
        format=row.get("format") or "jsonl",
        record_count=row["record_count"],
        dropped_count=int(row["dropped_count"] or 0),
        path=row["path"],
        checksum=row["checksum"],
        seed=row["seed"] or "",
        splits=_loads(row["splits"], {}),
        task_id=row["task_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        metadata=_loads(row["metadata"], {}),
    )


def _record_from_row(row: Mapping[str, Any]) -> DatasetRecord:
    return DatasetRecord(
        id=row["id"],
        dataset_id=row["dataset_id"],
        seq=int(row["seq"]),
        path=row["path"],
        sha256=row["sha256"],
        bytes=int(row["bytes"]),
        kind=row["kind"],
        status=row["status"],
        chars=row["chars"],
        lines=row["lines"],
        split=row["split"],
        reason=row["reason"],
        label=row["label"],
        created_at=row["created_at"],
        metadata=_loads(row["metadata"], {}),
    )


def _transform_from_row(row: Mapping[str, Any]) -> Transform:
    return Transform(
        id=int(row["id"]),
        dataset_id=row["dataset_id"],
        seq=int(row["seq"]),
        kind=row["kind"],
        config=_loads(row["config"], {}),
        records_in=row["records_in"],
        records_out=row["records_out"],
        report=_loads(row["report"], {}),
        output_path=row["output_path"],
        input_checksum=row["input_checksum"],
        output_checksum=row["output_checksum"],
        created_at=row["created_at"],
    )


class DatasetManager(BaseManager):
    """Rows for datasets, their candidate records and the ledger of steps that shaped them."""

    tables = DATASET_TABLES

    def register_handlers(self) -> None:
        self.coordinator.register("datasets.dataset", self._apply_dataset)
        self.coordinator.register("datasets.dataset_update", self._apply_dataset_update)
        self.coordinator.register("datasets.record", self._apply_record)
        self.coordinator.register("datasets.transform", self._apply_transform)
        self.coordinator.register("datasets.records_cleared", self._apply_clear)

    # -- write handlers ---------------------------------------------------
    def _apply_dataset(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        row = payload["dataset"]
        tx.execute(
            "INSERT INTO datasets(id, name, source, revision, license, format, record_count,"
            " path, checksum, status, seed, splits, dropped_count, task_id, created_at,"
            " updated_at, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["id"], row["name"], row["source"], row.get("revision"), row.get("license"),
                row.get("format") or "jsonl", row.get("record_count"), row.get("path"),
                row.get("checksum"), row.get("status") or "draft", row.get("seed") or "",
                json_text(row.get("splits") or {}), int(row.get("dropped_count") or 0),
                row.get("task_id"), row["created_at"], row.get("updated_at") or row["created_at"],
                json_text(row.get("metadata") or {}),
            ),
        )
        return {"id": row["id"]}

    def _apply_dataset_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        row = payload["dataset"]
        tx.execute(
            "UPDATE datasets SET status = ?, record_count = ?, dropped_count = ?, checksum = ?,"
            " path = ?, seed = ?, splits = ?, metadata = ?, revision = ?, updated_at = ?"
            " WHERE id = ?",
            (
                row["status"], row.get("record_count"), int(row.get("dropped_count") or 0),
                row.get("checksum"), row.get("path"), row.get("seed") or "",
                json_text(row.get("splits") or {}), json_text(row.get("metadata") or {}),
                row.get("revision"), row["updated_at"], row["id"],
            ),
        )
        return {"id": row["id"]}

    def _apply_record(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        record = payload["record"]
        tx.execute(
            "INSERT INTO dataset_records(id, dataset_id, seq, path, sha256, bytes, kind, chars,"
            " lines, split, status, reason, label, created_at, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record["id"], record["dataset_id"], int(record["seq"]), record["path"],
                record["sha256"], int(record["bytes"]), record["kind"], record.get("chars"),
                record.get("lines"), record.get("split"), record["status"],
                record.get("reason"), record.get("label"), record["created_at"],
                json_text(record.get("metadata") or {}),
            ),
        )
        return {"id": record["id"]}

    def _apply_transform(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        step = payload["transform"]
        rowid = tx.execute(
            "INSERT INTO dataset_transforms(dataset_id, seq, kind, config, records_in,"
            " records_out, created_at, output_path, report, input_checksum, output_checksum)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                step["dataset_id"], int(step["seq"]), step["kind"], json_text(step.get("config") or {}),
                step.get("records_in"), step.get("records_out"), step["created_at"],
                step.get("output_path"), json_text(step.get("report") or {}),
                step.get("input_checksum"), step.get("output_checksum"),
            ),
        )
        return {"id": rowid}

    def _apply_clear(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        """A rescan replaces the candidate set. The *previous* set is what the ledger reports."""
        dataset_id = payload["dataset_id"]
        removed = tx.execute("DELETE FROM dataset_records WHERE dataset_id = ?", (dataset_id,))
        return {"removed": int(removed or 0)}

    # -- datasets ---------------------------------------------------------
    def create(
        self,
        *,
        name: str,
        sources: list[str],
        license: str | None = None,
        format: str = "jsonl",
        revision: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Dataset:
        if not name.strip():
            raise ValidationError("a dataset needs a name")
        if not sources:
            raise ValidationError("a dataset needs at least one source path")
        dataset = Dataset(
            id=new_id("ds_"),
            name=name.strip(),
            source=json.dumps(list(sources)),
            license=(license or "unknown"),
            format=format,
            revision=revision,
            status="draft",
            task_id=task_id,
            created_at=iso_now(),
            metadata=dict(metadata or {}),
        )
        dataset.metadata.setdefault("sources", list(sources))
        self._write("datasets.dataset", {"dataset": dataset.to_dict()})
        self.trace(
            "datasets", "dataset.created", status="ok", task_id=task_id,
            payload={"dataset_id": dataset.id, "name": dataset.name, "sources": sources},
        )
        return dataset

    def get(self, dataset_id: str) -> Dataset:
        row = self.store.query_one("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        if row is None:
            raise NotFoundError(f"no such dataset: {dataset_id}")
        return _dataset_from_row(row)

    def by_name(self, name: str) -> Dataset | None:
        row = self.store.query_one(
            "SELECT * FROM datasets WHERE name = ? ORDER BY created_at DESC LIMIT 1", (name,)
        )
        return _dataset_from_row(row) if row else None

    def resolve(self, wanted: str) -> Dataset:
        """An id or a name - because a person types the name and a script holds the id."""
        row = self.store.query_one(
            "SELECT * FROM datasets WHERE id = ? OR name = ? ORDER BY created_at DESC LIMIT 1",
            (wanted, wanted),
        )
        if row is None:
            raise NotFoundError(f"no such dataset: {wanted}")
        return _dataset_from_row(row)

    def datasets(self, *, limit: int = 50) -> list[Dataset]:
        rows = self.store.query(
            "SELECT * FROM datasets ORDER BY created_at DESC, rowid DESC LIMIT ?", (int(limit),)
        )
        return [_dataset_from_row(row) for row in rows]

    def update_state(
        self,
        dataset_id: str,
        *,
        status: str,
        record_count: int | None = None,
        dropped_count: int | None = None,
        checksum: str | None = None,
        path: str | None = None,
        seed: str | None = None,
        splits: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        revision: str | None = None,
    ) -> Dataset:
        current = self.get(dataset_id)
        row = {
            "id": dataset_id,
            "status": status,
            "record_count": current.record_count if record_count is None else int(record_count),
            "dropped_count": current.dropped_count if dropped_count is None else int(dropped_count),
            "checksum": current.checksum if checksum is None else checksum,
            "path": current.path if path is None else path,
            "seed": current.seed if seed is None else seed,
            "splits": current.splits if splits is None else dict(splits),
            "metadata": current.metadata if metadata is None else dict(metadata),
            "revision": current.revision if revision is None else revision,
            "updated_at": iso_now(),
        }
        self._write("datasets.dataset_update", {"dataset": row})
        return self.get(dataset_id)

    # -- records ----------------------------------------------------------
    def replace_records(self, dataset_id: str, records: list[dict[str, Any]]) -> int:
        """Swap the candidate set in one go: one transaction, so a crash cannot half-replace it."""
        self._write("datasets.records_cleared", {"dataset_id": dataset_id})
        for record in records:
            self._write("datasets.record", {"record": record})
        return len(records)

    def records(
        self,
        dataset_id: str,
        *,
        status: str | None = None,
        split: str | None = None,
        limit: int = 1000,
    ) -> list[DatasetRecord]:
        sql = "SELECT * FROM dataset_records WHERE dataset_id = ?"
        params: list[Any] = [dataset_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        if split:
            sql += " AND split = ?"
            params.append(split)
        sql += " ORDER BY seq LIMIT ?"
        params.append(int(limit))
        return [_record_from_row(row) for row in self.store.query(sql, params)]

    def record(self, record_id: str) -> DatasetRecord:
        row = self.store.query_one("SELECT * FROM dataset_records WHERE id = ?", (record_id,))
        if row is None:
            raise NotFoundError(f"no such dataset record: {record_id}")
        return _record_from_row(row)

    def record_by_sha(self, dataset_id: str, sha256: str) -> list[DatasetRecord]:
        rows = self.store.query(
            "SELECT * FROM dataset_records WHERE dataset_id = ? AND sha256 = ? ORDER BY seq",
            (dataset_id, sha256),
        )
        return [_record_from_row(row) for row in rows]

    def counts(self, dataset_id: str) -> dict[str, Any]:
        kept = int(
            self.store.scalar(
                "SELECT COUNT(*) FROM dataset_records WHERE dataset_id = ? AND status = 'kept'",
                (dataset_id,),
            )
            or 0
        )
        dropped = int(
            self.store.scalar(
                "SELECT COUNT(*) FROM dataset_records WHERE dataset_id = ? AND status = 'dropped'",
                (dataset_id,),
            )
            or 0
        )
        by_split: dict[str, int] = {}
        for row in self.store.query(
            "SELECT split, COUNT(*) AS n FROM dataset_records"
            " WHERE dataset_id = ? AND status = 'kept' AND split IS NOT NULL GROUP BY split",
            (dataset_id,),
        ):
            by_split[str(row["split"])] = int(row["n"])
        return {"kept": kept, "dropped": dropped, "by_split": by_split}

    # -- transforms -------------------------------------------------------
    def next_seq(self, dataset_id: str) -> int:
        current = self.store.scalar(
            "SELECT MAX(seq) FROM dataset_transforms WHERE dataset_id = ?", (dataset_id,)
        )
        return int(current or 0) + 1

    def record_transform(
        self,
        dataset_id: str,
        *,
        kind: str,
        config: dict[str, Any],
        records_in: int | None,
        records_out: int | None,
        report: dict[str, Any] | None = None,
        output_path: str | None = None,
        input_checksum: str | None = None,
        output_checksum: str | None = None,
    ) -> Transform:
        step = {
            "dataset_id": dataset_id,
            "seq": self.next_seq(dataset_id),
            "kind": kind,
            "config": config,
            "records_in": records_in,
            "records_out": records_out,
            "report": report or {},
            "output_path": output_path,
            "input_checksum": input_checksum,
            "output_checksum": output_checksum,
            "created_at": iso_now(),
        }
        step_id = self._write("datasets.transform", {"transform": step})
        self.trace(
            "datasets", f"dataset.{kind}", status="ok",
            payload={"dataset_id": dataset_id, "records_in": records_in, "records_out": records_out},
        )
        for saved in self.transforms(dataset_id):
            if saved.id == int(step_id.get("id") if isinstance(step_id, dict) else step_id):
                return saved
        raise NotFoundError(f"the {kind} step was not written")  # pragma: no cover

    def transforms(self, dataset_id: str) -> list[Transform]:
        rows = self.store.query(
            "SELECT * FROM dataset_transforms WHERE dataset_id = ? ORDER BY seq", (dataset_id,)
        )
        return [_transform_from_row(row) for row in rows]

    # -- overview ---------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        datasets = int(self.store.scalar("SELECT COUNT(*) FROM datasets") or 0)
        records = int(self.store.scalar("SELECT COUNT(*) FROM dataset_records") or 0)
        kept = int(
            self.store.scalar("SELECT COUNT(*) FROM dataset_records WHERE status = 'kept'") or 0
        )
        bytes_kept = int(
            self.store.scalar(
                "SELECT COALESCE(SUM(bytes), 0) FROM dataset_records WHERE status = 'kept'"
            )
            or 0
        )
        by_status: dict[str, int] = {}
        for row in self.store.query(
            "SELECT status, COUNT(*) AS n FROM datasets GROUP BY status"
        ):
            by_status[str(row["status"])] = int(row["n"])
        return {
            "datasets": datasets,
            "records": records,
            "kept": kept,
            "dropped": records - kept,
            "bytes_kept": bytes_kept,
            "by_status": by_status,
            "states": list(DATASET_STATES),
            "splits": list(SPLITS),
        }
