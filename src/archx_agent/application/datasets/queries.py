"""Read and search operations for dataset preparation."""

from __future__ import annotations

from typing import Any

from archx_agent.managers.datasets import Dataset
from archx_agent.application.datasets.constants import TEXT_SUFFIXES, RULES


class DatasetServiceQueriesMixin:
    """Queries responsibility for DatasetService."""

    def get(self, wanted: str) -> Dataset:
        return self.manager.resolve(wanted)

    def view(self, wanted: str) -> dict[str, Any]:
        dataset = self.get(wanted)
        payload = dataset.to_dict()
        payload["counts"] = self.manager.counts(dataset.id)
        payload["transforms"] = [
            step.to_dict() for step in self.manager.transforms(dataset.id)
        ]
        payload["sources"] = list(dataset.metadata.get("sources") or [])
        payload["license_note"] = (
            "unknown - nothing here infers permission from a path"
            if (dataset.license or "unknown") == "unknown"
            else f"declared by the user: {dataset.license}"
        )
        return payload

    def records(
        self,
        wanted: str,
        *,
        status: str | None = None,
        split: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        dataset = self.get(wanted)
        return [
            record.to_dict()
            for record in self.manager.records(
                dataset.id, status=status, split=split, limit=limit
            )
        ]

    def explain(self, record_id: str) -> dict[str, Any]:
        """Why this file is in the dataset, or why it is not - the first question anyone asks."""
        record = self.manager.record(record_id)
        dataset = self.get(record.dataset_id)
        steps = [step.to_dict() for step in self.manager.transforms(dataset.id)]
        return {
            "record": record.to_dict(),
            "dataset": dataset.name,
            "status": record.status,
            "reason": record.reason,
            "sentence": (
                f"{record.path} is in the {record.split or 'unsplit'} split of {dataset.name!r}"
                if record.status == "kept"
                else f"{record.path} was dropped: {record.reason}"
            ),
            "steps": [
                {
                    "seq": step["seq"],
                    "kind": step["kind"],
                    "records_out": step["records_out"],
                }
                for step in steps
            ],
        }

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [dataset.to_dict() for dataset in self.manager.datasets(limit=limit)]

    def steps(self, wanted: str) -> list[dict[str, Any]]:
        dataset = self.get(wanted)
        return [step.to_dict() for step in self.manager.transforms(dataset.id)]

    def stats(self) -> dict[str, Any]:
        base = self.manager.stats()
        base["text_suffixes"] = list(TEXT_SUFFIXES)
        base["rules"] = sorted(RULES)
        return base
