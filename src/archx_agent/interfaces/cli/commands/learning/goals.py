"""Learning CLI: goals operations."""

from __future__ import annotations

from archx_agent.interfaces.cli.support import emit, emit_json, table, fail, EXIT_OK, EXIT_USAGE


def handle_goal(args, ws, command, manager, tutor):
    sub = args.learning_goal_command
    if sub == "create":
        goal = manager.create_goal(
            args.title,
            objective=args.objective,
            topic=args.topic,
            level=args.level,
            success_criteria=args.criteria,
            priority=args.priority,
            target_date=args.target_date,
        )
        if args.json:
            emit_json(goal.to_dict())
            return EXIT_OK
        emit(f"created goal {goal.id}  {goal.title}")
        emit(f"  level     {goal.level}")
        emit(f"  objective {goal.objective}")
        if goal.success_criteria:
            emit("  done when " + "; ".join(goal.success_criteria))
        emit("")
        emit(
            f"next: archx-agent learning plan {goal.id}   (propose items for this goal)"
        )
        return EXIT_OK
    if sub == "list":
        goals = manager.list_goals(status=args.status, limit=args.limit)
        if args.json:
            emit_json([goal.to_dict() for goal in goals])
            return EXIT_OK
        if not goals:
            emit(
                'no goals yet - start with: archx-agent learning goal create "Rust ownership"'
            )
            return EXIT_OK
        emit(
            table(
                [
                    [
                        goal.id,
                        goal.status,
                        goal.level,
                        goal.title[:44],
                        manager.stats(goal.id)["items"],
                        manager.stats(goal.id)["due"],
                        goal.updated_at,
                    ]
                    for goal in goals
                ],
                ["id", "status", "level", "title", "items", "due", "updated"],
            )
        )
        return EXIT_OK
    if sub == "show":
        goal = manager.require_goal(args.goal)
        items = manager.items(goal.id)
        stats = manager.stats(goal.id)
        sessions = manager.sessions(goal.id, limit=5)
        if args.json:
            emit_json(
                {
                    "goal": goal.to_dict(),
                    "items": [item.to_dict() for item in items],
                    "stats": stats,
                    "sessions": [session.to_dict() for session in sessions],
                }
            )
            return EXIT_OK
        emit(f"{goal.id}  {goal.title}")
        emit(
            f"  status    {goal.status}   level {goal.level}   priority {goal.priority}"
        )
        emit(f"  objective {goal.objective}")
        if goal.topic:
            emit(f"  topic     {goal.topic}")
        if goal.success_criteria:
            for criterion in goal.success_criteria:
                emit(f"  done when {criterion}")
        emit(
            f"  items     {stats['items']} ({', '.join(f'{k} {v}' for k, v in stats['by_status'].items()) or 'none'})   due {stats['due']}"
        )
        emit(
            f"  attempts  {stats['attempts']}   correct {stats['correct']}"
            + (
                f" ({stats['accuracy']:.0%})"
                if stats["accuracy"] is not None
                else ""
            )
        )
        if items:
            emit("")
            emit(
                table(
                    [
                        [
                            item.id,
                            item.status,
                            "yes" if item.due else "no",
                            item.streak,
                            f"{item.interval_days:g}d",
                            item.prompt[:60],
                        ]
                        for item in items
                    ],
                    ["item", "status", "due", "streak", "interval", "prompt"],
                )
            )
        else:
            emit("")
            emit(
                f"next: archx-agent learning plan {goal.id}   (or add one with item add)"
            )
        if sessions:
            emit("")
            emit(
                table(
                    [
                        [
                            session.id,
                            session.mode,
                            session.status,
                            session.items_attempted,
                            session.items_correct,
                            session.started_at,
                        ]
                        for session in sessions
                    ],
                    [
                        "session",
                        "mode",
                        "status",
                        "answered",
                        "correct",
                        "started",
                    ],
                )
            )
        return EXIT_OK
    if sub == "edit":
        fields = {}
        for name in (
            "title",
            "objective",
            "topic",
            "level",
            "priority",
            "status",
        ):
            value = getattr(args, name)
            if value is not None:
                fields[name] = value
        if args.criteria:
            fields["success_criteria"] = args.criteria
        if not fields:
            return fail(
                "nothing to change: pass at least one option", EXIT_USAGE
            )
        goal = manager.update_goal(args.goal, **fields)
        if args.json:
            emit_json(goal.to_dict())
            return EXIT_OK
        emit(f"updated {goal.id}: " + ", ".join(sorted(fields)))
        return EXIT_OK
    if sub == "complete":
        goal = manager.complete_goal(args.goal, note=args.note or "")
        if args.json:
            emit_json(goal.to_dict())
            return EXIT_OK
        emit(f"completed {goal.id}  {goal.title}")
        emit(
            "  this is your call against your criteria - Archx did not decide it for you"
        )
        return EXIT_OK
    if sub == "delete":
        goal = manager.require_goal(args.goal)
        if not args.yes:
            return fail(
                f"deleting {goal.id} removes its items, sessions and attempts; "
                "re-run with --yes",
                EXIT_USAGE,
            )
        result = manager.delete_goal(goal.id)
        emit(
            f"deleted {goal.id}"
            + ("" if args.json else " (with its items and attempts)")
        )
        if args.json:
            emit_json(result)
        return EXIT_OK

def handle_plan(args, ws, command, manager, tutor):
    outcome = tutor.plan(
        args.goal,
        use_model=not bool(args.no_model),
        max_items=args.max_items,
        model_id=args.model,
    )
    if args.json:
        emit_json(outcome)
        return EXIT_OK
    emit(f"planned {len(outcome['items'])} item(s) by {outcome['planned_by']}")
    emit(f"  why: {outcome['why']}")
    for item in outcome["items"]:
        emit(f"  - {item['id']}  {item['prompt'][:70]}")
    if outcome["planned_by"] == "rules":
        emit("")
        emit(
            "these are checkpoints of your own goal, not a curriculum: edit or delete them"
        )
    return EXIT_OK
