"""Dataset preparation: candidates, cleaning with reasons, stable splits, and a manifest you can check.

Three properties are what make a prepared corpus worth trusting, and each of them is easy to lose
in a pipeline that only *looks* tidy:

**A dataset is its manifest.** :meth:`DatasetService.build` writes a JSONL export and a manifest, and
records a sha256 over the manifest's sorted lines. :meth:`DatasetService.verify` recomputes that
hash from the files on disk and **disagrees out loud** when it does not match - the same instinct as
M33's simulation replay, because a corpus whose contents drifted quietly is worse than no corpus.

**Nothing is dropped silently.** Every candidate is a row, whether it survived cleaning or not, and
a dropped row keeps the rule that dropped it and the reason. Deduplication keeps the first copy by
path and marks the rest, so "two copies of the same document" is visible instead of invisible.

**A split is a function of the record, not of its position.** Records are assigned by hashing
``seed`` together with the record's own sha256, so adding a file tomorrow does not move the files
that are already in ``train``. A positional shuffle would look just as good in a demonstration and
would silently invalidate every model trained on yesterday's split. Identical content is refused
across splits - a leak is a data bug that flatters the evaluation, so it is a refusal with the
pairs named rather than a warning nobody reads.

The fourth property is smaller but decides how the rest is used: **the license is recorded per
source, and "unknown" is written as unknown**. Nothing here infers permission from a directory name.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.datasets import Dataset, DatasetRecord, Transform
from archx_agent.managers.tools import ToolContext

#: Text extensions this build will *treat as text*. Everything else is measured and shelved, not
#: silently skipped: a dataset of binaries needs a different pipeline, and saying so beats dropping
#: the file into a limbo where nobody can see it.
TEXT_SUFFIXES = (
    ".txt", ".md", ".markdown", ".rst", ".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".sql",
    ".sh", ".c", ".h", ".cc", ".cpp", ".go", ".rs", ".java", ".rb", ".php", ".log", ".tex",
)

#: The cleaning rules, with the phrase each one stamps on the record it removes. The reason text is
#: deliberately a sentence a person can read in `dataset records --status dropped`.
RULES = {
    "drop_empty": "the file is empty",
    "drop_binary": "not a text file this build can parse",
    "min_chars": "fewer characters than the min_chars rule allows",
    "dedupe": "the same content is already in the dataset from an earlier path",
    "strip": "leading and trailing whitespace was trimmed",
    "require_license": "the dataset's license is unknown, so nothing may be published from it",
}

LEAK_TEXT = "the same text (ignoring whitespace and case) appears in two splits"


def _norm_sha(content: str) -> str:
    """A hash of the text with runs of whitespace collapsed and case folded.

    Two files that differ only in how they were saved are the same document for the purposes of a
    train/test split, and treating them as different is how a corpus leaks into its own evaluation.
    """
    return _sha(" ".join(content.split()).lower())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DatasetService:
    """Build a dataset out of files in the tool roots, and keep every decision visible."""

    def __init__(self, ws) -> None:
        self.ws = ws

    # -- plumbing ---------------------------------------------------------
    @property
    def manager(self):
        return self.ws.datasets

    def _execute(self, name: str, arguments: dict[str, Any], context: ToolContext):
        run = self.ws.tools.execute(name, arguments, context=context, requester="datasets")
        if run.status == "denied":
            approval = getattr(run, "approval_id", None)
            if approval:
                raise ApprovalRequiredError(
                    f"{name} needs approval: approve {approval} or grant the capability",
                    approval_id=approval,
                )
            raise PermissionDeniedError(run.error or f"{name} was refused")
        if run.status == "failed":
            raise ToolError(run.error or f"{name} failed")
        return run

    def _context(self, purpose: str, task_id: str | None = None) -> ToolContext:
        return ToolContext(task_id=task_id, purpose=purpose)

    def _artifacts_dir(self) -> Path:
        base = Path(self.ws.config.path("paths.artifacts")) / "datasets"
        base.mkdir(parents=True, exist_ok=True)
        return base

    # -- create / resolve -------------------------------------------------
    def create(
        self,
        name: str,
        sources: list[str],
        *,
        license: str | None = None,
        notes: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        dataset = self.manager.create(
            name=name,
            sources=[str(s) for s in sources],
            license=(license or "unknown"),
            task_id=task_id,
            metadata={"notes": notes} if notes else {},
        )
        return self.view(dataset.id)

    def get(self, wanted: str) -> Dataset:
        return self.manager.resolve(wanted)

    # -- scanning ---------------------------------------------------------
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
                "fs.list", {"path": source, "limit": limit},
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
                    self._walk(child, depth=depth + 1, max_depth=max_depth, limit=limit,
                               task_id=task_id)
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
            metadata={**dataset.metadata, "scanned_at": iso_now(), "source_count": len(sources)},
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
            "fs.probe", {"path": path},
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
            "metadata": {"sha256_scope": measured.get("sha256_scope", "whole file"),
                         "suffix": suffix},
        }
        if suffix not in TEXT_SUFFIXES:
            return {**base, "kind": "binary", "status": "dropped", "reason": RULES["drop_binary"]}
        try:
            read = self._execute(
                "fs.read", {"path": path},
                self._context(f"dataset read {path}", task_id),
            )
        except ToolError as exc:
            # A file with a text suffix that `fs.read` refuses is binary in fact, whatever it is
            # named - the same lesson as M34's mislabelled media, applied to a corpus.
            return {**base, "kind": "binary", "status": "dropped",
                    "reason": f"{RULES['drop_binary']}: {exc}"}
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

    # -- cleaning ---------------------------------------------------------
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
        counts = {key: 0 for key in ("drop_empty", "drop_binary", "min_chars", "dedupe", "license")}
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
                status, reason = "dropped", (
                    f"{RULES['min_chars']} ({record.chars or 0} < {int(min_chars)})"
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
                {**record.to_dict(), "status": status, "reason": reason, "metadata": metadata}
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
            report={"rules": config, "removed": counts, "kept": kept,
                    "dropped": len(updated) - kept},
        )
        return self.view(dataset.id)

    @staticmethod
    def _dedupe_key(record: DatasetRecord, normalize: bool) -> str:
        """Exact bytes by default; the normalised text when `normalize` was asked for."""
        if normalize:
            return str(record.metadata.get("norm_sha") or record.sha256)
        return record.sha256

    # -- splitting --------------------------------------------------------
    @staticmethod
    def _bucket(dataset: Dataset, record: DatasetRecord) -> str:
        """The split a record belongs to, as a function of the seed and the record's own hash.

        Positional shuffling is the usual shortcut and it silently moves every record whenever the
        corpus changes; hashing keeps yesterday's assignment today, which is what makes a published
        split reproducible and a comparison between two runs meaningful.
        """
        ratios = dataset.splits.get("ratios") or {"train": 0.8, "val": 0.1, "test": 0.1}
        digest = hashlib.sha256(f"{dataset.seed}:{record.sha256}".encode("utf-8")).hexdigest()
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
            raise ValidationError("nothing survived cleaning, so there is nothing to split")

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
            splits={"ratios": {"train": train, "val": val, "test": test},
                    "by_split": counts["by_split"]},
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
                leaks.append({
                    "sha256": sha,
                    "splits": names,
                    "paths": [by_split[name].path for name in names],
                })
        return leaks

    # -- manifest and export ---------------------------------------------
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

    def build(self, wanted: str, *, force: bool = False, task_id: str | None = None) -> dict[str, Any]:
        """Write the JSONL export through `fs.write`, and record the manifest hash.

        The export goes through the tool layer like every other write in this build: a dataset that
        could appear in a directory `fs.write` is not allowed to touch would be a hole in the
        sandbox, whatever the intent.
        """
        dataset = self.get(wanted)
        counts = self.manager.counts(dataset.id)
        if not counts["kept"]:
            raise ValidationError("there is nothing to build: no record survived cleaning")
        unsigned = [r for r in self.manager.records(dataset.id, status="kept", limit=100_000)
                    if not r.split]
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
                "fs.read", {"path": record.path},
                self._context(f"dataset export {record.path}", task_id),
            )
            text = dict(read.result or {})
            lines.append(json.dumps({
                "id": record.id,
                "path": record.path,
                "sha256": record.sha256,
                "split": record.split or "train",
                "chars": record.chars,
                "lines": record.lines,
                "text": text.get("content"),
            }, ensure_ascii=False))
        body = "\n".join(lines) + ("\n" if lines else "")
        written = self._execute(
            "fs.write", {"path": target, "content": body, "create_parents": True},
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
            report={"manifest_checksum": manifest["checksum"], "export_checksum": _sha(body)},
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
                    "fs.probe", {"path": record.path},
                    self._context(f"dataset verify {record.path}"),
                )
            except (ToolError, PermissionDeniedError, ApprovalRequiredError) as exc:
                differences.append(
                    {"path": record.path, "kind": "missing", "detail": str(exc)}
                )
                continue
            measured = dict(run.result or {})
            if str(measured.get("sha256")) != record.sha256:
                differences.append({
                    "path": record.path,
                    "kind": "changed",
                    "recorded": record.sha256,
                    "found": measured.get("sha256"),
                })
                continue
            fresh.append((record.split or "train", record))

        lines = sorted(
            f"{split}\t{record.sha256}\t{record.bytes}\t{record.path}"
            for split, record in fresh
        )
        recomputed = _sha("\n".join(lines))
        stored = dataset.checksum or ""
        agrees = bool(stored) and recomputed == stored and not differences
        note = (
            "the files on disk still produce the recorded manifest"
            if agrees
            else "the dataset no longer matches its manifest: "
            + ("no manifest was recorded (run `dataset build`)" if not stored else
               f"{len(differences)} records differ")
        )
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

    # -- reading ----------------------------------------------------------
    def view(self, wanted: str) -> dict[str, Any]:
        dataset = self.get(wanted)
        payload = dataset.to_dict()
        payload["counts"] = self.manager.counts(dataset.id)
        payload["transforms"] = [step.to_dict() for step in self.manager.transforms(dataset.id)]
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
                {"seq": step["seq"], "kind": step["kind"], "records_out": step["records_out"]}
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
