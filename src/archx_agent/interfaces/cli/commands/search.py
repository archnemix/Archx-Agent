"""Search command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.helpers.exceptions import (
    ValidationError,
)


from archx_agent.application.search import SEARCH_KINDS


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_UNAVAILABLE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    srch = sub.add_parser(
        "search",
        help="one search across conversations, memory, tasks, workflows and files",
    )
    srch.add_argument("query")
    srch.add_argument(
        "--kind",
        action="append",
        choices=list(SEARCH_KINDS),
        help="limit to one source (repeatable)",
    )
    srch.add_argument(
        "--limit", type=int, help="merged results (default: search.default_limit)"
    )
    srch.add_argument(
        "--per-source", type=int, help="hits per source (default: search.per_source)"
    )
    srch.add_argument("--project")
    srch.add_argument("--conversation")
    srch.add_argument("--no-files", action="store_true", help="skip file contents")


def cmd_search(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        if ws.search is None:
            return fail("search is not available in this workspace", EXIT_UNAVAILABLE)
        try:
            report = ws.search.search(
                args.query,
                kinds=args.kind,
                limit=args.limit,
                per_source=args.per_source,
                project_id=args.project,
                conversation_id=args.conversation,
                include_files=False if args.no_files else None,
            )
        except ValidationError as exc:
            return fail(exc.message, EXIT_USAGE)
        if args.json:
            emit_json(report.to_dict())
            return EXIT_OK
        if not report.hits:
            emit(f'no matches for "{report.query}"')
        else:
            for hit in report.hits:
                emit(f"[{hit.kind}] {hit.title}  ({hit.score:.2f})")
                if hit.snippet:
                    emit(f"    {hit.snippet}")
                if hit.ref:
                    emit(f"    -> {hit.ref}")
        if report.counts:
            emit("")
            emit(
                "sources: "
                + ", ".join(f"{k} {v}" for k, v in sorted(report.counts.items()))
            )
        for note in report.degraded:
            emit(f"degraded: {note}")
        for kind, reason in sorted(report.skipped.items()):
            emit(f"skipped {kind}: {reason}")
        emit(
            f"({report.elapsed_ms:.0f}ms, scanned {sum(report.scanned.values())} record(s))"
        )
        return EXIT_OK
