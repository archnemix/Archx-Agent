"""LearningService: practice operations."""

from __future__ import annotations

from typing import Any
from archx_agent.helpers.exceptions import ConflictError, ValidationError

from .records import HintBeforeAttempt, NothingToStudy, grade_answer

class LearningServicePracticeMixin:
    def _cfg(self, key: str, default: Any) -> Any:
        try:
            return self.ws.config.get(key)
        except Exception:  # noqa: BLE001
            return default

    def next_item(self, goal_ref: str) -> dict[str, Any]:
        goal = self.manager.require_goal(goal_ref)
        if goal.status != "active":
            raise ConflictError(
                f"goal {goal.id} is {goal.status}; resume it before studying"
            )
        due = self.manager.due_items(goal.id)
        limit = int(self._cfg("learning.daily_review_limit", 20))
        if due:
            item = due[0]
            why = (
                "due for review: it was seen before and its interval has elapsed"
                if item.attempts
                else "new: it has never been attempted"
            )
            return {
                "item": item.to_dict(),
                "goal": goal.to_dict(),
                "why": why,
                "due_count": len(due),
                "review_limit": limit,
            }
        scheduled = self.manager.next_due_at(goal.id)
        raise NothingToStudy(
            (
                f"nothing to study in {goal.id}: no new items and nothing due"
                + (f" (next review at {scheduled})" if scheduled else "")
                + ". Add an item with `learning item add`, or plan the goal with `learning plan`."
            ),
            goal_id=goal.id,
        )

    def ask(self, goal_ref: str) -> dict[str, Any]:
        """The next question, stripped of everything that would be an answer."""
        payload = self.next_item(goal_ref)
        item = dict(payload["item"])
        item.pop("expected", None)
        item.pop("explanation", None)
        item.pop("hints", None)
        payload["item"] = item
        return payload

    def hint(self, item_ref: str, *, level: int = 1) -> dict[str, Any]:
        item = self.manager.require_item(item_ref)
        if not item.hints:
            raise ValidationError(
                f"item {item.id} has no hints. Add some with `learning item edit --hint` "
                "so the ladder exists before it is needed."
            )
        if level < 1 or level > len(item.hints):
            raise ValidationError(
                f"this item has {len(item.hints)} hint(s); ask for a level between 1 and "
                f"{len(item.hints)}"
            )
        try_first = bool(self._cfg("learning.try_first", True))
        if try_first and item.attempts == 0:
            raise HintBeforeAttempt(
                f"try first: item {item.id} has not been attempted yet, and "
                f"learning.try_first is on. Answer it with `learning answer {item.id} \"...\"` "
                "and the ladder opens if you are still stuck.",
                item_id=item.id,
                hints=len(item.hints),
            )
        return {
            "item_id": item.id,
            "level": level,
            "total": len(item.hints),
            "hint": item.hints[level - 1],
            "more": len(item.hints) - level,
            "revealed": item.hints[:level],
            "why": "hints are ordered from a nudge to the answer, one level at a time",
        }

    def answer(
        self,
        item_ref: str,
        answer: str,
        *,
        self_rating: int | None = None,
        session_id: str | None = None,
        hints_used: int = 0,
        at: str | None = None,
    ) -> dict[str, Any]:
        item = self.manager.require_item(item_ref)
        goal = self.manager.get_goal(item.goal_id)
        if goal.status in {"completed", "abandoned"}:
            raise ConflictError(f"goal {goal.id} is {goal.status}; it cannot be studied")
        grade = grade_answer(item, answer, self_rating=self_rating)
        if session_id is None:
            session = self._auto_session(goal)
            session_id = session.id
        schedule = self.schedule(item, correct=grade.correct)
        attempt = self.manager.record_attempt(
            item.id,
            answer=answer,
            correct=grade.correct,
            graded_by=grade.graded_by,
            session_id=session_id,
            self_rating=self_rating,
            hints_used=max(0, int(hints_used)),
            feedback=grade.feedback,
            interval_days=schedule["interval_days"],
            due_at=schedule["due_at"],
            next_status=schedule["status"],
            ease=schedule["ease"],
            streak=schedule["streak"],
            lapses=schedule["lapses"],
            at=at,
        )
        return {
            "attempt": attempt.to_dict(),
            "grade": grade.to_dict(),
            "schedule": schedule,
            "item": self.manager.get_item(item.id).to_dict(),
            "session": self.manager.get_session(session_id).to_dict(),
            "explanation": item.explanation,
        }
