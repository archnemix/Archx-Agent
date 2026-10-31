"""LearningService: reporting operations."""

from __future__ import annotations

from pathlib import Path


class LearningServiceReportingMixin:
    def report(self, goal_ref: str) -> str:
        goal = self.manager.require_goal(goal_ref)
        items = self.manager.items(goal.id)
        stats = self.manager.stats(goal.id)
        due = self.manager.due_items(goal.id)
        sessions = self.manager.sessions(goal.id, limit=10)
        attempts = self.manager.attempts(goal=goal.id, limit=10)
        lines = [
            f"# Learning: {goal.title}",
            "",
            f"- goal `{goal.id}` - status **{goal.status}** - level **{goal.level}**"
            + (f" - topic **{goal.topic}**" if goal.topic else ""),
            f"- objective: {goal.objective}",
            f"- items: {stats['items']} ({', '.join(f'{k} {v}' for k, v in stats['by_status'].items()) or 'none'})",
            f"- due now: {len(due)} - attempts: {stats['attempts']} - correct: {stats['correct']}"
            + (f" ({stats['accuracy']:.0%})" if stats["accuracy"] is not None else ""),
        ]
        if goal.success_criteria:
            lines += ["", "## Success criteria", ""]
            lines += [f"- {criterion}" for criterion in goal.success_criteria]
        lines += ["", "## What is scheduled next", ""]
        if due:
            for item in due[:10]:
                lines.append(
                    f"- {item.prompt} - **due now**"
                    + (f" (streak {item.streak}, interval {item.interval_days:g}d)"
                       if item.attempts else " (new)")
                )
        elif stats["items"]:
            upcoming = sorted(
                (item for item in items if item.due_at and item.status != "mastered"),
                key=lambda item: item.due_at or "",
            )
            for item in upcoming[:10]:
                lines.append(f"- {item.prompt} - next review {item.due_at}")
            if not upcoming:
                lines.append("- nothing scheduled: every item is mastered")
        else:
            lines.append("- nothing planned yet: `learning plan` proposes checkpoints, or add items yourself")
        if sessions:
            lines += ["", "## Recent sessions", ""]
            for session in sessions[:5]:
                lines.append(
                    f"- `{session.id}` {session.mode} {session.status} - "
                    f"{session.items_attempted} answered, {session.items_correct} correct"
                    + (f" - {session.summary}" if session.summary else "")
                )
        if attempts:
            lines += ["", "## Last attempts", ""]
            for attempt in attempts[:5]:
                mark = "correct" if attempt.correct else "not yet"
                lines.append(
                    f"- {attempt.created_at} - {mark} ({attempt.graded_by})"
                    + (f" - {attempt.feedback}" if attempt.feedback else "")
                )
        lines += [
            "",
            "## How this record is graded",
            "",
            "- answers are checked against the item's expected answer (`graded_by = exact`),",
            "- or the learner rates themselves (`graded_by = self`) - Archx did not check those.",
            "- a goal is completed by you, against your criteria; this report never does it for you.",
        ]
        return "\n".join(lines) + "\n"

    def write_report(self, goal_ref: str, path: str | None = None) -> str:
        goal = self.manager.require_goal(goal_ref)
        text = self.report(goal.id)
        if path is None:
            folder = Path(str(self.ws.config.get("paths.artifacts") or self.ws.config.home))
            folder.mkdir(parents=True, exist_ok=True)
            path = str(folder / f"learning-{goal.id}.md")
        target = Path(path)
        if target.parent and not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        if self.ws.tasks is not None:
            goal_row = self.manager.get_goal(goal.id)
            if goal_row.task_id:
                try:
                    self.ws.tasks.attach_artifact(
                        goal_row.task_id, "report", str(target), description="learning progress report"
                    )
                except Exception:  # noqa: BLE001 - the file is the deliverable
                    pass
        return str(target)
