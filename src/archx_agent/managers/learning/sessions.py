"""Sessions operations for learning records."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.learning.constants import (
    SESSION_MODES,
    SESSION_STATUSES,
    GRADERS,
)
from archx_agent.managers.learning.records import (
    LearningSession,
    LearningAttempt,
    _session_from_row,
    _attempt_from_row,
)


class LearningManagerSessionsMixin:
    """Sessions responsibility for LearningManager."""

    def create_session(
        self,
        goal_ref: str,
        *,
        mode: str = "practice",
        task_id: str | None = None,
        status: str = "open",
    ) -> LearningSession:
        goal = self.require_goal(goal_ref)
        if mode not in SESSION_MODES:
            raise ValidationError(f"mode must be one of {', '.join(SESSION_MODES)}")
        if status not in SESSION_STATUSES:
            raise ValidationError(
                f"status must be one of {', '.join(SESSION_STATUSES)}"
            )
        if goal.status != "active":
            raise ConflictError(
                f"goal {goal.id} is {goal.status}; a session needs an active goal"
            )
        session = LearningSession(
            id=new_id("ls_"),
            goal_id=goal.id,
            mode=mode,
            status=status,
            started_at=iso_now(),
            created_at=iso_now(),
            task_id=task_id,
        )
        self._write("learning.session", {"session": session.to_dict()})
        return self.get_session(session.id)

    def get_session(self, session_id: str) -> LearningSession:
        rows = self.store.query(
            "SELECT * FROM learning_sessions WHERE id = ?", (session_id,)
        )
        if not rows:
            raise NotFoundError(f"no learning session {session_id!r}")
        return _session_from_row(rows[0])

    def sessions(
        self, goal_ref: str | None = None, *, limit: int = 20
    ) -> list[LearningSession]:
        if goal_ref:
            goal = self.require_goal(goal_ref)
            rows = self.store.query(
                "SELECT * FROM learning_sessions WHERE goal_id = ?"
                " ORDER BY started_at DESC LIMIT ?",
                (goal.id, max(1, limit)),
            )
        else:
            rows = self.store.query(
                "SELECT * FROM learning_sessions ORDER BY started_at DESC LIMIT ?",
                (max(1, limit),),
            )
        return [_session_from_row(row) for row in rows]

    def record_attempt(
        self,
        item_ref: str,
        *,
        answer: str,
        correct: bool,
        graded_by: str,
        session_id: str | None = None,
        self_rating: int | None = None,
        hints_used: int = 0,
        feedback: str | None = None,
        interval_days: float | None = None,
        due_at: str | None = None,
        next_status: str | None = None,
        ease: float | None = None,
        streak: int | None = None,
        lapses: int | None = None,
        at: str | None = None,
    ) -> LearningAttempt:
        item = self.require_item(item_ref)
        if graded_by not in GRADERS:
            raise ValidationError(f"graded_by must be one of {', '.join(GRADERS)}")
        moment = at or iso_now()
        self._write(
            "learning.attempt",
            {
                "attempt": {
                    "session_id": session_id,
                    "goal_id": item.goal_id,
                    "item_id": item.id,
                    "answer": answer,
                    "correct": bool(correct),
                    "graded_by": graded_by,
                    "self_rating": self_rating,
                    "hints_used": int(hints_used),
                    "feedback": feedback,
                    "interval_days": interval_days,
                    "due_at": due_at,
                    "created_at": moment,
                }
            },
        )
        fields: dict[str, Any] = {
            "attempts": item.attempts + 1,
            "correct_count": item.correct_count + (1 if correct else 0),
            "last_reviewed_at": moment,
        }
        if interval_days is not None:
            fields["interval_days"] = interval_days
        if due_at is not None:
            fields["due_at"] = due_at
        if ease is not None:
            fields["ease"] = ease
        if streak is not None:
            fields["streak"] = streak
        if lapses is not None:
            fields["lapses"] = lapses
        if next_status is not None:
            fields["status"] = next_status
        self._write("learning.item_update", {"id": item.id, "fields": fields})
        if session_id:
            session = self.get_session(session_id)
            self._write(
                "learning.session_update",
                {
                    "id": session.id,
                    "fields": {
                        "items_attempted": session.items_attempted + 1,
                        "items_correct": session.items_correct + (1 if correct else 0),
                        "hints_used": session.hints_used + int(hints_used),
                        "graded_by": graded_by,
                    },
                },
            )
        rows = self.store.query(
            "SELECT * FROM learning_attempts WHERE item_id = ? ORDER BY id DESC LIMIT 1",
            (item.id,),
        )
        return _attempt_from_row(rows[0])

    def attempts(
        self,
        *,
        item: str | None = None,
        goal: str | None = None,
        session: str | None = None,
        limit: int = 50,
    ) -> list[LearningAttempt]:
        clauses: list[str] = []
        params: list[Any] = []
        if item:
            clauses.append("item_id = ?")
            params.append(self.require_item(item).id)
        if goal:
            clauses.append("goal_id = ?")
            params.append(self.require_goal(goal).id)
        if session:
            clauses.append("session_id = ?")
            params.append(self.get_session(session).id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.store.query(
            "SELECT * FROM learning_attempts" + where + " ORDER BY id DESC LIMIT ?",
            (*params, max(1, limit)),
        )
        return [_attempt_from_row(row) for row in rows]

    def close_session(
        self, session_id: str, *, summary: str | None = None
    ) -> LearningSession:
        session = self.get_session(session_id)
        if session.status == "closed":
            return session
        self._write(
            "learning.session_update",
            {
                "id": session.id,
                "fields": {
                    "status": "closed",
                    "ended_at": iso_now(),
                    "summary": summary,
                },
            },
        )
        return self.get_session(session.id)
