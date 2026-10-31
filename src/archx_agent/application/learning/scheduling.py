"""LearningService: scheduling operations."""

from __future__ import annotations

from typing import Any
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.learning import (
    DEFAULT_MASTERY_STREAK,
    LearningGoal,
    LearningItem,
    LearningSession,
    due_in,
)

from .records import NothingToStudy

class LearningServiceSchedulingMixin:
    def schedule(self, item: LearningItem, *, correct: bool) -> dict[str, Any]:
        """SM-2-lite, spelled out: every number below is stored and returned."""
        start_ease = float(self._cfg("learning.start_ease", 2.5))
        min_ease = float(self._cfg("learning.min_ease", 1.3))
        mastery_streak = int(self._cfg("learning.mastery_streak", DEFAULT_MASTERY_STREAK))
        ease = float(item.ease or start_ease)
        if correct:
            streak = item.streak + 1
            if streak == 1:
                interval = 1.0
            elif streak == 2:
                interval = 3.0
            else:
                interval = round(max(float(item.interval_days or 1.0), 1.0) * ease, 2)
            ease = min(3.0, round(ease + 0.1, 3))
            status = "mastered" if (streak >= mastery_streak and interval >= 14) else "review"
            lapses = item.lapses
            due_at = due_in(interval)
            why = f"correct {streak} in a row, so the interval grows to {interval:g} day(s)"
        else:
            streak = 0
            interval = 0.0
            ease = max(min_ease, round(ease - 0.2, 3))
            status = "learning"
            lapses = item.lapses + 1
            due_at = iso_now()
            why = "not correct, so the interval resets and the item is due again now"
        return {
            "correct": correct,
            "ease": ease,
            "interval_days": interval,
            "streak": streak,
            "lapses": lapses,
            "status": status,
            "due_at": due_at,
            "why": why,
        }

    def _auto_session(self, goal: LearningGoal) -> LearningSession:
        """An answer without a session still belongs to one: work is never unattributed."""
        open_sessions = [
            session
            for session in self.manager.sessions(goal.id, limit=5)
            if session.status == "open" and session.started_at > (iso_now()[:10])
        ]
        if open_sessions:
            return open_sessions[0]
        return self.manager.create_session(goal.id, mode="practice")

    def start_session(self, goal_ref: str, *, mode: str = "practice") -> dict[str, Any]:
        goal = self.manager.require_goal(goal_ref)
        task = None
        if self.ws.tasks is not None:
            task = self.ws.tasks.create(
                "learning", f"learn: {goal.title[:60]}", start=True,
                metadata={"goal_id": goal.id, "mode": mode},
            )
        session = self.manager.create_session(goal.id, mode=mode, task_id=task.id if task else None)
        queue = self.manager.due_items(goal.id)[: int(self._cfg("learning.daily_review_limit", 20))]
        return {
            "session": session.to_dict(),
            "goal": goal.to_dict(),
            "queue": [item.to_dict() for item in queue],
            "task_id": task.id if task else None,
        }

    def review(self, goal_ref: str, *, limit: int | None = None) -> dict[str, Any]:
        goal = self.manager.require_goal(goal_ref)
        due = self.manager.due_items(
            goal.id, limit=limit or int(self._cfg("learning.daily_review_limit", 20))
        )
        if not due:
            raise NothingToStudy(
                f"nothing is due in {goal.id}. A review session with no items would be a"
                " progress report about nothing.",
                goal_id=goal.id,
            )
        started = self.start_session(goal.id, mode="review")
        return {"session": started["session"], "items": [item.to_dict() for item in due],
                "queue": [item.to_dict() for item in due]}

    def end_session(self, session_id: str) -> dict[str, Any]:
        session = self.manager.close_session(session_id)
        summary = (
            f"{session.mode} session: {session.items_attempted} answered, "
            f"{session.items_correct} correct, {session.hints_used} hint(s)"
        )
        session = self.manager.close_session(session_id, summary=summary)
        if session.task_id and self.ws.tasks is not None:
            try:
                self.ws.tasks.complete(session.task_id, summary=summary)
            except Exception:  # noqa: BLE001 - closing the record must not lose the summary
                pass
        return {"session": session.to_dict(), "summary": summary}
