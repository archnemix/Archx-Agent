"""Code command: argument registration and execution."""

from __future__ import annotations

import argparse


import sys


from pathlib import Path


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
    code = sub.add_parser(
        "code",
        help="Coding workspace: edit, run and test code, all through the permission centre",
    )
    cd_sub = code.add_subparsers(dest="code_command", required=True)
    cd_open = cd_sub.add_parser(
        "open", help="open a session on a directory inside the tool roots"
    )
    cd_open.add_argument("--root", help="the directory (default: the first tool root)")
    cd_open.add_argument("--title", help="what this session is for")
    cd_open.add_argument("--note")
    cd_open.add_argument("--project")
    cd_list = cd_sub.add_parser("list", help="sessions, newest first")
    cd_list.add_argument("--status", choices=["open", "closed"])
    cd_list.add_argument("--limit", type=int, default=20)
    cd_show = cd_sub.add_parser(
        "show", help="one session: its edits, its runs, its counts"
    )
    cd_show.add_argument("session")
    cd_read = cd_sub.add_parser("read", help="read a file (needs fs.read)")
    cd_read.add_argument("session")
    cd_read.add_argument("path")
    cd_read.add_argument("--start-line", type=int, default=1)
    cd_read.add_argument("--max-lines", type=int)
    cd_ls = cd_sub.add_parser("ls", help="list a directory (needs fs.read)")
    cd_ls.add_argument("session")
    cd_ls.add_argument("path", nargs="?", default=".")
    cd_ls.add_argument("--limit", type=int, default=200)
    cd_write = cd_sub.add_parser(
        "write", help="create or replace a file, recording the diff (needs fs.write)"
    )
    cd_write.add_argument("session")
    cd_write.add_argument("path")
    cd_write.add_argument("--content", help="the new text; '-' reads stdin")
    cd_write.add_argument("--file", help="read the new text from a local file")
    cd_write.add_argument("--note")
    cd_rm = cd_sub.add_parser(
        "delete", help="delete a file, recording the diff (needs fs.delete)"
    )
    cd_rm.add_argument("session")
    cd_rm.add_argument("path")
    cd_rm.add_argument("--note")
    cd_run = cd_sub.add_parser(
        "run", help="run a command in the session root (needs shell.run)"
    )
    cd_run.add_argument("session")
    # dest is NOT "command": that is the top-level subcommand dest, and reusing it made
    # `code run <session> "echo hi"` overwrite args.command, so main() found no handler.
    cd_run.add_argument(
        "code_line",
        metavar="command",
        help="the command line, split like a shell but run without one",
    )
    cd_run.add_argument(
        "--timeout", type=int, help="seconds before the process is killed"
    )
    cd_run.add_argument("--cwd", help="a directory inside the session root")
    cd_test = cd_sub.add_parser("test", help="run a named check from archx.checks.json")
    cd_test.add_argument("session")
    cd_test.add_argument("--check", default="test", help="which check (default: test)")
    cd_checks = cd_sub.add_parser("checks", help="the checks this project declares")
    cd_checks.add_argument("session")
    cd_diff = cd_sub.add_parser("diff", help="the session's whole patch")
    cd_diff.add_argument("session")
    cd_diff.add_argument("--write", metavar="PATH", help="also save the patch here")
    cd_runs = cd_sub.add_parser("runs", help="the runner's ledger for a session")
    cd_runs.add_argument("session")
    cd_runs.add_argument("--limit", type=int, default=20)
    cd_rerun = cd_sub.add_parser("rerun", help="run a recorded command again")
    cd_rerun.add_argument("run")
    cd_close = cd_sub.add_parser(
        "close", help="close a session (the record stays readable)"
    )
    cd_close.add_argument("session")
    cd_close.add_argument("--note")
    cd_sub.add_parser("stats", help="how many sessions, edits and runs this home holds")


def cmd_code(args: argparse.Namespace) -> int:
    """`code ...` - the coding workspace: edit, run and test under the permission centre.

    Exit codes follow the run, not the tool: a passing check is 0, a failing one is 1 (the same
    number the command itself returned), a timeout is 3 and a refusal is 4 with the approval named.
    """
    from archx_agent.helpers.exceptions import (
        ApprovalRequiredError,
        PermissionDeniedError,
    )

    with _workspace(args) as ws:
        service = ws.code
        command = args.code_command
        try:
            if command == "open":
                session = service.open(
                    args.root, title=args.title, note=args.note, project_id=args.project
                )
                if getattr(args, "json", False):
                    emit_json(session.to_dict())
                    return EXIT_OK
                emit(f"opened {session.id}  {session.title}")
                emit(f"  root      {session.root}")
                emit(f"  task      {session.task_id or '-'}")
                emit(
                    f"  next      archx-agent code write {session.id} hello.py --content 'print(1)'"
                )
                emit(
                    "           (a write needs fs.write: archx-agent permissions grant fs.write)"
                )
                return EXIT_OK

            if command == "list":
                sessions = service.sessions(status=args.status, limit=args.limit)
                if getattr(args, "json", False):
                    emit_json([s.to_dict() for s in sessions])
                    return EXIT_OK
                if not sessions:
                    emit("no coding sessions yet (archx-agent code open --root .)")
                    return EXIT_OK
                for session in sessions:
                    mark = "open  " if session.open else "closed"
                    emit(f"{session.id}  {mark}  {session.title}  {session.root}")
                return EXIT_OK

            if command == "show":
                shown = service.show(args.session)
                if getattr(args, "json", False):
                    emit_json(shown)
                    return EXIT_OK
                session = shown["session"]
                emit(f"{session['id']}  {session['title']}  [{session['status']}]")
                emit(f"  root   {session['root']}")
                emit(f"  task   {session['task_id'] or '-'}")
                stats = shown["stats"]
                emit(
                    f"  edits  {stats['changes']} (+{stats['added']}/-{stats['removed']})"
                )
                emit(f"  runs   {stats['runs']} ({stats['failed']} not passed)")
                if shown["changes"]:
                    emit("")
                    for change in shown["changes"]:
                        emit(
                            f"  {change['action']:<7} {change['path']}  "
                            f"+{change['added']}/-{change['removed']}"
                        )
                if shown["runs"]:
                    emit("")
                    for run in shown["runs"]:
                        emit(
                            f"  {run['status']:<8} exit {run['exit_code']}  "
                            f"{int(run['duration_ms'] or 0)} ms  {run['command'][:60]}"
                        )
                return EXIT_OK

            if command == "read":
                result = service.read(
                    args.session,
                    args.path,
                    start_line=args.start_line,
                    max_lines=args.max_lines,
                )
                if getattr(args, "json", False):
                    emit_json(result)
                    return EXIT_OK
                emit(result.get("content") or "")
                if result.get("truncated"):
                    emit(f"[truncated: {result.get('total_lines')} lines in the file]")
                return EXIT_OK

            if command == "ls":
                listing = service.list_dir(args.session, args.path, limit=args.limit)
                if getattr(args, "json", False):
                    emit_json(listing)
                    return EXIT_OK
                for entry in listing["entries"]:
                    size = "-" if entry["size"] is None else str(entry["size"])
                    emit(f"  {entry['kind']:<4} {size:>8}  {entry['name']}")
                if listing["truncated"]:
                    emit(
                        f"[{listing['count']} entries, showing {len(listing['entries'])}]"
                    )
                return EXIT_OK

            if command == "write":
                if args.content is not None and args.file:
                    return fail("pass --content or --file, not both", EXIT_USAGE)
                if args.file:
                    content = Path(args.file).read_text(encoding="utf-8")
                elif args.content == "-":
                    content = sys.stdin.read()
                elif args.content is not None:
                    content = args.content
                else:
                    return fail(
                        "a write needs --content TEXT, --content - or --file PATH",
                        EXIT_USAGE,
                    )
                change = service.write(args.session, args.path, content, note=args.note)
                if getattr(args, "json", False):
                    emit_json(change.to_dict())
                    return EXIT_OK
                emit(
                    f"{change.action} {change.path}  +{change.added}/-{change.removed}"
                )
                if change.artifact_id:
                    emit(f"  diff     {change.artifact_id}")
                return EXIT_OK

            if command == "delete":
                change = service.delete(args.session, args.path, note=args.note)
                if getattr(args, "json", False):
                    emit_json(change.to_dict())
                    return EXIT_OK
                emit(f"deleted {change.path}  (+{change.added}/-{change.removed})")
                return EXIT_OK

            if command in {"run", "test"}:
                if command == "run":
                    run = service.run(
                        args.session, args.code_line, timeout=args.timeout, cwd=args.cwd
                    )
                else:
                    run = service.test(args.session, args.check)
                if getattr(args, "json", False):
                    emit_json(run.to_dict())
                    return _run_exit(run)
                if run.stdout:
                    emit(run.stdout.rstrip())
                if run.stderr:
                    print(run.stderr.rstrip(), file=sys.stderr)
                label = f"check {run.check_name}" if run.check_name else "run"
                emit(
                    f"[{label} {run.status}: exit {run.exit_code} in "
                    f"{int(run.duration_ms or 0)} ms]"
                )
                if run.artifact_id:
                    emit(f"[output saved as {run.artifact_id}]")
                return _run_exit(run)

            if command == "checks":
                listing = service.checks(args.session)
                if getattr(args, "json", False):
                    emit_json(listing)
                    return EXIT_OK
                if not listing["checks"]:
                    emit(listing["reason"])
                    return EXIT_OK
                emit(f"{len(listing['checks'])} check(s) from {listing['source']}")
                for check in listing["checks"]:
                    timeout = f"  ({check['timeout']}s)" if check["timeout"] else ""
                    emit(f"  {check['name']:<10} {check['command']}{timeout}")
                return EXIT_OK

            if command == "diff":
                patch = service.diff(args.session)
                if args.write:
                    Path(args.write).write_text(patch["patch"], encoding="utf-8")
                if getattr(args, "json", False):
                    emit_json(patch)
                    return EXIT_OK
                if not patch["patch"]:
                    emit("this session made no changes")
                    return EXIT_OK
                emit(patch["patch"].rstrip("\n"))
                emit("")
                emit(
                    f"[{len(patch['files'])} file(s), +{patch['added']}/-{patch['removed']}]"
                )
                if args.write:
                    emit(f"[written to {args.write}]")
                return EXIT_OK

            if command == "runs":
                runs = service.runs(args.session, limit=args.limit)
                if getattr(args, "json", False):
                    emit_json([run.to_dict() for run in runs])
                    return EXIT_OK
                if not runs:
                    emit("nothing has been run in this session")
                    return EXIT_OK
                for run in runs:
                    name = f"[{run.check_name}] " if run.check_name else ""
                    emit(
                        f"{run.id}  {run.status:<8} exit {str(run.exit_code):<4} "
                        f"{int(run.duration_ms or 0):>6} ms  {name}{run.command[:70]}"
                    )
                return EXIT_OK

            if command == "rerun":
                run = service.rerun(args.run)
                if getattr(args, "json", False):
                    emit_json(run.to_dict())
                    return _run_exit(run)
                if run.stdout:
                    emit(run.stdout.rstrip())
                if run.stderr:
                    print(run.stderr.rstrip(), file=sys.stderr)
                emit(
                    f"[replay {run.status}: exit {run.exit_code} in "
                    f"{int(run.duration_ms or 0)} ms]"
                )
                return _run_exit(run)

            if command == "close":
                session = service.close(args.session, note=args.note)
                if getattr(args, "json", False):
                    emit_json(session.to_dict())
                    return EXIT_OK
                emit(f"closed {session.id}  {session.title}")
                emit(
                    "  the edits and runs stay readable: archx-agent code show "
                    f"{session.id}"
                )
                return EXIT_OK

            if command == "stats":
                data = service.stats()
                if getattr(args, "json", False):
                    emit_json(data)
                    return EXIT_OK
                emit(f"sessions {data['sessions']} ({data['open']} open)")
                emit(f"edits    {data['changes']}")
                emit(f"runs     {data['runs']} ({data['failed_runs']} not passed)")
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

        return fail(f"unknown code command: {command}", EXIT_USAGE)


def _run_exit(run) -> int:
    """A run's own result, as an exit code the shell can branch on."""
    if run.status == "passed":
        return EXIT_OK
    if run.status == "timeout":
        return EXIT_DEGRADED
    return EXIT_ERROR
