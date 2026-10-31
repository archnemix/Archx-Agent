"""Splitting operations for dataset preparation."""

from __future__ import annotations

import hashlib
from typing import Any

from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.datasets import Dataset, DatasetRecord
from archx_agent.application.datasets.constants import LEAK_TEXT


class DatasetServiceSplittingMixin:
    """Splitting responsibility for DatasetService."""

    @staticmethod
    def _bucket(dataset: Dataset, record: DatasetRecord) -> str:
        """The split a record belongs to, as a function of the seed and the record's own hash.

        Positional shuffling is the usual shortcut and it silently moves every record whenever the
        corpus changes; hashing keeps yesterday's assignment today, which is what makes a published
        split reproducible and a comparison between two runs meaningful.
        """
        ratios = dataset.splits.get("ratios") or {"train": 0.8, "val": 0.1, "test": 0.1}
        digest = hashlib.sha256(
            f"{dataset.seed}:{record.sha256}".encode("utf-8")
        ).hexdigest()
        point = int(digest[:8], 16) / 0xFFFFFFFF
        running = 0.0
        for name in ("train", "val", "test"):
            running += float(ratios.get(name, 0.0))
            if point <= running:
                return name
        return "test"

    def split(
        self,
        wanted: str,
        *,
        train: float = 0.8,
        val: float = 0.1,
        test: float = 0.1,
        seed: str = "0",
        task_id: str | None = None,
    ) -> dict[str, Any]:
        dataset = self.get(wanted)
        total = float(train) + float(val) + float(test)
        if abs(total - 1.0) > 1e-9:
            raise ValidationError(f"the ratios must add up to 1.0 (got {total:.3f})")
        if min(float(train), float(val), float(test)) < 0:
            raise ValidationError("a ratio cannot be negative")
        records = self.manager.records(dataset.id, status="kept", limit=100_000)
        if not records:
            raise ValidationError(
                "nothing survived cleaning, so there is nothing to split"
            )

        dataset.splits = {"ratios": {"train": train, "val": val, "test": test}}
        dataset.seed = str(seed)
        assigned: dict[str, str] = {}
        for record in records:
            assigned[record.id] = self._bucket(dataset, record)

        leaks = self._leaks(records, assigned)
        if leaks:
            pairs = "; ".join(
                f"{leak['sha256'][:12]} in {leak['splits'][0]} and {leak['splits'][1]} "
                f"({leak['paths'][0]}, {leak['paths'][1]})"
                for leak in leaks[:5]
            )
            raise ValidationError(
                f"{LEAK_TEXT}: {pairs}. One document must not be in two splits; "
                "run `dataset clean --dedupe --normalize` first, because a leak flatters every "
                "score that comes out of this dataset"
            )

        updated = []
        for record in self.manager.records(dataset.id, limit=100_000):
            row = record.to_dict()
            if record.id in assigned:
                row["split"] = assigned[record.id]
            updated.append(row)
        self.manager.replace_records(dataset.id, updated)

        counts = self.manager.counts(dataset.id)
        self.manager.update_state(
            dataset.id,
            status="split",
            record_count=counts["kept"],
            dropped_count=counts["dropped"],
            seed=str(seed),
            splits={
                "ratios": {"train": train, "val": val, "test": test},
                "by_split": counts["by_split"],
            },
            metadata={**dataset.metadata, "split_at": iso_now()},
        )
        self.manager.record_transform(
            dataset.id,
            kind="split",
            config={"train": train, "val": val, "test": test, "seed": str(seed)},
            records_in=len(records),
            records_out=counts["kept"],
            report={"by_split": counts["by_split"], "leaks": 0},
        )
        return self.view(dataset.id)

    def _leaks(
        self, records: list[DatasetRecord], assigned: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Group by the *normalised* hash: exact duplicates cannot leak under this split rule.

        The bucket is a function of the record's own sha256, so two byte-identical files always land
        in the same split - the exact-duplicate leak is impossible by construction rather than by
        check. What the rule cannot see is a document re-saved with different whitespace or case:
        different bytes, different hash, different bucket, same text. That is the leak this finds.
        """
        by_sha: dict[str, list[DatasetRecord]] = {}
        for record in records:
            key = str(record.metadata.get("norm_sha") or record.sha256)
            by_sha.setdefault(key, []).append(record)
        leaks: list[dict[str, Any]] = []
        for sha, group in sorted(by_sha.items()):
            by_split: dict[str, DatasetRecord] = {}
            for record in group:
                by_split.setdefault(assigned.get(record.id, "test"), record)
            if len(by_split) > 1:
                # Name the pair that actually crosses, not the first two records in the group: a
                # message that points at a file which is not the problem wastes the reader's time.
                names = sorted(by_split)
                leaks.append(
                    {
                        "sha256": sha,
                        "splits": names,
                        "paths": [by_split[name].path for name in names],
                    }
                )
        return leaks
