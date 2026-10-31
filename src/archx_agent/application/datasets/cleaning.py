"""Cleaning operations for dataset preparation."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.datasets import DatasetRecord
from archx_agent.application.datasets.constants import RULES


class DatasetServiceCleaningMixin:
    """Cleaning responsibility for DatasetService."""

    def clean(
        self,
        wanted: str,
        *,
        min_chars: int = 0,
        dedupe: bool = True,
        normalize: bool = False,
        drop_empty: bool = True,
        strip: bool = True,
        require_license: bool = False,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply the declared rules, and keep the reason on every row a rule removes.

        The rules are *declared in the transform's config* as well as applied, so the ledger says
        what was asked for and the rows say what happened; running the same clean twice with the
        same rules produces the same set, which is the only way "cleaned" means anything.
        """
        dataset = self.get(wanted)
        records = self.manager.records(dataset.id, limit=100_000)
        if not records:
            raise ValidationError("scan the dataset before cleaning it")

        config = {
            "min_chars": int(min_chars),
            "dedupe": bool(dedupe),
            "normalize": bool(normalize),
            "drop_empty": bool(drop_empty),
            "strip": bool(strip),
            "require_license": bool(require_license),
        }
        counts = {
            key: 0
            for key in ("drop_empty", "drop_binary", "min_chars", "dedupe", "license")
        }
        seen: dict[str, str] = {}
        updated: list[dict[str, Any]] = []

        if require_license and (dataset.license or "unknown") == "unknown":
            raise ValidationError(
                "require_license was asked for, but this dataset's license is unknown: "
                "record one with `dataset create --license …` rather than guessing"
            )

        for record in records:
            status, reason = record.status, record.reason
            if record.kind == "binary":
                status, reason = "dropped", RULES["drop_binary"]
                counts["drop_binary"] += 1
            elif drop_empty and (record.chars or 0) == 0:
                status, reason = "dropped", RULES["drop_empty"]
                counts["drop_empty"] += 1
            elif min_chars and (record.chars or 0) < int(min_chars):
                status, reason = (
                    "dropped",
                    (f"{RULES['min_chars']} ({record.chars or 0} < {int(min_chars)})"),
                )
                counts["min_chars"] += 1
            elif dedupe and self._dedupe_key(record, normalize) in seen:
                key = self._dedupe_key(record, normalize)
                status, reason = "dropped", f"{RULES['dedupe']}: {seen[key]}"
                counts["dedupe"] += 1
            else:
                status, reason = "kept", None
                if record.kind == "text":
                    seen.setdefault(self._dedupe_key(record, normalize), record.path)
            metadata = dict(record.metadata)
            if strip:
                metadata["stripped"] = True
            updated.append(
                {
                    **record.to_dict(),
                    "status": status,
                    "reason": reason,
                    "metadata": metadata,
                }
            )

        self.manager.replace_records(dataset.id, updated)
        kept = sum(1 for row in updated if row["status"] == "kept")
        self.manager.update_state(
            dataset.id,
            status="cleaned",
            record_count=kept,
            dropped_count=len(updated) - kept,
            metadata={**dataset.metadata, "cleaned_at": iso_now(), "rules": config},
        )
        self.manager.record_transform(
            dataset.id,
            kind="clean",
            config=config,
            records_in=len(records),
            records_out=kept,
            report={
                "rules": config,
                "removed": counts,
                "kept": kept,
                "dropped": len(updated) - kept,
            },
        )
        return self.view(dataset.id)

    @staticmethod
    def _dedupe_key(record: DatasetRecord, normalize: bool) -> str:
        """Exact bytes by default; the normalised text when `normalize` was asked for."""
        if normalize:
            return str(record.metadata.get("norm_sha") or record.sha256)
        return record.sha256
