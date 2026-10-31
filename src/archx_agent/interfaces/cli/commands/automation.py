"""Automation command: argument registration and execution."""

from __future__ import annotations

import argparse


import json


from archx_agent.helpers.exceptions import (
    ArchxError,
    ValidationError,
)


from archx_agent.interfaces.cli.support import (
    emit_json,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_USAGE,
    EXIT_DEGRADED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    automation = sub.add_parser(
        "automation", help="Explicit-tick interval, one-shot and file-watch schedules"
    )
    au_sub = automation.add_subparsers(dest="automation_command", required=True)
    au_sub.add_parser("list")
    au_sub.add_parser("tick")
    au_serve = au_sub.add_parser(
        "serve", help="poll triggers and execute their jobs until interrupted"
    )
    au_serve.add_argument("--once", action="store_true")
    au_serve.add_argument("--poll", type=float, default=5.0)
    au_add = au_sub.add_parser("add")
    au_add.add_argument("name")
    au_add.add_argument(
        "--argv", required=True, help="command argv as JSON (no implicit shell)"
    )
    group = au_add.add_mutually_exclusive_group(required=True)
    group.add_argument("--interval", type=int)
    group.add_argument("--at", help="ISO timestamp with timezone")
    group.add_argument("--watch", help="file path inside tool roots")
    au_add.add_argument("--cwd")
    au_add.add_argument("--timeout", type=int, default=60)
    for action in ("show", "enable", "disable", "runs"):
        leaf = au_sub.add_parser(action)
        leaf.add_argument("name")


def cmd_automation(args: argparse.Namespace) -> int:
    try:
        with _workspace(args) as ws:
            action, svc = args.automation_command, ws.automation
            if action == "serve":
                import time

                if not 0.1 <= args.poll <= 3600:
                    raise ValidationError("--poll must be between 0.1 and 3600 seconds")
                while True:
                    result = svc.pump()
                    emit_json(result)
                    if args.once:
                        return (
                            EXIT_ERROR
                            if result["refused"]
                            or any(
                                job["status"] != "completed" for job in result["jobs"]
                            )
                            else EXIT_OK
                        )
                    time.sleep(args.poll)
            if action == "add":
                result = svc.create(
                    args.name,
                    json.loads(args.argv),
                    interval=args.interval,
                    at=args.at,
                    watch=args.watch,
                    cwd=args.cwd,
                    timeout=args.timeout,
                )
            elif action == "list":
                result = ws.automations.list()
            elif action == "show":
                result = ws.automations.get(args.name)
            elif action == "runs":
                result = ws.automations.runs(args.name)
            elif action in ("enable", "disable"):
                result = svc.enable(args.name, action == "enable")
            else:
                result = svc.tick()
            emit_json(result)
            return (
                EXIT_DEGRADED
                if isinstance(result, dict) and result.get("refused")
                else EXIT_OK
            )
    except (ValueError, ArchxError) as exc:
        return fail(str(exc), EXIT_USAGE)
