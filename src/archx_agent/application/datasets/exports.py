"""Exports operations for dataset preparation."""

from __future__ import annotations

import json
from typing import Any

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.datasets import DatasetRecord
from archx_agent.application.datasets.hashing import _sha


class DatasetServiceExportsMixin:
    """Exports responsibility for DatasetService."""

    def manifest(self, wanted: str) -> dict[str, Any]:
        """The dataset's claim about itself: sorted lines, one per kept record."""
        dataset = self.get(wanted)
        records = self.manager.records(dataset.id, status="kept", limit=100_000)
        lines = sorted(
            f"{record.split or 'train'}\t{record.sha256}\t{record.bytes}\t{record.path}"
            for record in records
        )
        body = "\n".join(lines)
        return {
            "dataset_id": dataset.id,
            "name": dataset.name,
            "seed": dataset.seed,
            "license": dataset.license,
            "records": len(records),
            "by_split": self.manager.counts(dataset.id)["by_split"],
            "checksum": _sha(body),
            "lines": lines,
        }

    def build(
        self, wanted: str, *, force: bool = False, task_id: str | None = None
    ) -> dict[str, Any]:
        """Write the JSONL export through `fs.write`, and record the manifest hash.

        The export goes through the tool layer like every other write in this build: a dataset that
        could appear in a directory `fs.write` is not allowed to touch would be a hole in the
        sandbox, whatever the intent.
        """
        dataset = self.get(wanted)
        counts = self.manager.counts(dataset.id)
        if not counts["kept"]:
            raise ValidationError(
                "there is nothing to build: no record survived cleaning"
            )
        unsigned = [
            r
            for r in self.manager.records(dataset.id, status="kept", limit=100_000)
            if not r.split
        ]
        if unsigned and not force:
            raise ValidationError(
                f"{len(unsigned)} records have no split yet: run `dataset split` first, or pass "
                "--force to build a dataset whose split is not decided"
            )
        manifest = self.manifest(dataset.id)
        target = f"{dataset.name.replace('/', '_') or 'dataset'}.jsonl"
        lines = []
        for record in self.manager.records(dataset.id, status="kept", limit=100_000):
            read = self._execute(
                "fs.read",
                {"path": record.path},
                self._context(f"dataset export {record.path}", task_id),
            )
            text = dict(read.result or {})
            lines.append(
                json.dumps(
                    {
                        "id": record.id,
                        "path": record.path,
                        "sha256": record.sha256,
                        "split": record.split or "train",
                        "chars": record.chars,
                        "lines": record.lines,
                        "text": text.get("content"),
                    },
                    ensure_ascii=False,
                )
            )
        body = "\n".join(lines) + ("\n" if lines else "")
        written = self._execute(
            "fs.write",
            {"path": target, "content": body, "create_parents": True},
            self._context(f"dataset build {target}", task_id),
        )
        output = dict(written.result or {})
        local_copy = self._artifacts_dir() / f"{dataset.id}.jsonl"
        local_copy.write_text(body, encoding="utf-8")

        self.manager.update_state(
            dataset.id,
            status="built",
            record_count=counts["kept"],
            dropped_count=counts["dropped"],
            checksum=manifest["checksum"],
            path=output.get("path") or target,
            metadata={
                **dataset.metadata,
                "built_at": iso_now(),
                "manifest_lines": manifest["lines"],
                "manifest_checksum": manifest["checksum"],
                "export_checksum": _sha(body),
                "export_bytes": len(body.encode("utf-8")),
                "local_copy": str(local_copy),
            },
        )
        self.manager.record_transform(
            dataset.id,
            kind="build",
            config={"target": target, "force": bool(force)},
            records_in=counts["kept"],
            records_out=len(lines),
            report={
                "manifest_checksum": manifest["checksum"],
                "export_checksum": _sha(body),
            },
            output_path=output.get("path") or target,
            output_checksum=manifest["checksum"],
        )
        return self.view(dataset.id)

    def verify(self, wanted: str) -> dict[str, Any]:
        """Recompute the manifest from the files on disk and disagree if it moved.

        A dataset is a set of *files*, so the honest check is against the files: a hash stored in a
        row proves only what the row said when it was written. Each recorded path is re-measured,
        and the differences are named - missing, changed, or still there.
        """
        dataset = self.get(wanted)
        records = self.manager.records(dataset.id, status="kept", limit=100_000)
        differences: list[dict[str, Any]] = []
        fresh: list[tuple[str, DatasetRecord]] = []
        for record in records:
            try:
                run = self._execute(
                    "fs.probe",
                    {"path": record.path},
                    self._context(f"dataset verify {record.path}"),
                )
            except (PermissionDeniedError, ApprovalRequiredError) as exc:
                # A file this run was not allowed to read is *not* a file that changed. Saying so
                # keeps a permission problem from being reported as a corpus problem.
                differences.append(
                    {
                        "path": record.path,
                        "kind": "unreadable",
                        "detail": getattr(exc, "message", None) or str(exc),
                    }
                )
                continue
            except ToolError as exc:
                differences.append(
                    {"path": record.path, "kind": "missing", "detail": str(exc)}
                )
                continue
            measured = dict(run.result or {})
            if str(measured.get("sha256")) != record.sha256:
                differences.append(
                    {
                        "path": record.path,
                        "kind": "changed",
                        "recorded": record.sha256,
                        "found": measured.get("sha256"),
                    }
                )
                continue
            fresh.append((record.split or "train", record))

        lines = sorted(
            f"{split}\t{record.sha256}\t{record.bytes}\t{record.path}"
            for split, record in fresh
        )
        recomputed = _sha("\n".join(lines))
        stored = dataset.checksum or ""
        agrees = bool(stored) and recomputed == stored and not differences
        unreadable = [item for item in differences if item["kind"] == "unreadable"]
        if agrees:
            note = "the files on disk still produce the recorded manifest"
        elif not stored:
            note = "no manifest was recorded (run `dataset build`)"
        elif unreadable:
            note = (
                f"{len(unreadable)} of {len(records)} records could not be read, so this check "
                f"cannot pass yet: {unreadable[0]['detail']}"
            )
        else:
            note = f"the dataset no longer matches its manifest: {len(differences)} records differ"
        return {
            "dataset_id": dataset.id,
            "name": dataset.name,
            "status": dataset.status,
            "stored_checksum": stored or None,
            "recomputed_checksum": recomputed,
            "agrees": agrees,
            "checked": len(records),
            "intact": len(fresh),
            "differences": differences,
            "note": note,
        }
