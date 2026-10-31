"""Context command: argument registration and execution."""

from __future__ import annotations

import argparse


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
    ctx = sub.add_parser("context", help="context strategies and manifests")
    ctx_sub = ctx.add_subparsers(dest="context_command", required=True)
    ctx_build = ctx_sub.add_parser("build", help="build and show a context manifest")
    ctx_build.add_argument("conversation")
    ctx_build.add_argument(
        "--strategy",
        required=True,
        choices=["oldest_first", "summarize", "ai_select", "manual", "ai_proposed"],
    )
    ctx_build.add_argument("--message", default="What should I do next?")
    ctx_build.add_argument("--budget", type=int)
    ctx_build.add_argument("--manual-ids")
    ctx_build.add_argument("--proposal")
    ctx_propose = ctx_sub.add_parser(
        "propose", help="make an AI-proposed change (nothing applied)"
    )
    ctx_propose.add_argument("conversation")
    ctx_propose.add_argument("--budget", type=int)
    ctx_reject = ctx_sub.add_parser(
        "reject", help="reject a proposal (nothing changes)"
    )
    ctx_reject.add_argument("proposal")
    ctx_reject.add_argument("--reason", default="rejected by the user")
    ctx_proposals = ctx_sub.add_parser(
        "proposals", help="list proposals for a conversation"
    )
    ctx_proposals.add_argument("conversation")
    ctx_manifests = ctx_sub.add_parser("manifests", help="list stored manifests")
    ctx_manifests.add_argument("conversation")
    ctx_summaries = ctx_sub.add_parser(
        "summaries", help="list summaries for a conversation"
    )
    ctx_summaries.add_argument("conversation")
    ctx_show = ctx_sub.add_parser("show", help="show one manifest")
    ctx_show.add_argument("manifest")


def cmd_context(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.context
        if args.context_command == "build":
            manual_ids = [
                x.strip() for x in (args.manual_ids or "").split(",") if x.strip()
            ] or None
            if args.strategy in ("summarize", "ai_proposed"):
                record = ws.resolve_model(task="chat")
                service = ws.chat
                manager.summarizer = service.summarizer_for(record)
                runtime = ws.runtime_for(record)
                manager.summary_generator = (
                    "simulated-test-double"
                    if getattr(runtime, "simulated", False)
                    else "model"
                )
            manifest = manager.build(
                args.conversation,
                strategy=args.strategy,
                user_message=args.message,
                budget_tokens=args.budget,
                manual_ids=manual_ids,
                approved_proposal_id=args.proposal,
            )
            if args.json:
                emit_json(manifest.to_dict())
            else:
                emit(f"manifest {manifest.id}  strategy={manifest.strategy}")
                emit(
                    f"budget {manifest.budget}  used {manifest.tokens_used}  memory {manifest.memory_tokens}"
                )
                if manifest.degraded:
                    emit(f"[degraded] {manifest.notes}")
                emit("included:")
                for item in manifest.included:
                    emit(
                        f"  + {item.kind:<8} {item.ref_id[:22]:<22} {item.tokens:>4}t  {item.reason[:50]}"
                    )
                if manifest.omitted:
                    emit("omitted:")
                    for item in manifest.omitted:
                        emit(
                            f"  - {item.get('kind', '-'):<8} {str(item.get('ref_id'))[:22]:<22} {item.get('tokens', '?')}t  {item.get('reason', '')[:50]}"
                        )
            return EXIT_OK
        if args.context_command == "propose":
            proposal = manager.propose(args.conversation, budget_tokens=args.budget)
            data = proposal.to_dict()
            data["note"] = (
                "nothing was applied; approve by building with --proposal <id>"
            )
            if args.json:
                emit_json(data)
            else:
                emit(json_text(data))
                emit("(nothing was applied; approve by building with --proposal <id>)")
            return EXIT_OK
        if args.context_command == "reject":
            manager.reject_proposal(args.proposal, reason=args.reason)
            emit(
                f"proposal {args.proposal} rejected: {args.reason} (history unchanged)"
            )
            return EXIT_OK
        if args.context_command == "proposals":
            rows = manager.proposals(args.conversation)
            emit_json(rows) if args.json else emit(json_text(rows))
            return EXIT_OK
        if args.context_command == "manifests":
            rows = manager.manifests(args.conversation)
            emit_json(rows) if args.json else emit(
                table(
                    [
                        [
                            r["id"],
                            r["strategy"],
                            r["tokens_used"],
                            r["token_budget"],
                            r["created_at"],
                        ]
                        for r in rows
                    ],
                    ["id", "strategy", "used", "budget", "created"],
                )
            ) if rows else emit("no manifests")
            return EXIT_OK
        if args.context_command == "summaries":
            rows = [s.to_dict() for s in manager.summaries(args.conversation)]
            emit_json(rows) if args.json else emit(json_text(rows))
            return EXIT_OK
        if args.context_command == "show":
            result = manager.manifest(args.manifest)
            if result.is_err:
                return fail(result.error.message)
            emit_json(result.value) if args.json else emit(json_text(result.value))
            return EXIT_OK
    return EXIT_USAGE
