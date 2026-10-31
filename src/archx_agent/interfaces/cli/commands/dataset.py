"""Dataset command: argument registration and execution."""

from __future__ import annotations

import argparse


import json


from archx_agent.helpers.exceptions import (
    ArchxError,
    NotFoundError,
    ValidationError,
)


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_USAGE,
    EXIT_DEGRADED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    data = sub.add_parser(
        "dataset",
        help="Dataset preparation: candidates, cleaning with reasons, stable splits",
    )
    ds_sub = data.add_subparsers(dest="dataset_command", required=True)
    ds_new = ds_sub.add_parser(
        "create", help="a named corpus over one or more source paths"
    )
    ds_new.add_argument("name")
    ds_new.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="PATH",
        help="a file or directory inside the tool roots (repeatable)",
    )
    ds_new.add_argument(
        "--license", help="what you may do with it; unstated is recorded as unknown"
    )
    ds_new.add_argument("--notes")
    ds_scan = ds_sub.add_parser(
        "scan", help="measure every candidate and write a row per candidate"
    )
    ds_scan.add_argument("dataset")
    ds_clean = ds_sub.add_parser(
        "clean", help="apply the rules; every removal keeps its reason"
    )
    ds_clean.add_argument("dataset")
    ds_clean.add_argument("--min-chars", type=int, default=0)
    ds_clean.add_argument(
        "--no-dedupe",
        dest="dedupe",
        action="store_false",
        help="keep byte-identical copies",
    )
    ds_clean.add_argument(
        "--normalize",
        action="store_true",
        help="also collapse copies that differ only in whitespace or case",
    )
    ds_clean.add_argument("--keep-empty", dest="drop_empty", action="store_false")
    ds_clean.add_argument(
        "--require-license",
        action="store_true",
        help="refuse to clean a dataset whose license is unknown",
    )
    ds_split = ds_sub.add_parser(
        "split", help="assign each record to train/val/test (stable, seeded)"
    )
    ds_split.add_argument("dataset")
    ds_split.add_argument("--train", type=float, default=0.8)
    ds_split.add_argument("--val", type=float, default=0.1)
    ds_split.add_argument("--test", type=float, default=0.1)
    ds_split.add_argument("--seed", default="0")
    ds_build = ds_sub.add_parser(
        "build", help="write the JSONL export and record the manifest hash"
    )
    ds_build.add_argument("dataset")
    ds_build.add_argument(
        "--force",
        action="store_true",
        help="build even though some records have no split",
    )
    ds_verify = ds_sub.add_parser(
        "verify", help="recompute the manifest from disk and disagree if it moved"
    )
    ds_verify.add_argument("dataset")
    ds_show = ds_sub.add_parser("show", help="one dataset: counts, splits, ledger")
    ds_show.add_argument("dataset")
    ds_recs = ds_sub.add_parser("records", help="the candidates, kept and dropped")
    ds_recs.add_argument("dataset")
    ds_recs.add_argument("--status", choices=["kept", "dropped"])
    ds_recs.add_argument("--split", choices=["train", "val", "test"])
    ds_recs.add_argument("--limit", type=int, default=50)
    ds_expl = ds_sub.add_parser(
        "explain", help="why one file is in the dataset, or why it is not"
    )
    ds_expl.add_argument("record")
    ds_steps = ds_sub.add_parser(
        "steps", help="the ledger: what each step took in and gave back"
    )
    ds_steps.add_argument("dataset")
    ds_list = ds_sub.add_parser("list", help="datasets, newest first")
    ds_list.add_argument("--limit", type=int, default=20)
    ds_sub.add_parser("stats", help="dataset and record counts")


def cmd_dataset(args: argparse.Namespace) -> int:
    """`dataset ...` - prepare a corpus and keep every decision visible.

    Exit codes: 0 the step ran; 1 nothing matching that id or name; 2 the input made no sense (no
    sources, ratios that do not add up, cleaning before scanning) or a step was refused by the
    data itself - a leak across splits, a manifest that does not match the files. The refusal is
    exit 2, not a crash, because a corpus that cannot be split is a fact about the corpus.
    """
    command = args.dataset_command
    try:
        with _workspace(args) as ws:
            service = ws.data

            if command == "create":
                created = service.create(
                    args.name, list(args.source), license=args.license, notes=args.notes
                )
                if args.json:
                    emit_json(created)
                    return EXIT_OK
                emit(
                    f"created {created['id']}  {created['name']!r}  ({created['status']})"
                )
                emit(f"  sources   {', '.join(created['sources'])}")
                emit(f"  license   {created['license']}  ({created['license_note']})")
                emit(f"  next      archx-agent dataset scan {created['id']}")
                return EXIT_OK

            if command == "scan":
                scanned = service.scan(args.dataset)
                if args.json:
                    emit_json(scanned)
                    return EXIT_OK
                counts = scanned["counts"]
                emit(
                    f"scanned {scanned['id']}  {counts['kept']} kept, {counts['dropped']} dropped"
                )
                for record in (
                    scanned["records"]
                    if "records" in scanned
                    else service.records(scanned["id"], limit=50)
                ):
                    mark = "kept " if record["status"] == "kept" else "drop "
                    lines = record["lines"] or 0
                    detail = record["reason"] or (
                        f"{record['chars']} chars, {lines} line{'' if lines == 1 else 's'}"
                    )
                    emit(f"  {mark} {record['path']:<40} {detail}")
                emit(f"  next   archx-agent dataset clean {scanned['id']}")
                return EXIT_OK

            if command == "clean":
                cleaned = service.clean(
                    args.dataset,
                    min_chars=args.min_chars,
                    dedupe=args.dedupe,
                    normalize=args.normalize,
                    drop_empty=args.drop_empty,
                    require_license=args.require_license,
                )
                if args.json:
                    emit_json(cleaned)
                    return EXIT_OK
                step = [s for s in cleaned["transforms"] if s["kind"] == "clean"][-1]
                counts = cleaned["counts"]
                emit(
                    f"cleaned {cleaned['id']}  {step['records_in']} -> {step['records_out']} kept"
                )
                for rule, removed in sorted(step["report"]["removed"].items()):
                    if removed:
                        emit(f"  {rule:<10} removed {removed}")
                emit(
                    f"  dropped  {counts['dropped']} records - each one kept with its reason"
                )
                emit(f"  next     archx-agent dataset split {cleaned['id']} --seed 42")
                return EXIT_OK

            if command == "split":
                split = service.split(
                    args.dataset,
                    train=args.train,
                    val=args.val,
                    test=args.test,
                    seed=args.seed,
                )
                if args.json:
                    emit_json(split)
                    return EXIT_OK
                by_split = split["splits"]["by_split"]
                emit(f"split {split['id']}  seed {split['seed']!r}")
                for name in ("train", "val", "test"):
                    emit(f"  {name:<6} {by_split.get(name, 0)}")
                emit(
                    "  each record's split follows from its own hash, so adding a file "
                    "tomorrow does not move today's rows"
                )
                emit(f"  next   archx-agent dataset build {split['id']}")
                return EXIT_OK

            if command == "build":
                built = service.build(args.dataset, force=args.force)
                if args.json:
                    emit_json(built)
                    return EXIT_OK
                emit(
                    f"built {built['id']}  {built['path']}  ({built['counts']['kept']} records)"
                )
                emit(f"  manifest  {built['checksum']}")
                emit(
                    f"  export    {built['metadata']['export_bytes']} bytes, "
                    f"sha256 {built['metadata']['export_checksum'][:16]}..."
                )
                emit(f"  local     {built['metadata']['local_copy']}")
                emit(f"  next      archx-agent dataset verify {built['id']}")
                return EXIT_OK

            if command == "verify":
                result = service.verify(args.dataset)
                if args.json:
                    emit_json(result)
                    return EXIT_DEGRADED if not result["agrees"] else EXIT_OK
                emit(
                    f"verify {result['dataset_id']}  {result['checked']} records checked"
                )
                emit(
                    f"  stored     {result['stored_checksum'] or '(none - never built)'}"
                )
                emit(f"  recomputed {result['recomputed_checksum']}")
                emit(f"  {result['note']}")
                for difference in result["differences"][:10]:
                    if difference["kind"] == "changed":
                        emit(f"  changed   {difference['path']}")
                        emit(
                            f"            recorded {str(difference['recorded'])[:16]}  "
                            f"found {str(difference['found'])[:16]}"
                        )
                    else:
                        emit(f"  missing   {difference['path']}")
                if not result["agrees"]:
                    emit("")
                    emit(
                        "  the dataset no longer matches its manifest. Rebuild it and record the "
                        "new hash, or restore the files; do not describe the old hash as current."
                    )
                    return EXIT_DEGRADED
                return EXIT_OK

            if command == "show":
                shown = service.view(args.dataset)
                if args.json:
                    emit_json(shown)
                    return EXIT_OK
                counts = shown["counts"]
                emit(f"{shown['id']}  {shown['name']!r}  ({shown['status']})")
                emit(f"  license   {shown['license']}  ({shown['license_note']})")
                emit(f"  sources   {', '.join(shown['sources']) or '-'}")
                emit(f"  records   {counts['kept']} kept, {counts['dropped']} dropped")
                if counts["by_split"]:
                    emit(
                        "  splits    "
                        + ", ".join(
                            f"{name} {count}"
                            for name, count in sorted(counts["by_split"].items())
                        )
                    )
                emit(f"  seed      {shown['seed'] or '-'}")
                emit(f"  manifest  {shown['checksum'] or '(not built)'}")
                if shown["path"]:
                    emit(f"  export    {shown['path']}")
                if shown["transforms"]:
                    emit("")
                    emit("  ledger:")
                    for step in shown["transforms"]:
                        emit(
                            f"    {step['seq']}. {step['kind']:<7} "
                            f"{step['records_in']} -> {step['records_out']}  {step['created_at']}"
                        )
                return EXIT_OK

            if command == "records":
                records = service.records(
                    args.dataset, status=args.status, split=args.split, limit=args.limit
                )
                if args.json:
                    emit_json(records)
                    return EXIT_OK
                if not records:
                    emit("no records (archx-agent dataset scan DATASET)")
                    return EXIT_OK
                rows = [
                    [
                        record["status"],
                        record["split"] or "-",
                        record["path"],
                        record["chars"] if record["chars"] is not None else "-",
                        (record["reason"] or "")[:44],
                    ]
                    for record in records
                ]
                emit(table(rows, ["status", "split", "path", "chars", "why"]))
                return EXIT_OK

            if command == "explain":
                explained = service.explain(args.record)
                if args.json:
                    emit_json(explained)
                    return EXIT_OK
                emit(explained["sentence"])
                for step in explained["steps"]:
                    emit(
                        f"  {step['seq']}. {step['kind']:<7} {step['records_out']} records out"
                    )
                return EXIT_OK

            if command == "steps":
                steps = service.steps(args.dataset)
                if args.json:
                    emit_json(steps)
                    return EXIT_OK
                if not steps:
                    emit("no steps yet")
                    return EXIT_OK
                rows = [
                    [
                        step["seq"],
                        step["kind"],
                        step["records_in"],
                        step["records_out"],
                        json.dumps(step["report"])[:60],
                        step["created_at"],
                    ]
                    for step in steps
                ]
                emit(table(rows, ["seq", "step", "in", "out", "report", "when"]))
                return EXIT_OK

            if command == "list":
                datasets = service.list(limit=args.limit)
                if args.json:
                    emit_json(datasets)
                    return EXIT_OK
                if not datasets:
                    emit(
                        "no datasets yet (archx-agent dataset create NAME --source PATH)"
                    )
                    return EXIT_OK
                rows = [
                    [
                        dataset["id"],
                        dataset["name"],
                        dataset["status"],
                        dataset["record_count"]
                        if dataset["record_count"] is not None
                        else "-",
                        dataset["dropped_count"],
                        dataset["license"],
                        dataset["created_at"],
                    ]
                    for dataset in datasets
                ]
                emit(
                    table(
                        rows,
                        [
                            "id",
                            "name",
                            "status",
                            "kept",
                            "dropped",
                            "license",
                            "created",
                        ],
                    )
                )
                return EXIT_OK

            if command == "stats":
                data = service.stats()
                if args.json:
                    emit_json(data)
                    return EXIT_OK
                emit(
                    f"datasets  {data['datasets']}  "
                    + ", ".join(
                        f"{k} {v}" for k, v in sorted(data["by_status"].items())
                    )
                )
                emit(
                    f"records   {data['records']} ({data['kept']} kept, {data['dropped']} dropped)"
                )
                emit(f"bytes     {data['bytes_kept']} kept")
                emit(f"states    {' -> '.join(data['states'])}")
                emit(
                    "this build prepares corpora on this machine; it does not train on them "
                    "or send them anywhere"
                )
                return EXIT_OK

    except NotFoundError as exc:
        return fail(exc.message, EXIT_ERROR)
    except ValidationError as exc:
        return fail(exc.message, EXIT_USAGE)
    except ArchxError as exc:
        return fail(exc.message, EXIT_ERROR)

    return fail(f"unknown dataset command: {command}", EXIT_USAGE)
