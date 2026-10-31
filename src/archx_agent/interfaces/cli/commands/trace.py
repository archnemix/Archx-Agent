"""Trace command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.helpers.exceptions import (
    ArchxError,
)


from archx_agent.helpers.jsonio import json_text


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_USAGE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    trace = sub.add_parser("trace", help="debug and trace")
    t_sub = trace.add_subparsers(dest="trace_command", required=True)
    t_list = t_sub.add_parser("list", help="list events")
    t_list.add_argument("--kind", action="append")
    t_list.add_argument("--conversation")
    t_list.add_argument("--task")
    t_list.add_argument("--run")
    t_list.add_argument("--status")
    t_list.add_argument("--limit", type=int, default=30)
    t_list.add_argument("--newest-first", action="store_true")
    t_show = t_sub.add_parser("show", help="show one event")
    t_show.add_argument("event")
    t_tree = t_sub.add_parser("tree", help="show the causal tree for an event")
    t_tree.add_argument("event")
    t_sub.add_parser("errors", help="recent errors and denials")
    t_sub.add_parser("summary", help="event counts by kind and status")
    t_export = t_sub.add_parser("export", help="export events as JSONL (redacted)")
    t_export.add_argument("--out", required=True)
    t_export.add_argument("--conversation")
    t_retention = t_sub.add_parser("retention", help="apply trace retention")
    t_retention.add_argument("--days", type=int)


def cmd_trace(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        store = ws.events
        store.flush()
        command = args.trace_command
        if command == "list":
            events = store.query(
                kind=args.kind,
                conversation_id=args.conversation,
                task_id=args.task,
                run_id=args.run,
                status=args.status,
                limit=args.limit,
                newest_first=args.newest_first,
            )
            if args.json:
                emit_json([e.to_dict() for e in events])
            else:
                if not events:
                    emit("no events")
                else:
                    emit(
                        table(
                            [
                                [
                                    e.seq,
                                    e.ts[11:19],
                                    e.kind,
                                    e.name,
                                    e.status,
                                    (
                                        e.payload.get("model_name")
                                        or e.payload.get("tool")
                                        or ""
                                    ),
                                ]
                                for e in events
                            ],
                            ["seq", "time", "kind", "name", "status", "detail"],
                        )
                    )
            return EXIT_OK
        if command == "show":
            event = store.get(args.event)
            if event is None:
                return fail(f"no event {args.event}")
            emit_json(event.to_dict()) if args.json else emit(
                json_text(event.to_dict())
            )
            return EXIT_OK
        if command == "tree":
            try:
                tree = store.trace_tree(args.event)
            except ArchxError as exc:
                return fail(exc.message)
            emit_json(tree) if args.json else emit(json_text(tree))
            return EXIT_OK
        if command == "errors":
            events = store.recent_errors(30)
            if args.json:
                emit_json([e.to_dict() for e in events])
            else:
                if not events:
                    emit("no errors recorded")
                for event in events:
                    emit(
                        f"{event.seq} {event.ts[11:19]} {event.kind}/{event.name} [{event.status}] {event.error or ''}"
                    )
            return EXIT_OK
        if command == "summary":
            rows = store.summaries()
            emit_json(rows) if args.json else emit(
                table(
                    [
                        [r["kind"], r["status"], r["n"], r["first_seq"], r["last_seq"]]
                        for r in rows
                    ],
                    ["kind", "status", "count", "first", "last"],
                )
            )
            return EXIT_OK
        if command == "export":
            path = store.export_jsonl(args.out, conversation_id=args.conversation)
            emit(f"exported {path}")
            return EXIT_OK
        if command == "retention":
            removed = store.apply_retention(
                max_age_days=args.days
                if args.days is not None
                else ws.config.get("trace.retention_days"),
                max_events=ws.config.get("trace.max_events"),
            )
            emit(f"removed {removed} event(s)")
            return EXIT_OK
    return EXIT_USAGE
