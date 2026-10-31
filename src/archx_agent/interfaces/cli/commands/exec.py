"""Exec command: argument registration and execution."""

from __future__ import annotations

import argparse


from typing import Any


from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
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
    exe = sub.add_parser(
        "exec",
        help="Execution targets: run a command in a container, a VM, another machine",
    )
    ex_sub = exe.add_subparsers(dest="exec_command", required=True)
    ex_sub.add_parser(
        "targets", help="which backends this machine could use, and why not"
    )
    ex_add = ex_sub.add_parser(
        "add", help="record a target (refused ones are recorded too)"
    )
    ex_add.add_argument(
        "kind",
        choices=[
            "local",
            "remote",
            "docker",
            "wsl",
            "windows-sandbox",
            "vmware",
            "virtualbox",
        ],
    )
    ex_add.add_argument("--name", default=None)
    ex_add.add_argument("--endpoint", default=None, help="for a remote target")
    ex_add.add_argument("--image", default=None, help="for docker")
    ex_add.add_argument(
        "--vm", default=None, help="for vmware (.vmx) or virtualbox (name)"
    )
    ex_add.add_argument("--distro", default=None, help="for wsl")
    ex_add.add_argument("--user", default=None)
    ex_add.add_argument("--network", default=None, help="docker network (default none)")
    ex_add.add_argument(
        "--read-only",
        dest="read_only",
        action="store_true",
        help="windows-sandbox: mount the folder read-only",
    )
    ex_sub.add_parser("targets-list", help="the recorded targets")
    ex_run = ex_sub.add_parser(
        "run", help="run one command on a target and record where it ran"
    )
    # `command` is the top-level dest for the subcommand name, so this positional must not be
    # called that: it would overwrite the chosen command and the dispatcher would see no handler.
    ex_run.add_argument("cmdline", metavar="command")
    ex_run.add_argument(
        "--target",
        default=None,
        help="a target name or kind (default: execution.target)",
    )
    ex_run.add_argument("--cwd", default=None)
    ex_run.add_argument("--timeout", type=int, default=None)
    ex_runs = ex_sub.add_parser(
        "runs", help="every command, newest first, with where it ran"
    )
    ex_runs.add_argument("--target", default=None)
    ex_runs.add_argument(
        "--status", choices=["ok", "failed", "timeout", "refused", "detached"]
    )
    ex_runs.add_argument("--limit", type=int, default=20)
    ex_show = ex_sub.add_parser("show", help="one run: invocation, output, artifacts")
    ex_show.add_argument("run")
    ex_push = ex_sub.add_parser(
        "push", help="send the project to a remote target, with hashes"
    )
    ex_push.add_argument("--target", default=None)
    ex_push.add_argument(
        "--root", default=None, help="the project directory (default execution.project)"
    )
    ex_pull = ex_sub.add_parser(
        "pull", help="bring changed files back, refusing to clobber edits"
    )
    ex_pull.add_argument("--target", default=None)
    ex_pull.add_argument("--root", default=None)
    ex_pull.add_argument(
        "--force", action="store_true", help="overwrite a file that changed here too"
    )
    ex_files = ex_sub.add_parser(
        "files", help="the file ledger: what was pushed and pulled"
    )
    ex_files.add_argument("--target", default=None)
    ex_files.add_argument("--direction", choices=["push", "pull"])
    ex_sub.add_parser("stats", help="targets, runs, conflicts")


def cmd_exec(args: argparse.Namespace) -> int:
    """`exec ...` - run a command in a chosen environment, and keep what it changed.

    Exit codes: 0 the command ran and exited 0; 1 the command ran and exited non-zero; 2 the input
    made no sense; 3 nothing ran (execution is off, the backend is unusable here, or the target
    refused) - so a script can tell "the command failed" apart from "the command never started".
    """
    command = args.exec_command
    try:
        with _workspace(args) as ws:
            service = ws.exec_env

            if command == "targets":
                probes = service.probes()
                if args.json:
                    emit_json(probes)
                    return EXIT_OK
                rows = [
                    [
                        probe["kind"],
                        "yes" if probe["available"] else "no",
                        probe["isolation"],
                        probe["enable"] or "-",
                    ]
                    for probe in probes
                ]
                emit(table(rows, ["backend", "here", "isolation", "how to enable"]))
                for probe in probes:
                    for reason in probe["why_not"]:
                        emit(f"  {probe['kind']}: {reason}")
                return EXIT_OK

            if command == "add":
                spec: dict[str, Any] = {}
                if getattr(args, "image", None):
                    spec["image"] = args.image
                if getattr(args, "vm", None):
                    spec["vm"] = args.vm
                if getattr(args, "distro", None):
                    spec["distro"] = args.distro
                if getattr(args, "user", None):
                    spec["user"] = args.user
                if getattr(args, "network", None):
                    spec["network"] = args.network
                if getattr(args, "read_only", False):
                    spec["read_only"] = True
                target = service.ensure(
                    args.kind, name=args.name, endpoint=args.endpoint, spec=spec
                )
                if args.json:
                    emit_json(target.to_dict())
                    return EXIT_OK
                emit(f"{target.name}  {target.kind}  ({target.status})")
                if target.refusal:
                    emit(f"  - {target.refusal}")
                    emit(
                        "  this target is recorded and will refuse to run until that is fixed"
                    )
                else:
                    emit(
                        f"  next      archx-agent exec run 'uname -a' --target {target.name}"
                    )
                return EXIT_OK

            if command == "targets-list":
                targets = service.targets()
                if args.json:
                    emit_json(targets)
                    return EXIT_OK
                if not targets:
                    emit(
                        "no execution targets yet (archx-agent exec add docker --image debian:12)"
                    )
                    return EXIT_OK
                rows = [
                    [
                        target["name"],
                        target["kind"],
                        target["status"],
                        target["endpoint"] or "-",
                        target["refusal"] or "-",
                    ]
                    for target in targets
                ]
                emit(table(rows, ["name", "kind", "status", "endpoint", "refusal"]))
                return EXIT_OK

            if command == "run":
                run = service.run(
                    args.cmdline, target=args.target, cwd=args.cwd, timeout=args.timeout
                )
                if args.json:
                    emit_json(run)
                    return (
                        EXIT_OK
                        if run["status"] == "ok"
                        else (EXIT_USAGE if run["status"] == "refused" else EXIT_ERROR)
                    )
                emit(
                    f"{run['status']} {run['id']}  [{run['kind']}]  exit {run['exit_code']}"
                )
                emit(f"  {run['sentence']}")
                if run["invocation"] and run["kind"] != "local":
                    emit(f"  ran       {run['invocation']}")
                if run.get("note"):
                    emit(f"  note      {run['note']}")
                for stream in ("stdout", "stderr"):
                    text = (run.get(stream) or "").strip()
                    if not text:
                        continue
                    emit(f"  {stream}:")
                    for line in text.splitlines()[:20]:
                        emit(f"    {line}")
                if run["status"] == "refused":
                    for reason in run["reasons"]:
                        emit(f"  - {reason}")
                    if run.get("approval_id"):
                        emit(
                            f"  approve    archx-agent approvals approve {run['approval_id']}"
                        )
                    return EXIT_DEGRADED
                if run["status"] == "detached":
                    return EXIT_DEGRADED
                return EXIT_OK if run["status"] == "ok" else EXIT_ERROR

            if command == "runs":
                runs = service.runs(
                    target=args.target, status=args.status, limit=args.limit
                )
                if args.json:
                    emit_json(runs)
                    return EXIT_OK
                if not runs:
                    emit(
                        "nothing has run yet (archx-agent exec run 'uname -a' --target local)"
                    )
                    return EXIT_OK
                rows = [
                    [
                        run["id"],
                        run["kind"],
                        run["status"],
                        str(run["exit_code"]),
                        run["command"][:40],
                        str(run["duration_ms"] or "-"),
                        run["started_at"],
                    ]
                    for run in runs
                ]
                emit(
                    table(
                        rows,
                        ["id", "where", "status", "exit", "command", "ms", "started"],
                    )
                )
                return EXIT_OK

            if command == "show":
                run = service.view(args.run)
                if args.json:
                    emit_json(run)
                    return EXIT_OK
                emit(
                    f"{run['id']}  [{run['kind']}]  {run['status']}  exit {run['exit_code']}"
                )
                emit(f"  {run['sentence']}")
                emit(f"  command   {run['command']}")
                if run["invocation"]:
                    emit(f"  ran       {run['invocation']}")
                for name in ("stdout_path", "stderr_path"):
                    if run[name]:
                        emit(f"  {name:<9} {run[name]}")
                if run["note"]:
                    emit(f"  note      {run['note']}")
                for reason in run.get("reasons", []):
                    emit(f"  - {reason}")
                return EXIT_OK

            if command == "push":
                pushed = service.push(args.target, root=args.root)
                if args.json:
                    emit_json(pushed)
                    return EXIT_OK
                emit(
                    f"pushed {pushed['files']} file(s), {pushed['bytes']} bytes to {pushed['target']}"
                )
                for path in pushed["paths"]:
                    emit(f"  {path}")
                return EXIT_OK

            if command == "pull":
                pulled = service.pull(args.target, root=args.root, force=args.force)
                if args.json:
                    emit_json(pulled)
                    return EXIT_OK if not pulled["conflicts"] else EXIT_DEGRADED
                emit(
                    f"pulled from {pulled['target']}  ({pulled['files']} file(s) there)"
                )
                for path in pulled["applied"]:
                    emit(f"  applied   {path}")
                for path in pulled["conflicts"]:
                    emit(f"  conflict  {path}  - changed here too; --force replaces it")
                emit(f"  {len(pulled['skipped'])} unchanged")
                return EXIT_OK if not pulled["conflicts"] else EXIT_DEGRADED

            if command == "files":
                records = ws.execution.files(direction=args.direction)
                if args.json:
                    emit_json([record.to_dict() for record in records])
                    return EXIT_OK
                if not records:
                    emit("no files have crossed a boundary yet")
                    return EXIT_OK
                rows = [
                    [
                        record.direction,
                        record.status,
                        record.path,
                        str(record.sha256_local or "-")[:12],
                        str(record.sha256_remote or "-")[:12],
                    ]
                    for record in records
                ]
                emit(table(rows, ["direction", "status", "path", "local", "remote"]))
                return EXIT_OK

            if command == "stats":
                stats = service.stats()
                if args.json:
                    emit_json(stats)
                    return EXIT_OK
                emit(
                    f"execution  {'on' if stats['enabled'] else 'off'}   "
                    f"default {stats['default_target']}"
                )
                emit(
                    f"  targets {stats['targets']}   runs {stats['runs']}   "
                    f"files {stats['files']}   conflicts {stats['conflicts']}"
                )
                for kind, count in sorted(stats["by_kind"].items()):
                    emit(f"    {kind:<10} {count}")
                for kind, available in stats["probes"].items():
                    emit(f"  {'ok ' if available else 'no '} {kind}")
                return EXIT_OK

    except ValidationError as exc:
        return fail(str(exc), EXIT_USAGE)
    except NotFoundError as exc:
        return fail(str(exc), EXIT_USAGE)
    except PermissionDeniedError as exc:
        return fail(str(exc), EXIT_DEGRADED)
    except ApprovalRequiredError as exc:
        return fail(
            f"{exc} (approve with: archx-agent approve {getattr(exc, 'approval_id', '')})",
            EXIT_DEGRADED,
        )
    except ToolError as exc:
        return fail(str(exc), EXIT_DEGRADED)
    return fail(f"unknown exec command: {command}", EXIT_USAGE)
