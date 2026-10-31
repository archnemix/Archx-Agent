"""Scanning operations for dataset preparation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ToolError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.datasets import Dataset
from archx_agent.application.datasets.constants import TEXT_SUFFIXES, RULES
from archx_agent.application.datasets.hashing import _norm_sha


class DatasetServiceScanningMixin:
    """Scanning responsibility for DatasetService."""

    def _walk(
        self,
        source: str,
        *,
        depth: int = 0,
        max_depth: int = 4,
        limit: int = 500,
        task_id: str | None = None,
    ) -> list[str]:
        """Every file under a source path, one `fs.list` per directory.

        Recursion happens here rather than in the tool because each level is a separate permission
        check: a sandbox that is walked by one tool call is a sandbox with one entry point, and this
        build prefers the version where an operator can see every directory that was read.
        """
        found: list[str] = []
        try:
            run = self._execute(
                "fs.list",
                {"path": source, "limit": limit},
                self._context(f"dataset scan {source}", task_id),
            )
        except ToolError as exc:
            # A source that is a file rather than a directory is not an error - it is a corpus of
            # one. Anything else is reported against the source and the scan continues.
            if "not a directory" in str(exc) or "is a directory" not in str(exc):
                return [source]
            raise
        payload = dict(run.result or {})
        if payload.get("truncated"):
            raise ValidationError(
                f"{source} has more entries than one listing returns; split the source or raise the "
                "limit, because a silently truncated scan is a dataset with holes in it"
            )
        for entry in payload.get("entries") or []:
            name = str(entry.get("name") or "")
            kind = str(entry.get("kind") or "file")
            child = f"{source.rstrip('/')}/{name}" if source not in ("", ".") else name
            if kind == "dir":
                if depth >= max_depth:
                    raise ValidationError(
                        f"{child} is deeper than {max_depth} levels; the scan stops rather than "
                        "descending without a bound"
                    )
                found.extend(
                    self._walk(
                        child,
                        depth=depth + 1,
                        max_depth=max_depth,
                        limit=limit,
                        task_id=task_id,
                    )
                )
            elif kind == "file":
                found.append(child)
        return found

    def scan(self, wanted: str, *, task_id: str | None = None) -> dict[str, Any]:
        """Measure every candidate and write one row per candidate - including the ones dropped."""
        dataset = self.get(wanted)
        sources = list(dataset.metadata.get("sources") or [])
        if not sources:
            raise ValidationError("this dataset has no source paths recorded")

        paths: list[str] = []
        for source in sources:
            for path in self._walk(str(source), task_id=task_id):
                if path not in paths:
                    paths.append(path)
        if not paths:
            raise ValidationError(f"no files were found under {', '.join(sources)}")

        previous = len(self.manager.records(dataset.id, limit=100_000))
        records: list[dict[str, Any]] = []
        for seq, path in enumerate(sorted(paths)):
            records.append(self._measure(dataset, seq, path, task_id=task_id))

        self.manager.replace_records(dataset.id, records)
        kept = [r for r in records if r["status"] == "kept"]
        count = self.manager.counts(dataset.id)
        self.manager.update_state(
            dataset.id,
            status="scanned",
            record_count=count["kept"],
            dropped_count=count["dropped"],
            metadata={
                **dataset.metadata,
                "scanned_at": iso_now(),
                "source_count": len(sources),
            },
        )
        self.manager.record_transform(
            dataset.id,
            kind="scan",
            config={"sources": sources},
            records_in=previous,
            records_out=len(records),
            report={
                "paths": len(paths),
                "kept": len(kept),
                "dropped": len(records) - len(kept),
                "sources": len(sources),
            },
        )
        return self.view(dataset.id)

    def _measure(
        self, dataset: Dataset, seq: int, path: str, *, task_id: str | None = None
    ) -> dict[str, Any]:
        probe = self._execute(
            "fs.probe",
            {"path": path},
            self._context(f"dataset measure {path}", task_id),
        )
        measured = dict(probe.result or {})
        sha = str(measured["sha256"])
        size = int(measured["bytes"])
        suffix = Path(path).suffix.lower()
        base = {
            "id": new_id("dr_"),
            "dataset_id": dataset.id,
            "seq": seq,
            "path": measured.get("path") or path,
            "sha256": sha,
            "bytes": size,
            "created_at": iso_now(),
            "split": None,
            "label": None,
            "chars": None,
            "lines": None,
            "metadata": {
                "sha256_scope": measured.get("sha256_scope", "whole file"),
                "suffix": suffix,
            },
        }
        if suffix not in TEXT_SUFFIXES:
            return {
                **base,
                "kind": "binary",
                "status": "dropped",
                "reason": RULES["drop_binary"],
            }
        try:
            read = self._execute(
                "fs.read",
                {"path": path},
                self._context(f"dataset read {path}", task_id),
            )
        except ToolError as exc:
            # A file with a text suffix that `fs.read` refuses is binary in fact, whatever it is
            # named - the same lesson as M34's mislabelled media, applied to a corpus.
            return {
                **base,
                "kind": "binary",
                "status": "dropped",
                "reason": f"{RULES['drop_binary']}: {exc}",
            }
        text = dict(read.result or {})
        content = str(text.get("content") or "")
        metadata = dict(base["metadata"])
        metadata["truncated"] = bool(text.get("truncated"))
        # The exact hash cannot find a document that was re-saved with different whitespace or
        # case, and that is exactly the pair that leaks between splits. One more hash, of the
        # normalised text, makes the near-duplicate visible.
        metadata["norm_sha"] = _norm_sha(content)
        return {
            **base,
            "kind": "text",
            "chars": len(content),
            "lines": int(text.get("total_lines") or 0),
            "status": "kept" if content.strip() else "dropped",
            "reason": None if content.strip() else RULES["drop_empty"],
            "metadata": metadata,
        }
