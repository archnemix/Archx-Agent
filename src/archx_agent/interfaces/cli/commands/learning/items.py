"""Learning CLI: items operations."""

from __future__ import annotations

from archx_agent.interfaces.cli.support import emit, emit_json, table, fail, EXIT_OK, EXIT_USAGE, EXIT_DEGRADED

from archx_agent.application.learning import HintBeforeAttempt, NothingToStudy

def handle_item(args, ws, command, manager, tutor):
    sub = args.learning_item_command
    if sub == "add":
        item = manager.add_item(
            args.goal,
            args.prompt,
            expected=args.expected,
            hints=args.hint,
            explanation=args.explanation,
            subtopic=args.subtopic,
        )
        if args.json:
            emit_json(item.to_dict())
            return EXIT_OK
        emit(f"added item {item.id} to {item.goal_id}")
        emit(f"  prompt {item.prompt}")
        if item.expected:
            emit(f"  graded against: {item.expected}")
        else:
            emit("  no expected answer: this item is self-graded (--self-rate)")
        if item.hints:
            emit(f"  hints  {len(item.hints)}")
        return EXIT_OK
    if sub == "edit":
        item = manager.require_item(args.item)
        changes: dict[str, object] = {}
        if args.prompt:
            changes["topic"] = args.prompt
        if args.expected is not None:
            changes["expected"] = args.expected
        if args.explanation is not None:
            changes["explanation"] = args.explanation
        if args.subtopic is not None:
            changes["subtopic"] = args.subtopic
        if args.clear_hints and args.add_hint:
            changes["hints"] = list(args.add_hint)
        elif args.clear_hints:
            changes["hints"] = []
        elif args.hint is not None:
            changes["hints"] = args.hint
        elif args.add_hint:
            changes["hints"] = [*item.hints, *args.add_hint]
        if not changes:
            return fail(
                "nothing to change: pass --prompt, --expected, --hint, --add-hint,"
                " --clear-hints, --explanation or --subtopic",
                EXIT_USAGE,
            )
        updated = manager.update_item(item.id, **changes)
        if args.json:
            emit_json(updated.to_dict())
            return EXIT_OK
        emit(f"updated item {updated.id}")
        emit(f"  prompt {updated.prompt}")
        emit(f"  ladder {len(updated.hints)} hint(s)")
        emit(
            "  graded against: "
            + (updated.expected or "your own rating (self)")
        )
        return EXIT_OK
    if sub == "list":
        items = (
            manager.due_items(args.goal)
            if args.due
            else manager.items(args.goal, status=args.status)
        )
        if args.json:
            emit_json([item.to_dict() for item in items])
            return EXIT_OK
        if not items:
            emit("nothing due" if args.due else "no items yet")
            return EXIT_OK
        emit(
            table(
                [
                    [
                        item.id,
                        item.status,
                        "yes" if item.due else "no",
                        item.streak,
                        f"{item.interval_days:g}d",
                        item.due_at or "-",
                        item.prompt[:56],
                    ]
                    for item in items
                ],
                [
                    "item",
                    "status",
                    "due",
                    "streak",
                    "interval",
                    "next review",
                    "prompt",
                ],
            )
        )
        return EXIT_OK
    if sub == "delete":
        item = manager.require_item(args.item)
        if not args.yes:
            return fail(
                f"deleting {item.id} removes its attempts; re-run with --yes",
                EXIT_USAGE,
            )
        result = manager.delete_item(item.id)
        if args.json:
            emit_json(result)
        else:
            emit(f"deleted {item.id}")
        return EXIT_OK

def handle_next(args, ws, command, manager, tutor):
    try:
        payload = tutor.next_item(args.goal)
    except NothingToStudy as exc:
        if args.json:
            emit_json({"nothing_to_study": True, "message": exc.message})
        else:
            emit(exc.message)
        return EXIT_DEGRADED
    if args.json:
        emit_json(payload)
        return EXIT_OK
    item = payload["item"]
    emit(f"{item['id']}  {item['prompt']}")
    emit(f"  why        {payload['why']}")
    emit(
        f"  status     {item['status']}   due now {payload['due_count']}"
        + (f"   hints {item['hint_count']}" if item["hint_count"] else "")
    )
    emit("")
    emit(
        f'next: archx-agent learning answer {item["id"]} "..."'
        + ("   (or --self-rate 1-5)" if not item["expected"] else "")
    )
    return EXIT_OK

def handle_ask(args, ws, command, manager, tutor):
    try:
        payload = tutor.ask(args.goal)
    except NothingToStudy as exc:
        if args.json:
            emit_json({"nothing_to_study": True, "message": exc.message})
        else:
            emit(exc.message)
        return EXIT_DEGRADED
    if args.json:
        emit_json(payload)
        return EXIT_OK
    item = payload["item"]
    emit(item["prompt"])
    emit(f"  item       {item['id']}")
    emit(f"  why        {payload['why']}")
    emit(f"  due now    {payload['due_count']}")
    emit(
        "  answer with `learning answer` - the answer key and the hint ladder are not shown here"
    )
    return EXIT_OK

def handle_hint(args, ws, command, manager, tutor):
    try:
        payload = tutor.hint(args.item, level=args.level)
    except HintBeforeAttempt as exc:
        if args.json:
            emit_json({"refused": True, "message": exc.message})
        else:
            emit(exc.message)
        return EXIT_DEGRADED
    if args.json:
        emit_json(payload)
        return EXIT_OK
    emit(f"hint {payload['level']} of {payload['total']}: {payload['hint']}")
    if payload["more"]:
        emit(
            f"  {payload['more']} more available with --level {payload['level'] + 1}"
        )
    return EXIT_OK

def handle_answer(args, ws, command, manager, tutor):
    outcome = tutor.answer(
        args.item,
        args.answer,
        self_rating=args.self_rate,
        session_id=args.session,
        hints_used=args.hints,
    )
    if args.json:
        emit_json(outcome)
        return EXIT_OK
    grade = outcome["grade"]
    emit(
        ("correct" if grade["correct"] else "not yet")
        + f"  (graded by {grade['graded_by']})"
    )
    emit(f"  {grade['feedback']}")
    schedule = outcome["schedule"]
    emit(f"  schedule   {schedule['why']}")
    emit(
        f"  next due   {schedule['due_at']}   status {schedule['status']}"
        f"   ease {schedule['ease']:g}   streak {schedule['streak']}"
    )
    if outcome.get("explanation"):
        emit(f"  explanation {outcome['explanation']}")
    if outcome["session"]:
        session = outcome["session"]
        emit(
            f"  session    {session['id']} ({session['items_attempted']} answered,"
            f" {session['items_correct']} correct)"
        )
    return EXIT_OK
