"""Research command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.helpers.exceptions import (
    NotFoundError,
    ValidationError,
)


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
    EXIT_DEGRADED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    res = sub.add_parser(
        "research", help="Researcher Mode: plan, read real sources, cite them"
    )
    res_sub = res.add_subparsers(dest="research_command", required=True)
    res_run = res_sub.add_parser("run", help="research a question end to end")
    res_run.add_argument("question")
    res_run.add_argument(
        "--mode",
        choices=["local", "web", "mixed"],
        help="where to look (default: research.default_mode)",
    )
    res_run.add_argument(
        "--url",
        action="append",
        default=[],
        metavar="URL",
        help="seed URL (repeatable); web and mixed modes need at least one",
    )
    res_run.add_argument(
        "--urls-from", metavar="FILE", help="read seed URLs from a file, one per line"
    )
    res_run.add_argument("--max-subquestions", type=int)
    res_run.add_argument(
        "--subquestion",
        action="append",
        default=[],
        metavar="TEXT",
        help="use this subquestion instead of planning (repeatable)",
    )
    res_run.add_argument("--format", choices=["markdown", "html", "md"])
    res_run.add_argument(
        "--out", help="write the report here (default: <home>/research/<run>.md)"
    )
    res_run.add_argument("--model")
    res_run.add_argument(
        "--no-model",
        action="store_true",
        help="do not call a model at all (extractive report, stated as such)",
    )
    res_run.add_argument(
        "--allow-private-hosts",
        action="store_true",
        help="let net.fetch reach loopback/private addresses (needs the grant too)",
    )
    res_list = res_sub.add_parser("list", help="research runs (newest first)")
    res_list.add_argument("--status")
    res_list.add_argument(
        "--closed", action="store_true", help="only runs you marked done"
    )
    res_list.add_argument(
        "--open", action="store_true", help="only runs you have not marked done"
    )
    res_list.add_argument("--limit", type=int, default=20)
    res_show = res_sub.add_parser(
        "show", help="one run: plan, coverage, limitations, sources"
    )
    res_show.add_argument("run")
    res_sources = res_sub.add_parser(
        "sources", help="the sources a run read, and the failures"
    )
    res_sources.add_argument("run")
    res_report = res_sub.add_parser("report", help="print the stored report")
    res_report.add_argument("run")
    res_report.add_argument("--write", help="also write it to this path")
    res_verify = res_sub.add_parser(
        "verify", help="re-check every citation in the report"
    )
    res_verify.add_argument("run")
    res_search = res_sub.add_parser("search", help="search past research runs")
    res_search.add_argument("query")
    res_search.add_argument("--limit", type=int, default=10)
    res_close = res_sub.add_parser(
        "close", help="mark a run done - your call, not the runner's"
    )
    res_close.add_argument("run")
    res_close.add_argument("--note", help="what settled it")
    res_reopen = res_sub.add_parser("reopen", help="undo a close")
    res_reopen.add_argument("run")
    res_sub.add_parser("stats", help="research counts")
    res_del = res_sub.add_parser("delete", help="delete a run and its sources")
    res_del.add_argument("run")
    res_del.add_argument("--yes", action="store_true")


def cmd_research(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        if ws.research is None:
            return fail(
                "Researcher Mode is not available in this workspace", EXIT_UNAVAILABLE
            )
        command = args.research_command

        if command == "run":
            urls = list(args.url or [])
            if getattr(args, "urls_from", None):
                try:
                    with open(args.urls_from, "r", encoding="utf-8") as handle:
                        urls.extend(
                            line.strip()
                            for line in handle
                            if line.strip() and not line.strip().startswith("#")
                        )
                except OSError as exc:
                    return fail(f"cannot read {args.urls_from}: {exc}", EXIT_USAGE)
            from archx_agent.application.researcher import ResearchBlocked

            try:
                outcome = ws.researcher.run(
                    args.question,
                    mode=args.mode,
                    urls=urls,
                    max_subquestions=args.max_subquestions,
                    subquestions=list(args.subquestion or []) or None,
                    model_id=args.model,
                    out=args.out,
                    report_format=args.format,
                    use_model=not bool(args.no_model),
                    allow_private_hosts=True if args.allow_private_hosts else None,
                )
            except ResearchBlocked as blocked:
                if args.json:
                    emit_json(
                        {
                            "run": ws.research.get(blocked.run_id).to_dict()
                            if blocked.run_id
                            else None,
                            "blocked": True,
                            "approval_id": blocked.approval_id,
                            "message": blocked.message,
                        }
                    )
                else:
                    emit("Web research needs a capability I cannot grant for you.")
                    emit(f"  {blocked.message}")
                    if blocked.approval_id:
                        emit("")
                        emit(
                            f"next: archx-agent approvals approve {blocked.approval_id}"
                        )
                return EXIT_DENIED
            except (ValidationError, NotFoundError) as exc:
                return fail(getattr(exc, "message", str(exc)), EXIT_USAGE)

            run = outcome["run"]
            verification = outcome["verification"]
            if args.json:
                emit_json(
                    {
                        "run": run,
                        "report_path": outcome["report_path"],
                        "verification": verification,
                        "plan_meta": outcome["plan_meta"],
                        "model_reading": outcome["model_reading"],
                    }
                )
            else:
                emit(f"{run['id']}  {run['status']}  {run['question'][:70]}")
                emit(
                    f"  mode {run['mode']}   plan by {run['planned_by']}   "
                    f"coverage {run['coverage']:.0%}   {run['evidence_count']} usable source(s)"
                )
                emit(f"  report: {outcome['report_path']}")
                for line in outcome["report"].splitlines():
                    if line.startswith("- **"):
                        emit(f"  {line[2:]}")
                if run["limitations"]:
                    emit("")
                    emit("limitations:")
                    for note in run["limitations"]:
                        emit(f"  - {note}")
                emit("")
                emit(f"next: archx-agent research show {run['id']}")
            problems = not verification["ok"]
            if run["status"] != "completed":
                return EXIT_DEGRADED
            return EXIT_DEGRADED if problems else EXIT_OK

        if command == "list":
            if getattr(args, "closed", False) and getattr(args, "open", False):
                return fail("--closed and --open contradict each other", EXIT_USAGE)
            closed = (
                True
                if getattr(args, "closed", False)
                else (False if getattr(args, "open", False) else None)
            )
            rows = ws.research.list(limit=args.limit, status=args.status, closed=closed)
            if args.json:
                emit_json([row.to_dict() for row in rows])
            elif not rows:
                emit("no research runs")
            else:
                emit(
                    table(
                        [
                            [
                                row.id,
                                row.status,
                                "done" if row.closed else "open",
                                f"{row.coverage:.0%}",
                                row.evidence_count,
                                row.planned_by,
                                row.mode,
                                row.question[:40],
                                row.created_at[11:19],
                            ]
                            for row in rows
                        ],
                        [
                            "run",
                            "status",
                            "closed",
                            "cover",
                            "src",
                            "plan",
                            "mode",
                            "question",
                            "created",
                        ],
                    )
                )
            return EXIT_OK

        if command in {"show", "sources", "report", "verify"}:
            try:
                run = ws.research.get(args.run)
            except NotFoundError as exc:
                return fail(getattr(exc, "message", str(exc)), EXIT_USAGE)
            sources = ws.research.sources(run.id)
            if command == "show":
                if args.json:
                    emit_json(
                        {**run.to_dict(), "sources": [s.to_dict() for s in sources]}
                    )
                    return EXIT_OK
                emit(f"{run.id}  {run.status}  {run.question}")
                emit(
                    f"  mode {run.mode}   plan by {run.planned_by}   coverage {run.coverage:.0%}   "
                    f"{run.evidence_count} usable source(s)   task {run.task_id or '-'}"
                )
                if run.report_path:
                    emit(f"  report {run.report_path}")
                emit("")
                emit("plan:")
                for index, item in enumerate(run.plan, start=1):
                    emit(f"  {index}. {item.get('question')}")
                    emit(f"     ({item.get('why') or 'no reason'})")
                if run.limitations:
                    emit("")
                    emit("limitations:")
                    for note in run.limitations:
                        emit(f"  - {note}")
                return EXIT_OK
            if command == "sources":
                if args.json:
                    emit_json([s.to_dict() for s in sources])
                    return EXIT_OK
                if not sources:
                    emit("this run recorded no sources")
                else:
                    from archx_agent.application.researcher import citation_numbers

                    labels = citation_numbers(sources)
                    emit(
                        table(
                            [
                                [
                                    f"S{labels[s.id]}" if s.id in labels else "-",
                                    s.kind,
                                    s.status,
                                    f"{s.relevance or 0:.2f}",
                                    s.stance,
                                    (s.title or "")[:36],
                                    (s.ref or s.url or "")[:44],
                                ]
                                for s in sources
                            ],
                            ["cite", "kind", "status", "rel", "stance", "title", "ref"],
                        )
                    )
                    failed = [s for s in sources if s.status != "fetched"]
                    if failed:
                        emit("")
                        emit("could not be read:")
                        for source in failed:
                            emit(f"  {source.ref}: {source.error}")
                return EXIT_OK
            if command == "report":
                if not run.report:
                    return fail(f"run {run.id} has no stored report", EXIT_DEGRADED)
                if args.write:
                    with open(args.write, "w", encoding="utf-8") as handle:
                        handle.write(run.report)
                    emit(f"wrote {args.write}")
                else:
                    emit(run.report)
                return EXIT_OK
            # verify
            from archx_agent.application.researcher import (
                ResearchRunner,
                citation_numbers,
            )

            labels = citation_numbers(sources)
            result = ResearchRunner.verify(run.report or "", list(labels.values()))
            if args.json:
                emit_json(result)
            else:
                emit(f"citations      {result['citations']}")
                emit(
                    f"sources cited  {len(result['sources_cited'])} of {len(result['sources_available'])}"
                )
                emit(f"unknown refs   {len(result['unknown_citations'])}")
                emit(f"uncited claims {len(result['uncited_claims'])}")
                for claim in result["uncited_claims"][:5]:
                    emit(f"  - {claim}")
                emit("result: " + ("ok" if result["ok"] else "problems found"))
            return EXIT_OK if result["ok"] else EXIT_DEGRADED

        if command in {"close", "reopen"}:
            try:
                if command == "close":
                    run = ws.research.close(args.run, note=args.note or "")
                else:
                    run = ws.research.reopen(args.run)
            except NotFoundError as exc:
                return fail(getattr(exc, "message", str(exc)), EXIT_USAGE)
            if args.json:
                emit_json(run.to_dict())
                return EXIT_OK
            if command == "close":
                emit(f"closed {run.id}  {run.question[:60]}")
                emit(
                    f"  the run itself was {run.status} at {run.coverage:.0%} coverage"
                )
                emit(
                    "  this is your call, not a coverage threshold - reopen it with `research reopen`"
                )
            else:
                emit(f"reopened {run.id}  {run.question[:60]}")
            return EXIT_OK

        if command == "search":
            try:
                rows = ws.research.search(args.query, limit=args.limit)
            except ValidationError as exc:
                return fail(exc.message, EXIT_USAGE)
            if args.json:
                emit_json(rows)
            elif not rows:
                emit(f"no research about {args.query!r}")
            else:
                for row in rows:
                    emit(
                        f"{row['id']}  {row['status']}  {row['coverage']:.0%}  {row['question'][:60]}"
                    )
            return EXIT_OK

        if command == "stats":
            stats = ws.research.stats()
            if args.json:
                emit_json(stats)
            else:
                emit(f"runs    {stats['total']}")
                emit(f"sources {stats['sources']}")
                for status, count in sorted(stats["by_status"].items()):
                    emit(f"  {status}: {count}")
            return EXIT_OK

        if command == "delete":
            if not args.yes:
                return fail("deleting a research run needs --yes", EXIT_USAGE)
            try:
                run = ws.research.get(args.run)
            except NotFoundError as exc:
                return fail(getattr(exc, "message", str(exc)), EXIT_USAGE)
            sources = len(ws.research.sources(run.id))
            ws.research.delete(run.id)
            emit(f"deleted {run.id} (with {sources} source row(s))")
            return EXIT_OK

    return fail(f"unknown research command {command!r}", EXIT_USAGE)
