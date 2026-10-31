"""Goals operations for learning records."""

from __future__ import annotations

from typing import Any, Sequence

from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.learning.constants import (
    LEVELS,
    GOAL_STATUSES,
    TERMINAL_GOALS,
    PLANNERS,
)
from archx_agent.managers.learning.records import LearningGoal, _goal_from_row


class LearningManagerGoalsMixin:
    """Goals responsibility for LearningManager."""

    def create_goal(
        self,
        title: str,
        *,
        objective: str | None = None,
        level: str = "beginner",
        topic: str | None = None,
        success_criteria: Sequence[str] = (),
        priority: int = 5,
        target_date: str | None = None,
        status: str = "active",
        planned_by: str = "user",
        source: str = "user",
        task_id: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> LearningGoal:
        title = (title or "").strip()
        if len(title) < 3:
            raise ValidationError(
                "a learning goal needs a title of at least three characters"
            )
        if level not in LEVELS:
            raise ValidationError(f"level must be one of {', '.join(LEVELS)}")
        if status not in GOAL_STATUSES:
            raise ValidationError(f"status must be one of {', '.join(GOAL_STATUSES)}")
        if planned_by not in PLANNERS:
            raise ValidationError(f"planned_by must be one of {', '.join(PLANNERS)}")
        if not 0 <= int(priority) <= 9:
            raise ValidationError("priority must be between 0 and 9")
        limit = int(self._cfg("learning.active_goal_limit", 5))
        active = int(
            self.store.scalar(
                "SELECT COUNT(*) FROM learning_goals WHERE status = 'active'"
            )
            or 0
        )
        if status == "active" and active >= limit:
            raise ConflictError(
                f"{active} goals are already active (learning.active_goal_limit={limit});"
                " finish or pause one first - Archx will not quietly drop one"
            )
        criteria = [str(item).strip() for item in success_criteria if str(item).strip()]
        goal = LearningGoal(
            id=new_id("lg_"),
            title=title,
            objective=(objective or title).strip(),
            status=status,
            created_at=iso_now(),
            updated_at=iso_now(),
            level=level,
            topic=(topic or "").strip() or None,
            success_criteria=criteria,
            priority=int(priority),
            target_date=target_date,
            task_id=task_id,
            settings=dict(settings or {}),
            planned_by=planned_by,
            source=source,
        )
        self._write("learning.goal", {"goal": goal.to_dict()})
        self.trace("learning", "goal.created", payload=goal.to_dict())
        return goal

    def get_goal(self, goal_id: str) -> LearningGoal:
        rows = self.store.query("SELECT * FROM learning_goals WHERE id = ?", (goal_id,))
        if not rows:
            raise NotFoundError(f"no learning goal {goal_id!r}")
        return _goal_from_row(rows[0])

    def find_goal(self, ref: str) -> LearningGoal | None:
        """Accept an id, an exact title, or a unique prefix - the way a person refers to it."""
        ref = (ref or "").strip()
        if not ref:
            return None
        rows = self.store.query("SELECT * FROM learning_goals WHERE id = ?", (ref,))
        if rows:
            return _goal_from_row(rows[0])
        rows = self.store.query(
            "SELECT * FROM learning_goals WHERE LOWER(title) = LOWER(?)", (ref,)
        )
        if rows:
            return _goal_from_row(rows[0])
        rows = self.store.query(
            "SELECT * FROM learning_goals WHERE id LIKE ? OR LOWER(title) LIKE ?"
            " ORDER BY created_at DESC LIMIT 2",
            (ref + "%", "%" + ref.lower() + "%"),
        )
        if len(rows) > 1:
            raise ValidationError(f"{ref!r} matches more than one goal; use the id")
        return _goal_from_row(rows[0]) if rows else None

    def require_goal(self, ref: str) -> LearningGoal:
        goal = self.find_goal(ref)
        if goal is None:
            raise NotFoundError(f"no learning goal {ref!r}")
        return goal

    def list_goals(
        self, *, status: str | None = None, limit: int = 20
    ) -> list[LearningGoal]:
        if status is not None and status not in GOAL_STATUSES:
            raise ValidationError(f"unknown goal status {status!r}")
        clause = " WHERE status = ?" if status else ""
        params: tuple[Any, ...] = (
            (status, max(1, limit)) if status else (max(1, limit),)
        )
        rows = self.store.query(
            "SELECT * FROM learning_goals"
            + clause
            + " ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,"
            " priority DESC, updated_at DESC LIMIT ?",
            params,
        )
        return [_goal_from_row(row) for row in rows]

    def update_goal(self, ref: str, **fields: Any) -> LearningGoal:
        goal = self.require_goal(ref)
        allowed = {
            "title",
            "objective",
            "level",
            "status",
            "topic",
            "priority",
            "target_date",
            "success_criteria",
            "settings",
            "planned_by",
        }
        changes: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "level" and value not in LEVELS:
                raise ValidationError(f"level must be one of {', '.join(LEVELS)}")
            if key == "status":
                if value not in GOAL_STATUSES:
                    raise ValidationError(
                        f"status must be one of {', '.join(GOAL_STATUSES)}"
                    )
                if value == "completed":
                    changes["completed_at"] = iso_now()
                elif goal.status == "completed":
                    changes["completed_at"] = None
            if key == "priority":
                if not 0 <= int(value) <= 9:
                    raise ValidationError("priority must be between 0 and 9")
                value = int(value)
            if key == "success_criteria":
                value = [
                    str(item).strip() for item in (value or []) if str(item).strip()
                ]
            changes[key] = (
                json_text(value) if isinstance(value, (list, dict)) else value
            )
        if not changes:
            return goal
        changes["updated_at"] = iso_now()
        self._write("learning.goal_update", {"id": goal.id, "fields": changes})
        return self.get_goal(goal.id)

    def complete_goal(
        self, ref: str, *, confirmed_by: str = "user:cli", note: str = ""
    ) -> LearningGoal:
        """Close a goal against its criteria - explicitly, never as a side effect."""
        goal = self.require_goal(ref)
        if goal.status in TERMINAL_GOALS:
            raise ConflictError(f"goal {goal.id} is already {goal.status}")
        settings = dict(goal.settings)
        settings["completed_by"] = confirmed_by
        settings["completion_note"] = note.strip() or None
        return self.update_goal(goal.id, status="completed", settings=settings)

    def delete_goal(self, ref: str) -> dict[str, Any]:
        goal = self.require_goal(ref)
        return self._write("learning.delete", {"id": goal.id})
