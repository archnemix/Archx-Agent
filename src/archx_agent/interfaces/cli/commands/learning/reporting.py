"""Learning CLI: reporting operations."""

from __future__ import annotations

from archx_agent.interfaces.cli.support import emit, emit_json, table, EXIT_OK


def handle_stats(args, ws, command, manager, tutor):
    stats = manager.stats(args.goal)
    if args.json:
        emit_json(stats)
        return EXIT_OK
    if args.goal:
        emit(f"{stats['title']}  ({stats['status']})")
        emit(
            f"  items     {stats['items']}   mastered {stats['mastered']}   due {stats['due']}"
        )
        emit(
            f"  attempts  {stats['attempts']}   correct {stats['correct']}"
            + (
                f" ({stats['accuracy']:.0%})"
                if stats["accuracy"] is not None
                else ""
            )
        )
        emit(f"  sessions  {stats['sessions']}")
    else:
        emit(f"goals     {stats['goals']}")
        emit(
            f"items     {stats['items']}   mastered {stats['mastered']}   due {stats['due']}"
        )
        emit(
            f"attempts  {stats['attempts']}   correct {stats['correct']}"
            + (
                f" ({stats['accuracy']:.0%})"
                if stats["accuracy"] is not None
                else ""
            )
        )
        emit(f"sessions  {stats['sessions']}")
    return EXIT_OK

def handle_search(args, ws, command, manager, tutor):
    hits = manager.search(args.query, limit=args.limit)
    if args.json:
        emit_json(hits)
        return EXIT_OK
    if not hits:
        emit("no learning matches")
        return EXIT_OK
    emit(
        table(
            [
                [
                    hit["kind"],
                    hit["id"],
                    hit["status"],
                    f"{hit['score']:.2f}",
                    hit["title"][:60],
                ]
                for hit in hits
            ],
            ["kind", "id", "status", "score", "title"],
        )
    )
    return EXIT_OK

def handle_report(args, ws, command, manager, tutor):
    if args.write:
        path = tutor.write_report(args.goal, args.write)
        emit(f"wrote {path}")
        return EXIT_OK
    text = tutor.report(args.goal)
    if args.json:
        emit_json({"report": text})
    else:
        emit(text.rstrip())
    return EXIT_OK
