"""Tools command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    _parse_tool_args,
    _execute_tool,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_UNAVAILABLE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    tools = sub.add_parser(
        "tools", help="tool registry, permissions-aware execution and run history"
    )
    t2_sub = tools.add_subparsers(dest="tools_command", required=True)
    t2_sub.add_parser("list", help="every registered tool with its capability and risk")
    t2_show = t2_sub.add_parser(
        "show", help="one tool: inputs, roots and active grants"
    )
    t2_show.add_argument("tool")
    t2_run = t2_sub.add_parser(
        "run", help="run a tool (needs a grant or an approved request)"
    )
    t2_run.add_argument("tool")
    t2_run.add_argument(
        "--arg",
        action="append",
        default=[],
        metavar="key=value",
        help="tool argument (repeatable)",
    )
    t2_run.add_argument(
        "--dry-run", action="store_true", help="preview without changing anything"
    )
    t2_run.add_argument(
        "--conversation", help="conversation scope for the permission check"
    )
    t2_run.add_argument("--task", help="task scope for the permission check")
    t2_run.add_argument("--project", help="project scope for the permission check")
    t2_run.add_argument("--purpose", help="why this is being run (kept in the trace)")
    t2_runs = t2_sub.add_parser("runs", help="recent tool runs, including refusals")
    t2_runs.add_argument("--tool")
    t2_runs.add_argument("--limit", type=int, default=20)


def cmd_tools(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.tools
        if manager is None:
            return fail(
                "no tool registry is available in this workspace", EXIT_UNAVAILABLE
            )
        command = args.tools_command
        if command == "list":
            rows = manager.registry()
            if args.json:
                emit_json(rows)
            else:
                emit(
                    table(
                        [
                            [
                                row["name"],
                                row["capability"] or "-",
                                row["risk"],
                                "yes" if row["supports_dry_run"] else "no",
                                "-"
                                if row["active_grants"] is None
                                else str(row["active_grants"]),
                                row["summary"][:44],
                            ]
                            for row in rows
                        ],
                        [
                            "tool",
                            "capability",
                            "risk",
                            "dry-run",
                            "grants",
                            "what it does",
                        ],
                    )
                )
                emit("")
                emit(
                    "a tool with capability '-' needs no permission; every other tool needs a "
                    "grant or an approved request"
                )
            return EXIT_OK
        if command == "show":
            spec = manager.spec(args.tool)
            data = spec.to_dict()
            data["roots"] = ws.tool_roots()
            data["recent_runs"] = manager.runs(tool=spec.name, limit=5)
            if spec.capability:
                data["grants"] = [
                    g.to_dict()
                    for g in ws.permissions.grants(capability=spec.capability)
                ]
            if args.json:
                emit_json(data)
            else:
                emit(
                    f"{spec.name}  risk={spec.risk}  capability={spec.capability or '(none)'}"
                )
                emit(f"  {spec.summary}")
                emit(
                    f"  side effects: {spec.side_effects}   dry run: {'yes' if spec.supports_dry_run else 'no'}"
                )
                if spec.inputs:
                    emit("  inputs:")
                    for name, description in spec.inputs.items():
                        mark = "*" if name in spec.required else " "
                        emit(f"   {mark} {name:<16} {description}")
                emit(f"  roots: {', '.join(str(r) for r in data['roots'])}")
                if data.get("grants"):
                    emit("  grants:")
                    for grant in data["grants"]:
                        emit(
                            f"   {grant['id']}  {grant['scope']}  by {grant['granted_by']}"
                        )
                else:
                    emit("  grants: none")
            return EXIT_OK
        if command == "run":
            arguments = _parse_tool_args(args.arg)
            return _execute_tool(ws, manager, args.tool, arguments, args)
        if command == "runs":
            rows = manager.runs(tool=args.tool, limit=args.limit)
            if args.json:
                emit_json(rows)
            else:
                if not rows:
                    emit("no tool runs")
                else:
                    emit(
                        table(
                            [
                                [
                                    row.get("seq"),
                                    row["started_at"][11:19],
                                    row["tool_name"],
                                    row["status"],
                                    "dry" if row["dry_run"] else "",
                                    (row.get("error") or "")[:44],
                                ]
                                for row in rows
                            ],
                            ["seq", "time", "tool", "status", "dry", "error"],
                        )
                    )
            return EXIT_OK
    return EXIT_USAGE
