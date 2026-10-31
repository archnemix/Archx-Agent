"""Permissions command: argument registration and execution."""

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
    EXIT_DENIED,
    EXIT_UNAVAILABLE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    perms = sub.add_parser("permissions", help="capabilities, grants and denials")
    pm_sub = perms.add_subparsers(dest="permissions_command", required=True)
    pm_sub.add_parser("capabilities", help="protected operations and their risk")
    pm_list = pm_sub.add_parser("list", help="recorded grants")
    pm_list.add_argument("--capability")
    pm_list.add_argument("--subject")
    pm_list.add_argument("--all", action="store_true", help="include revoked grants")
    pm_grant = pm_sub.add_parser("grant", help="record an explicit grant")
    pm_grant.add_argument("capability")
    pm_grant.add_argument(
        "--subject", default="*", help="tool name, or '*' for any subject"
    )
    pm_grant.add_argument(
        "--duration",
        choices=["once", "task", "conversation", "project", "persistent"],
        help="how broad the grant is (default: permissions.default_duration)",
    )
    pm_grant.add_argument(
        "--for", dest="for_hours", type=int, help="expire after N hours"
    )
    pm_grant.add_argument("--reason", default="")
    pm_grant.add_argument("--conversation")
    pm_grant.add_argument("--task")
    pm_grant.add_argument("--project")
    pm_grant.add_argument(
        "--confirm",
        action="store_true",
        help="confirm a persistent grant (without it, it is downgraded)",
    )
    pm_revoke = pm_sub.add_parser("revoke", help="revoke a grant")
    pm_revoke.add_argument("grant")
    pm_revoke.add_argument("--reason", default="")
    pm_check = pm_sub.add_parser(
        "check", help="would this operation be allowed? (creates nothing)"
    )
    pm_check.add_argument("capability")
    pm_check.add_argument("--subject", required=True)
    pm_check.add_argument("--conversation")
    pm_check.add_argument("--task")
    pm_check.add_argument("--project")
    pm_sub.add_parser("prune", help="revoke expired grants")


def cmd_permissions(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.permissions
        if manager is None:
            return fail(
                "no permission centre is available in this workspace", EXIT_UNAVAILABLE
            )
        command = args.permissions_command
        if command == "capabilities":
            rows = manager.capabilities()
            emit_json(rows) if args.json else emit(
                table(
                    [
                        [r["name"], r["risk"], r["effect"], r["description"]]
                        for r in rows
                    ],
                    ["capability", "risk", "effect", "meaning"],
                )
            )
            return EXIT_OK
        if command == "list":
            grants = manager.grants(
                capability=args.capability,
                subject=args.subject,
                include_revoked=args.all,
            )
            if args.json:
                emit_json([g.to_dict() for g in grants])
            else:
                if not grants:
                    emit("no grants")
                else:
                    emit(
                        table(
                            [
                                [
                                    g.id,
                                    g.capability,
                                    g.subject,
                                    g.scope,
                                    g.expires_at or "-",
                                    g.use_count,
                                    "revoked" if g.revoked_at else "active",
                                ]
                                for g in grants
                            ],
                            [
                                "grant",
                                "capability",
                                "subject",
                                "scope",
                                "expires",
                                "uses",
                                "state",
                            ],
                        )
                    )
            return EXIT_OK
        if command == "grant":
            grant = manager.grant(
                args.capability,
                subject=args.subject,
                duration=args.duration,
                reason=args.reason or "",
                conversation_id=args.conversation,
                task_id=args.task,
                project_id=args.project,
                hours=args.for_hours,
                confirm=args.confirm,
            )
            if args.json:
                emit_json(grant.to_dict())
            else:
                emit(f"granted {grant.summary}  (id {grant.id}, by {grant.granted_by})")
                if grant.notes:
                    emit(f"note: {grant.notes}")
                if grant.expires_at:
                    emit(f"expires {grant.expires_at}")
            return EXIT_OK
        if command == "revoke":
            grant = manager.revoke(args.grant, reason=args.reason or "")
            emit_json(grant.to_dict()) if args.json else emit(
                f"revoked {grant.id} ({grant.capability})"
            )
            return EXIT_OK
        if command == "check":
            decision = manager.check(
                args.capability,
                subject=args.subject,
                conversation_id=args.conversation,
                task_id=args.task,
                project_id=args.project,
                consume=False,
                purpose="permissions check",
                request_approval_on_denial=False,
            )
            if args.json:
                emit_json(decision.to_dict())
            else:
                emit(
                    f"{'allowed' if decision.allowed else 'denied'}: {decision.reason}"
                )
            return EXIT_OK if decision.allowed else EXIT_DENIED
        if command == "prune":
            count = manager.prune_expired()
            emit_json({"revoked": count}) if args.json else emit(
                f"revoked {count} expired grant(s)"
            )
            return EXIT_OK
    return EXIT_USAGE
