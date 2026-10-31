"""Learning CLI: sessions operations."""

from __future__ import annotations

from archx_agent.interfaces.cli.support import emit, emit_json, table, EXIT_OK, EXIT_DEGRADED

from archx_agent.application.learning import NothingToStudy

def handle_session(args, ws, command, manager, tutor):
    sub = args.learning_session_command
    if sub == "start":
        outcome = tutor.start_session(args.goal, mode=args.mode)
        if args.json:
            emit_json(outcome)
            return EXIT_OK
        session = outcome["session"]
        emit(
            f"started {session['mode']} session {session['id']} on {session['goal_id']}"
        )
        if outcome.get("task_id"):
            emit(
                f"  task {outcome['task_id']} (this sitting is in the task history)"
            )
        emit(f"  queue {len(outcome['queue'])} item(s)")
        for item in outcome["queue"][:10]:
            emit(f"    - {item['id']}  {item['prompt'][:60]}")
        return EXIT_OK
    if sub == "list":
        sessions = manager.sessions(args.goal, limit=args.limit)
        if args.json:
            emit_json([session.to_dict() for session in sessions])
            return EXIT_OK
        if not sessions:
            emit("no sessions yet")
            return EXIT_OK
        emit(
            table(
                [
                    [
                        session.id,
                        session.goal_id,
                        session.mode,
                        session.status,
                        session.items_attempted,
                        session.items_correct,
                        session.graded_by or "-",
                        session.started_at,
                    ]
                    for session in sessions
                ],
                [
                    "session",
                    "goal",
                    "mode",
                    "status",
                    "answered",
                    "correct",
                    "graded by",
                    "started",
                ],
            )
        )
        return EXIT_OK
    if sub == "end":
        outcome = tutor.end_session(args.session)
        if args.json:
            emit_json(outcome)
            return EXIT_OK
        emit(f"closed {outcome['session']['id']}")
        emit(f"  {outcome['summary']}")
        return EXIT_OK

def handle_review(args, ws, command, manager, tutor):
    try:
        outcome = tutor.review(args.goal, limit=args.limit)
    except NothingToStudy as exc:
        if args.json:
            emit_json({"nothing_due": True, "message": exc.message})
        else:
            emit(exc.message)
        return EXIT_DEGRADED
    if args.json:
        emit_json(outcome)
        return EXIT_OK
    emit(
        f"review session {outcome['session']['id']} with {len(outcome['items'])} due item(s)"
    )
    for item in outcome["items"]:
        emit(f"  - {item['id']}  {item['prompt'][:64]}")
    return EXIT_OK
