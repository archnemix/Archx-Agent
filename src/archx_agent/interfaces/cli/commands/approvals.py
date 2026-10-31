"""Approvals command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.helpers.exceptions import (
    ValidationError,
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
    EXIT_UNAVAILABLE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    approvals = sub.add_parser("approvals", help="the approval centre")
    ap_sub = approvals.add_subparsers(dest="approvals_command", required=True)
    ap_list = ap_sub.add_parser("list", help="requests waiting for a decision")
    ap_list.add_argument(
        "--status", choices=["pending", "approved", "denied", "expired"]
    )
    ap_list.add_argument("--limit", type=int, default=50)
    ap_show = ap_sub.add_parser("show", help="one approval request")
    ap_show.add_argument("approval")
    ap_approve = ap_sub.add_parser("approve", help="approve exactly what was requested")
    ap_approve.add_argument("approval")
    ap_approve.add_argument("--reason", default="")
    ap_approve.add_argument(
        "--for", dest="for_hours", type=int, help="time-box the resulting grant"
    )
    ap_deny = ap_sub.add_parser("deny", help="deny a request (no grant is created)")
    ap_deny.add_argument("approval")
    ap_deny.add_argument("--reason", default="denied by the user")


def cmd_approvals(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.permissions
        if manager is None:
            return fail(
                "no permission centre is available in this workspace", EXIT_UNAVAILABLE
            )
        command = args.approvals_command
        if command == "list":
            if args.status:
                rows = manager.approvals(status=args.status, limit=args.limit)
            else:
                rows = manager.pending(limit=args.limit)
            if args.json:
                emit_json([a.to_dict() for a in rows])
            else:
                if not rows:
                    emit("nothing waiting for approval")
                else:
                    emit(
                        table(
                            [
                                [
                                    a.id,
                                    a.capability,
                                    a.subject,
                                    a.scope,
                                    a.expires_at or "-",
                                    (a.purpose or "")[:36],
                                ]
                                for a in rows
                            ],
                            [
                                "approval",
                                "capability",
                                "subject",
                                "scope",
                                "expires",
                                "purpose",
                            ],
                        )
                    )
                    emit("")
                    emit("approve with: archx-agent approvals approve <approval>")
            return EXIT_OK
        if command == "show":
            approval = manager.get_approval(args.approval)
            if approval.is_err:
                return fail(approval.error.message)
            emit_json(approval.value.to_dict()) if args.json else emit(
                json_text(approval.value.to_dict())
            )
            return EXIT_OK
        if command == "approve":
            try:
                approval, grant = manager.approve(
                    args.approval, reason=args.reason or "", hours=args.for_hours
                )
            except ValidationError as exc:
                return fail(exc.message, EXIT_USAGE)
            if args.json:
                emit_json({"approval": approval.to_dict(), "grant": grant.to_dict()})
            else:
                emit(f"approved {approval.id}: {grant.summary}")
                emit(
                    f"grant {grant.id} ({grant.scope}); re-run the operation to use it"
                )
            return EXIT_OK
        if command == "deny":
            try:
                approval = manager.deny(
                    args.approval, reason=args.reason or "denied by the user"
                )
            except ValidationError as exc:
                return fail(exc.message, EXIT_USAGE)
            emit_json(approval.to_dict()) if args.json else emit(
                f"denied {approval.id} ({approval.capability}); no grant was created"
            )
            return EXIT_OK
    return EXIT_USAGE
