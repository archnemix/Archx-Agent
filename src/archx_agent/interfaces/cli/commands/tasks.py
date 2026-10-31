"""Tasks command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_UNAVAILABLE,
    EXIT_DEGRADED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    tasks = sub.add_parser(
        "tasks", help="task history, artifacts and reproduction records"
    )
    tk_sub = tasks.add_subparsers(dest="tasks_command", required=True)
    tk_list = tk_sub.add_parser("list", help="recent tasks (newest first)")
    tk_list.add_argument(
        "--status",
        choices=[
            "queued",
            "running",
            "completed",
            "failed",
            "cancelled",
            "interrupted",
        ],
    )
    tk_list.add_argument("--type", dest="task_type")
    tk_list.add_argument("--project")
    tk_list.add_argument("--conversation")
    tk_list.add_argument("--since")
    tk_list.add_argument("--limit", type=int, default=20)
    tk_show = tk_sub.add_parser(
        "show", help="one task: fields, timeline, tool runs, artifacts"
    )
    tk_show.add_argument("task")
    for verb, text in (
        ("start", "record a task and mark it running"),
        ("queue", "record a task without starting it"),
    ):
        node = tk_sub.add_parser(verb, help=text)
        node.add_argument("--type", dest="task_type", default="system")
        node.add_argument("--title")
        node.add_argument("--project")
        node.add_argument("--conversation")
        node.add_argument("--model")
        node.add_argument("--parent")
    tk_done = tk_sub.add_parser("complete", help="mark a task completed")
    tk_done.add_argument("task")
    tk_done.add_argument("--summary")
    tk_fail = tk_sub.add_parser("fail", help="mark a task failed with a reason")
    tk_fail.add_argument("task")
    tk_fail.add_argument("--error", required=True)
    tk_cancel = tk_sub.add_parser("cancel", help="cancel a task")
    tk_cancel.add_argument("task")
    tk_cancel.add_argument("--reason")
    tk_log = tk_sub.add_parser("log", help="append a step to a task's timeline")
    tk_log.add_argument("task")
    tk_log.add_argument("--kind", default="note")
    tk_log.add_argument("--detail")
    tk_q = tk_sub.add_parser("question", help="record an open question on a task")
    tk_q.add_argument("task")
    tk_q.add_argument("--text", required=True)
    tk_r = tk_sub.add_parser("resolve", help="resolve an open question (index or text)")
    tk_r.add_argument("task")
    tk_r.add_argument("question")
    tk_art = tk_sub.add_parser("artifacts", help="artifacts recorded for a task")
    tk_art.add_argument("task")
    tk_add = tk_sub.add_parser(
        "attach", help="record a file as a task artifact (and a content version)"
    )
    tk_add.add_argument("task")
    tk_add.add_argument("path")
    tk_add.add_argument("--kind", default="file")
    tk_add.add_argument("--name")
    tk_repro = tk_sub.add_parser(
        "reproduce", help="can this task be reproduced? what would it take?"
    )
    tk_repro.add_argument("task")
    tk_repro.add_argument(
        "--record", action="store_true", help="store the assessment as a record"
    )
    tk_repro.add_argument(
        "--verify",
        metavar="REPRODUCTION_ID",
        help="re-check an existing record against today's environment",
    )
    tk_sub.add_parser("stats", help="task counts by status and type")


def cmd_tasks(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.tasks
        if manager is None:
            return fail(
                "no task history is available in this workspace", EXIT_UNAVAILABLE
            )
        command = args.tasks_command
        if command == "list":
            rows = manager.list(
                status=args.status,
                kind=getattr(args, "task_type", None),
                project_id=args.project,
                conversation_id=args.conversation,
                since=args.since,
                limit=args.limit,
            )
            if args.json:
                emit_json([row.to_dict() for row in rows])
            else:
                if not rows:
                    emit("no tasks")
                else:
                    emit(
                        table(
                            [
                                [
                                    row.seq,
                                    row.created_at[11:19],
                                    row.type,
                                    row.status,
                                    len(row.tools),
                                    len(row.unresolved),
                                    row.title[:46],
                                ]
                                for row in rows
                            ],
                            ["seq", "time", "type", "status", "tools", "open", "title"],
                        )
                    )
            return EXIT_OK
        if command == "show":
            task = manager.get(args.task)
            data = {
                **task.to_dict(),
                "timeline": manager.timeline(task.id),
                "tool_runs": manager.tool_runs(task.id),
                "artifacts": [a.to_dict() for a in manager.artifacts(task.id)],
                "reproductions": [
                    r.to_dict(with_environment=False)
                    for r in ws.reproduction.records(task.id, limit=5)
                ]
                if ws.reproduction is not None
                else [],
            }
            if args.json:
                emit_json(data)
            else:
                emit(f"{task.id}  {task.type}  [{task.status}]  {task.title}")
                emit(
                    f"  created {task.created_at}   started {task.started_at or '-'}   finished {task.completed_at or '-'}"
                )
                if task.conversation_id:
                    emit(f"  conversation {task.conversation_id}")
                if task.project_id:
                    emit(f"  project {task.project_id}")
                if task.model_id:
                    emit(f"  model {task.model_id}")
                if task.tools:
                    emit(f"  tools {', '.join(task.tools)}")
                if task.error:
                    emit(f"  error {task.error}")
                if task.unresolved:
                    emit("  open questions:")
                    for index, question in enumerate(task.unresolved):
                        emit(f"   [{index}] {question}")
                if data["timeline"]:
                    emit("")
                    emit("  timeline:")
                    for entry in data["timeline"]:
                        emit(
                            f"   {entry['seq']:>4}  {entry['at'][11:19]}  {entry['kind']:<12} {(entry['detail'] or '')[:80]}"
                        )
                if data["tool_runs"]:
                    emit("")
                    emit(
                        table(
                            [
                                [
                                    run.get("seq"),
                                    run["tool_name"],
                                    run["status"],
                                    (run.get("error") or "")[:40],
                                ]
                                for run in data["tool_runs"]
                            ],
                            ["seq", "tool", "status", "error"],
                        )
                    )
                if data["artifacts"]:
                    emit("")
                    emit(
                        table(
                            [
                                [
                                    a["id"],
                                    a["kind"],
                                    a["name"],
                                    a["size"],
                                    "present" if a["exists"] else "MISSING",
                                    (a["metadata"].get("version") or "-"),
                                ]
                                for a in data["artifacts"]
                            ],
                            ["artifact", "kind", "name", "bytes", "file", "version"],
                        )
                    )
                if data["reproductions"]:
                    emit("")
                    emit(
                        table(
                            [
                                [r["id"], r["fidelity"], r["created_at"][11:19]]
                                for r in data["reproductions"]
                            ],
                            ["reproduction", "fidelity", "recorded"],
                        )
                    )
            return EXIT_OK
        if command in ("start", "queue"):
            task = manager.create(
                args.task_type,
                args.title,
                conversation_id=args.conversation,
                project_id=args.project,
                parent_task_id=args.parent,
                model_id=args.model,
                start=command == "start",
                manual=True,
            )
            emit_json(task.to_dict()) if args.json else emit(
                f"{task.id}  {task.type}  [{task.status}]  {task.title}"
            )
            return EXIT_OK
        if command == "complete":
            task = manager.complete(args.task, summary=args.summary)
            emit_json(task.to_dict()) if args.json else emit(f"{task.id} completed")
            return EXIT_OK
        if command == "fail":
            task = manager.fail(args.task, args.error)
            emit_json(task.to_dict()) if args.json else emit(
                f"{task.id} failed: {task.error}"
            )
            return EXIT_OK
        if command == "cancel":
            task = manager.cancel(args.task, args.reason or "")
            emit_json(task.to_dict()) if args.json else emit(f"{task.id} cancelled")
            return EXIT_OK
        if command == "log":
            seq = manager.log(args.task, args.kind, detail=args.detail)
            manager.get(args.task)
            emit_json({"task": args.task, "seq": seq}) if args.json else emit(
                f"{args.task}: logged {args.kind} (step {seq})"
            )
            return EXIT_OK
        if command == "question":
            task = manager.add_question(args.task, args.text)
            emit_json(task.to_dict()) if args.json else emit(
                f"{task.id}: {len(task.unresolved)} open question(s)"
            )
            return EXIT_OK
        if command == "resolve":
            task = manager.resolve_question(args.task, args.question)
            emit_json(task.to_dict()) if args.json else emit(
                f"{task.id}: {len(task.unresolved)} open question(s) remain"
            )
            return EXIT_OK
        if command == "artifacts":
            rows = manager.artifacts(args.task)
            emit_json([a.to_dict() for a in rows]) if args.json else (
                emit(
                    table(
                        [
                            [
                                a.id,
                                a.kind,
                                a.name,
                                a.size,
                                "present" if a.exists else "MISSING",
                            ]
                            for a in rows
                        ],
                        ["artifact", "kind", "name", "bytes", "file"],
                    )
                )
                if rows
                else emit("no artifacts")
            )
            return EXIT_OK
        if command == "attach":
            artifact = manager.attach_artifact(
                args.task, args.path, kind=args.kind, name=args.name
            )
            emit_json(artifact.to_dict()) if args.json else emit(
                f"{artifact.id}  {artifact.name}  {artifact.size} bytes  sha256 {artifact.checksum[:12]}...\n"
                f"version {(artifact.metadata.get('version') or 'not recorded')}"
            )
            return EXIT_OK
        if command == "reproduce":
            if ws.reproduction is None:
                return fail("no reproduction manager is available", EXIT_UNAVAILABLE)
            if args.verify:
                data = ws.reproduction.verify(args.verify)
                if args.json:
                    emit_json(data)
                else:
                    emit(f"recorded {data['recorded']}, now {data['current']}")
                    if data["new_blockers"]:
                        emit(f"  new: {', '.join(data['new_blockers'])}")
                    if data["resolved"]:
                        emit(f"  resolved: {', '.join(data['resolved'])}")
                    if data["changed_settings"]:
                        emit(
                            f"  settings changed: {', '.join(sorted(data['changed_settings']))}"
                        )
                    for issue in data["issues"]:
                        emit(f"  [{issue['level']}] {issue['code']}: {issue['detail']}")
                return EXIT_OK if not data["changed"] else EXIT_DEGRADED
            data = ws.reproduction.assess(args.task)
            record = None
            if args.record:
                record = ws.reproduction.capture(args.task)
            payload = {**data, "record": record.to_dict() if record else None}
            if args.json:
                emit_json(payload)
            else:
                emit(f"fidelity: {data['fidelity']}")
                for issue in data["issues"]:
                    emit(f"  [{issue['level']}] {issue['code']}: {issue['detail']}")
                if data["environment"].get("model"):
                    model = data["environment"]["model"]
                    emit(
                        f"model: {model.get('name') or model.get('id')} ({model.get('runtime')})"
                    )
                emit("")
                emit("commands:")
                for command_line in data["commands"]:
                    emit(f"  {command_line}")
                if record:
                    emit("")
                    emit(f"recorded as {record.id} ({record.fidelity})")
            return EXIT_OK if data["fidelity"] != "impossible" else EXIT_DEGRADED
        if command == "stats":
            data = manager.stats()
            if args.json:
                emit_json(data)
            else:
                emit(f"tasks: {data['total']}")
                for status, count in sorted(data["by_status"].items()):
                    emit(f"  {status:<12} {count}")
                emit(f"open questions on {data['with_open_questions']} task(s)")
                emit(f"artifacts: {data['artifacts']}")
            return EXIT_OK
    return EXIT_USAGE
