"""Train command: argument registration and execution."""

from __future__ import annotations

import argparse


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
    _metric,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_USAGE,
    EXIT_DEGRADED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    train = sub.add_parser(
        "train",
        help="Training: two trainers that run here, and fine-tuning refused by name",
    )
    tr_sub = train.add_subparsers(dest="train_command", required=True)
    tr_run = tr_sub.add_parser("run", help="train a model on a built dataset")
    tr_run.add_argument(
        "--method", default="ngram", help="ngram, centroid, or lora/qlora/full"
    )
    tr_run.add_argument("--dataset", required=True, help="an id or a name")
    tr_run.add_argument("--seed", type=int, default=0)
    tr_run.add_argument(
        "--order", type=int, default=3, help="n-gram order (ngram only)"
    )
    tr_run.add_argument(
        "--smoothing", type=float, default=0.1, help="add-k constant (ngram only)"
    )
    tr_run.add_argument(
        "--label-source",
        choices=["directory", "record"],
        default="directory",
        help="where a centroid run takes its labels from",
    )
    tr_run.add_argument("--notes")
    tr_run.add_argument(
        "--target",
        choices=["local", "remote"],
        default=None,
        help="run on this machine's CPU (default) or on an M37 worker",
    )
    tr_pre = tr_sub.add_parser(
        "preflight", help="what would have to be true before a run means anything"
    )
    tr_pre.add_argument("--method", default="ngram")
    tr_pre.add_argument("--dataset")
    tr_pre.add_argument("--base-model")
    tr_list = tr_sub.add_parser("list", help="runs, newest first")
    tr_list.add_argument(
        "--status", choices=["queued", "running", "completed", "failed", "refused"]
    )
    tr_list.add_argument("--dataset")
    tr_list.add_argument("--limit", type=int, default=20)
    tr_show = tr_sub.add_parser(
        "show", help="one run: checks, metrics, artifact and reasons"
    )
    tr_show.add_argument("run")
    tr_met = tr_sub.add_parser("metrics", help="the metrics, grouped by split")
    tr_met.add_argument("run")
    tr_cmp = tr_sub.add_parser(
        "compare", help="line runs up, and name what cannot be ranked"
    )
    tr_cmp.add_argument("runs", nargs="+")
    tr_pred = tr_sub.add_parser("predict", help="use the artifact a run wrote")
    tr_pred.add_argument("run")
    tr_pred.add_argument("text")
    tr_sub.add_parser("stats", help="jobs, metrics, and what this build cannot train")


def cmd_training(args: argparse.Namespace) -> int:
    """`train ...` - run a real trainer here, or record the refusal with every reason.

    Exit codes: 0 the run completed or the question was answered; 2 the input made no sense; 3 a
    run was refused (the build cannot fine-tune) or a run failed - nothing about the request was
    malformed, and a script needs to tell "cannot" apart from "typed it wrong".
    """
    command = args.train_command
    try:
        with _workspace(args) as ws:
            service = ws.trainer

            if command == "run":
                job = service.run(
                    method=args.method,
                    dataset=args.dataset,
                    seed=args.seed,
                    order=args.order,
                    smoothing=args.smoothing,
                    label_source=args.label_source,
                    notes=args.notes or "",
                    target=getattr(args, "target", None),
                )
                if args.json:
                    emit_json(job)
                    return EXIT_OK if job["status"] == "completed" else EXIT_DEGRADED
                emit(
                    f"{job['status']} {job['id']}  {job['method']} on {job['dataset_id']}"
                )
                if job["status"] == "refused":
                    for reason in job.get("reasons", []):
                        emit(f"  - {reason}")
                    emit("")
                    emit("  nothing was trained, and nothing pretends otherwise")
                    return EXIT_DEGRADED
                if job["status"] == "failed":
                    emit(f"  error {job['error']}")
                    return EXIT_DEGRADED
                for split in ("train", "val", "test"):
                    values = job["metrics"].get(split)
                    if not values:
                        continue
                    rendered = ", ".join(
                        f"{name} {_metric(value)}"
                        for name, value in sorted(values.items())
                    )
                    emit(f"  {split:<6} {rendered}")
                emit(
                    f"  artifact  {job['artifact_path']}  sha256 {job['artifact_sha256'][:16]}..."
                )
                if job["version_id"]:
                    emit(f"  version   {job['version_id']}")
                emit(f"  next      archx-agent train show {job['id']}")
                return EXIT_OK

            if command == "preflight":
                result = service.preflight(
                    method=args.method, dataset=args.dataset, base_model=args.base_model
                )
                if args.json:
                    emit_json(result)
                    return EXIT_OK if result["runnable"] else EXIT_DEGRADED
                emit(
                    f"{result['method']}: {'runnable here' if result['runnable'] else 'not runnable'}"
                )
                for check in result["checks"]:
                    mark = "ok  " if check["ok"] else "fail"
                    emit(f"  {mark} {check['check']:<12} {check['detail']}")
                emit("")
                emit(f"  {result['note']}")
                return EXIT_OK if result["runnable"] else EXIT_DEGRADED

            if command == "list":
                runs = service.jobs(
                    status=args.status, dataset=args.dataset, limit=args.limit
                )
                if args.json:
                    emit_json(runs)
                    return EXIT_OK
                if not runs:
                    emit(
                        "no training runs yet (archx-agent train run --dataset DATASET)"
                    )
                    return EXIT_OK
                rows = [
                    [
                        run["id"],
                        run["method"],
                        run["status"],
                        run["dataset_id"] or "-",
                        run["artifact_path"] or "-",
                        run["created_at"],
                    ]
                    for run in runs
                ]
                emit(
                    table(
                        rows,
                        ["id", "method", "status", "dataset", "artifact", "created"],
                    )
                )
                return EXIT_OK

            if command == "show":
                shown = service.view(args.run)
                if args.json:
                    emit_json(shown)
                    return EXIT_OK
                emit(f"{shown['id']}  {shown['method']}  ({shown['status']})")
                emit(f"  {shown['sentence']}")
                emit(
                    f"  dataset   {shown['dataset_id'] or '-'}  seed {shown['seed']}  "
                    f"target {shown.get('target') or 'local'}"
                )
                if shown.get("remote_job_id"):
                    emit(f"  remote    {shown['remote_job_id']}")
                if shown["artifact_path"]:
                    emit(f"  artifact  {shown['artifact_path']}")
                    emit(f"  sha256    {shown['artifact_sha256'] or '-'}")
                if shown["metrics"]:
                    for split, values in sorted(shown["metrics"].items()):
                        rendered = ", ".join(
                            f"{name} {_metric(value)}"
                            for name, value in sorted(values.items())
                        )
                        emit(f"  {split:<8} {rendered}")
                for reason in shown.get("reasons", []):
                    emit(f"  - {reason}")
                return EXIT_OK

            if command == "metrics":
                data = service.metrics(args.run)
                if args.json:
                    emit_json(data)
                    return EXIT_OK
                emit(f"{data['job_id']}  {data['method']}  ({data['status']})")
                if not data["by_split"]:
                    emit("  no metrics: this run did not train anything")
                    return EXIT_OK
                for split, values in sorted(data["by_split"].items()):
                    emit(
                        f"  {split:<8} "
                        + ", ".join(
                            f"{name} {_metric(value)}"
                            for name, value in sorted(values.items())
                        )
                    )
                return EXIT_OK

            if command == "compare":
                result = service.compare(list(args.runs))
                if args.json:
                    emit_json(result)
                    return EXIT_OK
                emit(
                    f"metric {result['metric']} (lower is better)"
                    if result["lower_is_better"]
                    else f"metric {result['metric']} (higher is better)"
                )
                rows = [
                    [
                        row["job_id"],
                        row["method"],
                        row["status"],
                        "-" if row["value"] is None else f"{row['value']:.4f}",
                        "best" if row["job_id"] == result["best"] else "",
                    ]
                    for row in result["rows"]
                ]
                emit(table(rows, ["run", "method", "status", result["metric"], ""]))
                for note in result["notes"]:
                    emit(f"  note: {note}")
                return EXIT_OK

            if command == "predict":
                result = service.predict(args.run, args.text)
                if args.json:
                    emit_json(result)
                    return EXIT_OK
                if result["kind"] == "ngram":
                    emit(
                        f"perplexity {result['perplexity']:.4f}  ({result['tokens']} tokens)"
                    )
                else:
                    emit(
                        f"label {result['label']}  (known: {', '.join(result['labels'])})"
                    )
                return EXIT_OK

            if command == "stats":
                data = service.stats()
                if args.json:
                    emit_json(data)
                    return EXIT_OK
                emit(
                    f"jobs      {data['jobs']}  "
                    + (
                        ", ".join(
                            f"{k} {v}" for k, v in sorted(data["by_status"].items())
                        )
                        or "none"
                    )
                )
                emit(f"metrics   {data['metrics']} rows")
                emit(f"runnable  {', '.join(data['runnable'])}")
                emit(
                    f"fine-tune {'yes' if data['can_finetune'] else 'no'} - this build cannot "
                    "fine-tune a transformer"
                )
                for reason in data["why_not"]:
                    emit(f"  - {reason}")
                return EXIT_OK

    except NotFoundError as exc:
        return fail(exc.message, EXIT_ERROR)
    except ValidationError as exc:
        return fail(exc.message, EXIT_USAGE)
    except ArchxError as exc:
        return fail(exc.message, EXIT_ERROR)

    return fail(f"unknown train command: {command}", EXIT_USAGE)
