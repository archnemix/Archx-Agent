"""Experiment command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.helpers.exceptions import (
    NotFoundError,
    ValidationError,
)


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_USAGE,
    EXIT_DENIED,
    EXIT_DEGRADED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    exp = sub.add_parser(
        "experiment",
        help="Experimental Mode: run a declared command, keep the numbers, compare runs",
    )
    ex_sub = exp.add_subparsers(dest="experiment_command", required=True)
    ex_create = ex_sub.add_parser(
        "create", help="declare an experiment: a command and its parameters"
    )
    ex_create.add_argument("name")
    # dest is NOT "command": that is the top-level subcommand dest, and reusing it made
    # `experiment create X --command "..."` overwrite args.command, so main() found no handler.
    ex_create.add_argument(
        "--command",
        dest="experiment_line",
        required=True,
        help="the command line, with {placeholders} for the parameters",
    )
    ex_create.add_argument(
        "--root", help="where it runs (default: the first tool root)"
    )
    ex_create.add_argument("--hypothesis", help="what you expect, in one sentence")
    ex_create.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="NAME[=DEFAULT]",
        help="declare a parameter (repeatable)",
    )
    ex_create.add_argument(
        "--metric-source",
        choices=["none", "stdout-json", "file"],
        default="none",
        help="where the numbers come from (default: nowhere)",
    )
    ex_create.add_argument(
        "--metric-file",
        metavar="PATH",
        help="the JSON file the run writes (for --metric-source file)",
    )
    ex_list = ex_sub.add_parser("list", help="experiments, newest first")
    ex_list.add_argument("--status", choices=["open", "closed"])
    ex_list.add_argument("--limit", type=int, default=20)
    ex_show = ex_sub.add_parser(
        "show", help="one experiment: its runs, metrics and counts"
    )
    ex_show.add_argument("experiment")
    ex_run = ex_sub.add_parser("run", help="run it once (needs shell.run)")
    ex_run.add_argument("experiment")
    ex_run.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="override a parameter (repeatable)",
    )
    ex_run.add_argument(
        "--timeout", type=int, help="seconds before the process is killed"
    )
    ex_run.add_argument("--seed", help="a note about what made this run different")
    ex_run.add_argument("--note")
    ex_compare = ex_sub.add_parser(
        "compare", help="line the runs up and name the best one"
    )
    ex_compare.add_argument("experiment")
    ex_compare.add_argument(
        "--metric", help="which metric (default: the first one recorded)"
    )
    ex_compare.add_argument(
        "--minimise",
        "--minimize",
        dest="minimise",
        action="store_true",
        help="lower is better",
    )
    ex_compare.add_argument("--limit", type=int, default=50)
    ex_runs = ex_sub.add_parser("runs", help="every run of an experiment")
    ex_runs.add_argument("experiment")
    ex_runs.add_argument("--limit", type=int, default=50)
    ex_close = ex_sub.add_parser(
        "close", help="close an experiment (the runs stay readable)"
    )
    ex_close.add_argument("experiment")
    ex_reopen = ex_sub.add_parser("reopen", help="reopen a closed experiment")
    ex_reopen.add_argument("experiment")
    ex_del = ex_sub.add_parser("delete", help="delete an experiment and its runs")
    ex_del.add_argument("experiment")
    ex_del.add_argument("--yes", action="store_true")
    ex_sub.add_parser("stats", help="experiment counts")


def cmd_experiment(args: argparse.Namespace) -> int:
    """`experiment ...` - declare a command, run it with parameters, compare the runs.

    Exit codes follow the run: passed 0, failed 1, timeout 3, refused 4 with the approval named.
    """
    from archx_agent.helpers.exceptions import (
        ApprovalRequiredError,
        PermissionDeniedError,
    )

    command = args.experiment_command
    try:
        with _workspace(args) as ws:
            service = ws.experiment
            if command == "create":
                try:
                    params = _parse_assignments(args.param, what="parameter")
                except ValidationError as exc:
                    return fail(exc.message, EXIT_USAGE)
                declared = [
                    {"name": name, "default": (value if value != "" else None)}
                    for name, value in params.items()
                ]
                if args.metric_source == "file" and not args.metric_file:
                    return fail(
                        "--metric-source file needs --metric-file PATH", EXIT_USAGE
                    )
                metrics = {"kind": args.metric_source}
                if args.metric_file:
                    metrics["path"] = args.metric_file
                experiment = service.create(
                    args.name,
                    args.experiment_line,
                    root=args.root,
                    hypothesis=args.hypothesis,
                    params=declared,
                    metrics=metrics,
                )
                if getattr(args, "json", False):
                    emit_json(experiment.to_dict())
                    return EXIT_OK
                emit(f"created {experiment.id}  {experiment.name}")
                emit(f"  root      {experiment.root}")
                emit(f"  command   {experiment.command}")
                if experiment.param_names():
                    defaults = ", ".join(
                        f"{entry['name']}={entry['default']}"
                        for entry in experiment.params
                    )
                    emit(f"  params    {defaults}")
                source = experiment.metrics_source
                if source.get("kind") == "none":
                    emit(
                        "  metrics   none declared - an experiment that reads no numbers is "
                        "still a record, but it cannot be compared"
                    )
                elif source.get("kind") == "file":
                    emit(f"  metrics   {source.get('path')} (JSON object of numbers)")
                else:
                    emit("  metrics   the last line of stdout (JSON object of numbers)")
                emit(f"  next      archx-agent experiment run {experiment.id}")
                return EXIT_OK

            if command == "list":
                rows = service.list(status=args.status, limit=args.limit)
                if getattr(args, "json", False):
                    emit_json([row.to_dict() for row in rows])
                    return EXIT_OK
                if not rows:
                    emit(
                        "no experiments yet (archx-agent experiment create NAME --command ...)"
                    )
                    return EXIT_OK
                counts = ws.experiments.run_counts()
                for row in rows:
                    mark = "open  " if row.open else "closed"
                    stats = counts.get(row.id, {"runs": 0, "failed": 0})
                    emitted = f"{stats['runs']} run(s)"
                    if stats["failed"]:
                        emitted += f", {stats['failed']} not passed"
                    emit(f"{row.id}  {mark}  {row.name}  ({emitted})  {row.root}")
                return EXIT_OK

            if command == "show":
                shown = service.show(args.experiment)
                if getattr(args, "json", False):
                    emit_json(shown)
                    return EXIT_OK
                exp = shown["experiment"]
                emit(f"{exp['id']}  {exp['name']}  [{exp['status']}]")
                emit(f"  root      {exp['root']}")
                emit(f"  command   {exp['command']}")
                if exp["hypothesis"]:
                    emit(f"  expect    {exp['hypothesis']}")
                stats = shown["stats"]
                emit(f"  runs      {stats['runs']} ({stats['by_status']})")
                emit(
                    f"  metrics   {', '.join(shown['metric_names']) or 'none recorded'}"
                )
                if shown["runs"]:
                    emit("")
                    for run in shown["runs"]:
                        numbers = ", ".join(
                            f"{k}={v:g}" for k, v in run["metrics"].items()
                        )
                        emit(
                            f"  {run['id']}  {run['status']:<8} exit {str(run['exit_code']):<4} "
                            f"{numbers or (run['metrics_error'] or 'no metrics')}"
                        )
                return EXIT_OK

            if command == "run":
                try:
                    overrides = _parse_assignments(args.set, what="setting")
                except ValidationError as exc:
                    return fail(exc.message, EXIT_USAGE)
                run = service.run(
                    args.experiment,
                    overrides,
                    timeout=args.timeout,
                    seed=args.seed,
                    note=args.note,
                )
                if getattr(args, "json", False):
                    emit_json(run.to_dict())
                    return _experiment_exit(run)
                if run.metrics:
                    emit(", ".join(f"{k}={v:g}" for k, v in run.metrics.items()))
                elif run.metrics_error:
                    emit(f"[no metrics: {run.metrics_error}]")
                emit(
                    f"[{run.status}: exit {run.exit_code} in {int(run.duration_ms or 0)} ms]"
                )
                if run.artifact_id:
                    emit(f"[output saved as {run.artifact_id}]")
                return _experiment_exit(run)

            if command == "compare":
                table = service.compare(
                    args.experiment,
                    metric=args.metric,
                    minimise=args.minimise,
                    limit=args.limit,
                )
                if getattr(args, "json", False):
                    emit_json(table)
                    return EXIT_OK
                exp = table["experiment"]
                if table["metric"]:
                    best = table["best"]
                    emit(
                        f"{exp['name']}: {table['metric']} "
                        f"({table['direction']} wins, {len(table['runs'])} run(s))"
                    )
                    if best:
                        emit(
                            f"  best  {best['run_id']}  {table['metric']}={best['value']:g}  "
                            f"{_params_text(best['params'])}"
                        )
                else:
                    emit(
                        f"{exp['name']}: no metrics were ever read, so there is nothing to rank"
                    )
                failures = [run for run in table["runs"] if run["status"] != "passed"]
                for run in failures:
                    emit(f"  {run['id']}  {run['status']}  exit {run['exit_code']}")
                for note in table["notes"]:
                    emit(f"  note: {note}")
                return EXIT_OK

            if command == "runs":
                runs = service.runs(args.experiment, limit=args.limit)
                if getattr(args, "json", False):
                    emit_json([run.to_dict() for run in runs])
                    return EXIT_OK
                if not runs:
                    emit("this experiment has not been run yet")
                    return EXIT_OK
                for run in runs:
                    numbers = ", ".join(f"{k}={v:g}" for k, v in run.metrics.items())
                    emit(
                        f"{run.id}  {run.status:<8} exit {str(run.exit_code):<4} "
                        f"{_params_text(run.params):<28} {numbers}"
                    )
                return EXIT_OK

            if command == "close":
                experiment = service.close(args.experiment)
                if getattr(args, "json", False):
                    emit_json(experiment.to_dict())
                    return EXIT_OK
                emit(f"closed {experiment.id}  {experiment.name}")
                emit(
                    f"  the runs stay readable: archx-agent experiment show {experiment.id}"
                )
                return EXIT_OK

            if command == "reopen":
                experiment = service.reopen(args.experiment)
                if getattr(args, "json", False):
                    emit_json(experiment.to_dict())
                    return EXIT_OK
                emit(f"reopened {experiment.id}  {experiment.name}")
                return EXIT_OK

            if command == "delete":
                if not args.yes:
                    return fail(
                        "deleting an experiment deletes its runs; pass --yes to confirm",
                        EXIT_USAGE,
                    )
                service.delete(args.experiment)
                if getattr(args, "json", False):
                    emit_json({"deleted": args.experiment})
                    return EXIT_OK
                emit(f"deleted {args.experiment}")
                return EXIT_OK

            if command == "stats":
                data = service.stats()
                if getattr(args, "json", False):
                    emit_json(data)
                    return EXIT_OK
                emit(f"experiments {data['experiments']} ({data['open']} open)")
                emit(f"runs        {data['runs']} ({data['failed_runs']} not passed)")
                emit(f"metrics     {data['metrics']}")
                return EXIT_OK
    except ApprovalRequiredError as exc:
        approval = getattr(exc, "approval_id", None)
        hint = (
            f"approve it with: archx-agent approvals approve {approval}"
            if approval
            else "grant the capability with: archx-agent permissions grant <capability>"
        )
        return fail(f"{exc.message}\n{hint}", EXIT_DENIED)
    except PermissionDeniedError as exc:
        return fail(exc.message, EXIT_DENIED)
    except NotFoundError as exc:
        return fail(exc.message, EXIT_ERROR)
    except ValidationError as exc:
        return fail(exc.message, EXIT_USAGE)

    return fail(f"unknown experiment command: {command}", EXIT_USAGE)


def _parse_assignments(values: list[str], *, what: str) -> dict[str, str]:
    """Parse repeated ``NAME=VALUE`` / ``NAME`` flags into a dict, refusing near-misses."""
    out: dict[str, str] = {}
    for raw in values:
        text = str(raw)
        if "=" in text:
            name, _, value = text.partition("=")
        else:
            name, value = text, ""
        name = name.strip()
        if not name:
            raise ValidationError(f"{what} {raw!r} has no name")
        if name in out:
            raise ValidationError(f"{what} {name!r} was given twice")
        out[name] = value.strip()
    return out


def _experiment_exit(run) -> int:
    """A run's own result as an exit code the shell can branch on."""
    if run.status == "passed":
        return EXIT_OK
    if run.status == "refused":
        return EXIT_DENIED
    if run.status == "timeout":
        return EXIT_DEGRADED
    return EXIT_ERROR


def _params_text(params: dict) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(params.items())) or "-"
