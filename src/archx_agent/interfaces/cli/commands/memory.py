"""Memory command: argument registration and execution."""

from __future__ import annotations

import argparse


from typing import Any


from archx_agent.helpers.jsonio import json_text


from archx_agent.managers.memory import CATEGORIES, KINDS as MEMORY_KINDS, MemoryManager


from archx_agent.managers.models import VERIFICATION_STATES


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
    memory = sub.add_parser("memory", help="the six memory systems")
    mem_sub = memory.add_subparsers(dest="memory_command", required=True)
    mem_add = mem_sub.add_parser("add", help="store a memory")
    mem_add.add_argument("--kind", required=True, choices=list(MEMORY_KINDS))
    mem_add.add_argument("--title", required=True)
    mem_add.add_argument("--content", required=True)
    mem_add.add_argument("--category", default="note", choices=list(CATEGORIES))
    mem_add.add_argument("--project", help="project id (required for project memory)")
    mem_add.add_argument(
        "--conversation", help="conversation id (required for active memory)"
    )
    mem_add.add_argument("--task", help="task id (active memory)")
    mem_add.add_argument("--tags", help="comma separated tags")
    mem_add.add_argument("--pinned", action="store_true")
    mem_add.add_argument(
        "--slot", help="logical slot; a new value supersedes the old one"
    )
    mem_add.add_argument("--verification", choices=list(VERIFICATION_STATES))
    mem_add.add_argument("--problem", help="solution memory: the problem")
    mem_add.add_argument("--solution", help="solution memory: the solution")
    mem_add.add_argument("--topic", help="learning memory: topic")
    mem_add.add_argument("--evidence", help="solution memory: how it was verified")
    mem_add.add_argument("--limitations")
    mem_add.add_argument("--environment")
    mem_add.add_argument("--allow-duplicate", action="store_true")
    mem_add.add_argument(
        "--source",
        default="user",
        help="who/what produced this memory (user, tool, import, model)",
    )
    mem_add.add_argument(
        "--provenance-origin",
        help="where the fact came from (file, url, conversation, review)",
    )
    mem_add.add_argument(
        "--outcome",
        choices=["passed", "failed", "skipped", "in_progress"],
        help="learning memory: the recorded outcome",
    )
    mem_add.add_argument("--confidence", type=float, default=0.8)
    mem_list = mem_sub.add_parser("list", help="list memories")
    mem_list.add_argument("--kind", action="append", choices=list(MEMORY_KINDS))
    mem_list.add_argument("--project")
    mem_list.add_argument("--conversation")
    mem_list.add_argument("--status", default="active")
    mem_list.add_argument("--limit", type=int, default=50)
    mem_show = mem_sub.add_parser(
        "show", help="show one memory with provenance and history"
    )
    mem_show.add_argument("memory")
    mem_history = mem_sub.add_parser("history", help="version history of one memory")
    mem_history.add_argument("memory")
    mem_search = mem_sub.add_parser("search", help="search memories")
    mem_search.add_argument("query")
    mem_search.add_argument("--kind", action="append", choices=list(MEMORY_KINDS))
    mem_search.add_argument("--limit", type=int, default=10)
    mem_edit = mem_sub.add_parser(
        "edit", help="edit a memory (the previous version is kept)"
    )
    mem_edit.add_argument("memory")
    mem_edit.add_argument("--title")
    mem_edit.add_argument("--content")
    mem_edit.add_argument("--verification", choices=list(VERIFICATION_STATES))
    mem_edit.add_argument("--pinned", action="store_true")
    mem_edit.add_argument("--status")
    mem_delete = mem_sub.add_parser("delete", help="delete a memory")
    mem_delete.add_argument("memory")
    mem_delete.add_argument("--hard", action="store_true")
    mem_delete.add_argument("--yes", action="store_true")
    mem_retrieve = mem_sub.add_parser(
        "retrieve", help="show what memory would be injected"
    )
    mem_retrieve.add_argument("--conversation")
    mem_retrieve.add_argument("--project")
    mem_retrieve.add_argument("--query")
    mem_retrieve.add_argument("--budget", type=int, default=400)
    mem_retrieve.add_argument("--include-archival", action="store_true")
    mem_profile = mem_sub.add_parser("profile", help="learning profile")
    mem_profile.add_argument("--learner", default="default")
    mem_sub.add_parser("policy", help="documented policy for each memory kind")
    mem_sub.add_parser("stats", help="memory statistics")
    mem_retention = mem_sub.add_parser("retention", help="apply the retention policy")
    mem_retention.add_argument("--archival-days", type=int, default=365)


def cmd_memory(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        command = args.memory_command
        manager = ws.memory
        if command == "history":
            rows = manager.history(args.memory)
            emit_json(rows) if args.json else (
                emit(
                    table(
                        [[r["version"], r["change"], r["changed_at"]] for r in rows],
                        ["version", "change", "changed_at"],
                    )
                )
                if rows
                else emit("no history")
            )
            return EXIT_OK
        if command == "add":
            details = {}
            if args.problem:
                details["problem"] = args.problem
            if args.solution:
                details["solution"] = args.solution
            if args.topic:
                details["topic"] = args.topic
            if args.evidence:
                details["evidence"] = [args.evidence]
            if args.outcome:
                details["outcome"] = args.outcome
            result = manager.add(
                args.kind,
                args.title,
                args.content,
                category=args.category,
                project_id=args.project,
                conversation_id=args.conversation,
                task_id=args.task,
                tags=[t.strip() for t in (args.tags or "").split(",") if t.strip()],
                pinned=args.pinned,
                slot=args.slot,
                verification=args.verification,
                details=details or None,
                evidence=[args.evidence] if args.evidence else None,
                environment=args.environment,
                limitations=args.limitations,
                allow_duplicate=args.allow_duplicate,
                source=args.source,
                provenance={"origin": args.provenance_origin}
                if args.provenance_origin
                else None,
                confidence=args.confidence,
            )
            if result.is_err:
                return fail(f"{result.error.message}")
            memory = result.value
            if args.json:
                emit_json(memory.to_dict())
            else:
                emit(f"stored {memory.kind} memory {memory.id}")
                emit(
                    f"  scope     {memory.scope}"
                    + (f" ({memory.scope_id})" if memory.scope_id else "")
                )
                emit(f"  category  {memory.category}")
                if memory.slot:
                    emit(f"  slot      {memory.slot}")
            return EXIT_OK
        if command == "list":
            memories = manager.list(
                kinds=args.kind,
                project_id=args.project,
                conversation_id=args.conversation,
                status=args.status,
                limit=args.limit,
            )
            if args.json:
                emit_json([m.to_dict() for m in memories])
            else:
                if not memories:
                    emit("no memories")
                else:
                    emit(
                        table(
                            [
                                [
                                    m.id,
                                    m.kind,
                                    m.category,
                                    m.title[:40],
                                    m.status,
                                    m.created_at[:19],
                                ]
                                for m in memories
                            ],
                            ["id", "kind", "category", "title", "status", "created"],
                        )
                    )
            return EXIT_OK
        if command == "show":
            result = manager.get(args.memory, include_deleted=True)
            if result.is_err:
                return fail(result.error.message)
            memory = result.value
            if args.json:
                data = memory.to_dict()
                data["history"] = manager.history(memory.id)
                data["sources"] = manager.sources(memory.id)
                emit_json(data)
            else:
                emit(f"{memory.title}   ({memory.id})")
                emit(f"  kind        {memory.kind}")
                emit(
                    f"  scope       {memory.scope}"
                    + (f" ({memory.scope_id})" if memory.scope_id else "")
                )
                emit(f"  category    {memory.category}")
                emit(f"  status      {memory.status}")
                emit(f"  source      {memory.source}")
                emit(f"  provenance  {json_text(memory.provenance)}")
                emit(
                    f"  created     {memory.created_at}   updated {memory.updated_at}   version {memory.version}"
                )
                if memory.verification:
                    emit(f"  verification {memory.verification}")
                if memory.limitations:
                    emit(f"  limitations {memory.limitations}")
                if memory.artifact_path:
                    emit(f"  artifact    {memory.artifact_path}")
                emit(f"  content     {memory.content}")
                sources = manager.sources(memory.id)
                if sources:
                    emit("  sources")
                    for src in sources:
                        emit(
                            f"    {src['source_type']}: {src['reference'] or ''} {src['retrieved_at']}"
                        )
                history = manager.history(memory.id)
                if history:
                    emit("  history")
                    for entry in history:
                        emit(
                            f"    v{entry['version']} {entry['change']} at {entry['changed_at']}"
                        )
            return EXIT_OK
        if command == "search":
            outcome = manager.search(args.query, kinds=args.kind, limit=args.limit)
            if args.json:
                emit_json(
                    {
                        "mode": outcome.mode,
                        "degraded": outcome.degraded,
                        "degraded_reason": outcome.degraded_reason,
                        "hits": [
                            {
                                "memory": h.memory.to_dict(),
                                "score": h.score,
                                "reason": h.reason,
                            }
                            for h in outcome.hits
                        ],
                    }
                )
            else:
                if outcome.degraded:
                    emit(f"[degraded] {outcome.degraded_reason}")
                if not outcome.hits:
                    emit(f"no memories match {args.query!r}")
                for hit in outcome.hits:
                    emit(
                        f"{hit.score:6.2f}  {hit.memory.kind:<9} {hit.memory.title[:50]}"
                    )
                    emit(f"        {hit.memory.id}  ({hit.reason})")
            return EXIT_OK
        if command == "edit":
            fields: dict[str, Any] = {}
            if args.title is not None:
                fields["title"] = args.title
            if args.content is not None:
                fields["content"] = args.content
            if args.verification is not None:
                fields["verification"] = args.verification
            if args.pinned:
                fields["pinned"] = True
            if args.status is not None:
                fields["status"] = args.status
            if not fields:
                return fail(
                    "nothing to change; pass --title/--content/--verification/--pinned/--status"
                )
            updated = manager.update(args.memory, **fields)
            emit(f"updated {updated.id} to version {updated.version}")
            return EXIT_OK
        if command == "delete":
            if args.hard and not args.yes:
                return fail(
                    "hard delete is irreversible; re-run with --yes", EXIT_USAGE
                )
            emit(f"{args.memory}: {manager.delete(args.memory, hard=args.hard)}")
            return EXIT_OK
        if command == "retrieve":
            result = manager.retrieve_for_context(
                budget_tokens=args.budget,
                conversation_id=args.conversation,
                project_id=args.project,
                query=args.query,
                include_archival=args.include_archival,
            )
            if args.json:
                emit_json(result.to_dict())
            else:
                emit(f"budget {result.budget} tokens, used {result.tokens_used}")
                if result.degraded:
                    emit(f"[degraded] {result.notes}")
                for item in result.included:
                    emit(
                        f"  + {item['kind']:<9} {item['title'][:50]}  ({item['tokens']}t) - {item['reason']}"
                    )
                for item in result.omitted:
                    emit(
                        f"  - {item.get('kind')} {item.get('ref_id')}  ({item.get('tokens')}t) - {item.get('reason')}"
                    )
            return EXIT_OK
        if command == "profile":
            profile = manager.learner_profile(args.learner)
            emit_json(profile) if args.json else emit(json_text(profile))
            return EXIT_OK
        if command == "policy":
            policy = MemoryManager.policy()
            if args.json:
                emit_json(policy)
            else:
                for kind, entry in policy.items():
                    emit(f"{kind}")
                    emit(f"  purpose   {entry['purpose']}")
                    emit(f"  scope     {', '.join(entry['scope'])}")
                    emit(f"  injected  {entry['injected']}")
                    emit(f"  lifetime  {entry['lifetime']}")
                    emit(f"  requires  {', '.join(entry['requires'])}")
                    emit("")
            return EXIT_OK
        if command == "stats":
            stats = manager.stats()
            emit_json(stats) if args.json else emit(json_text(stats))
            return EXIT_OK
        if command == "retention":
            counts = manager.apply_retention(archival_retention_days=args.archival_days)
            emit_json(counts) if args.json else emit(json_text(counts))
            return EXIT_OK
    return EXIT_USAGE
