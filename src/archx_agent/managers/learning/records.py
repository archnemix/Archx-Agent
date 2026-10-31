"""Record types and row conversion for learning records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.learning.constants import TERMINAL_GOALS
from archx_agent.managers.learning.formatting import _json


@dataclass
class LearningGoal:
    id: str
    title: str
    objective: str
    status: str
    created_at: str
    updated_at: str
    level: str = "beginner"
    topic: str | None = None
    success_criteria: list[str] = field(default_factory=list)
    priority: int = 5
    target_date: str | None = None
    task_id: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    completed_at: str | None = None
    planned_by: str = "user"
    source: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "objective": self.objective,
            "status": self.status,
            "level": self.level,
            "topic": self.topic,
            "success_criteria": list(self.success_criteria),
            "priority": self.priority,
            "target_date": self.target_date,
            "task_id": self.task_id,
            "settings": dict(self.settings),
            "completed_at": self.completed_at,
            "planned_by": self.planned_by,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "terminal": self.status in TERMINAL_GOALS,
        }


@dataclass
class LearningItem:
    id: str
    goal_id: str
    prompt: str
    position: int
    status: str
    updated_at: str
    topic: str | None = None
    subtopic: str | None = None
    expected: str | None = None
    hints: list[str] = field(default_factory=list)
    explanation: str | None = None
    ease: float = 2.5
    interval_days: float = 0.0
    streak: int = 0
    lapses: int = 0
    attempts: int = 0
    correct_count: int = 0
    best_score: float | None = None
    due_at: str | None = None
    last_reviewed_at: str | None = None
    created_at: str | None = None
    source: str = "user"

    def is_due(self, at: str | None = None) -> bool:
        if not self.due_at:
            return self.status == "new"
        return self.due_at <= (at or iso_now())

    @property
    def due(self) -> bool:
        """Whether this item is due now - the same answer ``to_dict()`` publishes."""
        return self.is_due()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "prompt": self.prompt,
            "position": self.position,
            "status": self.status,
            "topic": self.topic,
            "subtopic": self.subtopic,
            "expected": self.expected,
            "hints": list(self.hints),
            "hint_count": len(self.hints),
            "explanation": self.explanation,
            "ease": round(float(self.ease or 0.0), 3),
            "interval_days": round(float(self.interval_days or 0.0), 3),
            "streak": int(self.streak or 0),
            "lapses": int(self.lapses or 0),
            "attempts": int(self.attempts or 0),
            "correct": int(self.correct_count or 0),
            "accuracy": round(self.correct_count / self.attempts, 3)
            if self.attempts
            else None,
            "best_score": self.best_score,
            "due_at": self.due_at,
            "last_reviewed_at": self.last_reviewed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "due": self.is_due(),
        }


@dataclass
class LearningSession:
    id: str
    goal_id: str
    mode: str
    status: str
    started_at: str
    created_at: str
    ended_at: str | None = None
    task_id: str | None = None
    items_attempted: int = 0
    items_correct: int = 0
    hints_used: int = 0
    graded_by: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "mode": self.mode,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "items_attempted": self.items_attempted,
            "items_correct": self.items_correct,
            "hints_used": self.hints_used,
            "graded_by": self.graded_by,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class LearningAttempt:
    id: int
    goal_id: str
    item_id: str
    correct: bool
    graded_by: str
    created_at: str
    session_id: str | None = None
    answer: str | None = None
    self_rating: int | None = None
    hints_used: int = 0
    feedback: str | None = None
    interval_days: float | None = None
    due_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "goal_id": self.goal_id,
            "item_id": self.item_id,
            "answer": self.answer,
            "correct": self.correct,
            "graded_by": self.graded_by,
            "self_rating": self.self_rating,
            "hints_used": self.hints_used,
            "feedback": self.feedback,
            "interval_days": self.interval_days,
            "due_at": self.due_at,
            "created_at": self.created_at,
        }


def _goal_from_row(row: Any) -> LearningGoal:
    return LearningGoal(
        id=row["id"],
        title=row["title"],
        objective=row["objective"] or "",
        status=row["status"] or "active",
        created_at=row["created_at"],
        updated_at=row["updated_at"] or row["created_at"],
        level=row["level"] or "beginner",
        topic=row["topic"],
        success_criteria=_json(row["success_criteria"], []),
        priority=int(row["priority"] or 5),
        target_date=row["target_date"],
        task_id=row["task_id"],
        settings=_json(row["settings"], {}),
        completed_at=row["completed_at"],
        planned_by=row["planned_by"] or "user",
        source=row["source"] or "user",
    )


def _item_from_row(row: Any) -> LearningItem:
    return LearningItem(
        id=row["id"],
        goal_id=row["goal_id"],
        prompt=row["topic"],
        position=int(row["position"] or 0),
        status=row["status"] or "new",
        updated_at=row["updated_at"] or "",
        subtopic=row["subtopic"],
        expected=row["expected"],
        hints=_json(row["hints"], []),
        explanation=row["explanation"],
        ease=float(row["ease"] if row["ease"] is not None else 2.5),
        interval_days=float(row["interval_days"] or 0.0),
        streak=int(row["streak"] or 0),
        lapses=int(row["lapses"] or 0),
        attempts=int(row["attempts"] or 0),
        correct_count=int(row["correct_count"] or 0),
        best_score=row["best_score"],
        due_at=row["due_at"],
        last_reviewed_at=row["last_reviewed_at"],
        created_at=row["created_at"],
        source=row["source"] or "user",
    )


def _session_from_row(row: Any) -> LearningSession:
    return LearningSession(
        id=row["id"],
        goal_id=row["goal_id"],
        mode=row["mode"],
        status=row["status"],
        started_at=row["started_at"],
        created_at=row["created_at"],
        ended_at=row["ended_at"],
        task_id=row["task_id"],
        items_attempted=int(row["items_attempted"] or 0),
        items_correct=int(row["items_correct"] or 0),
        hints_used=int(row["hints_used"] or 0),
        graded_by=row["graded_by"],
        summary=row["summary"],
    )


def _attempt_from_row(row: Any) -> LearningAttempt:
    return LearningAttempt(
        id=int(row["id"]),
        goal_id=row["goal_id"],
        item_id=row["item_id"],
        correct=bool(row["correct"]),
        graded_by=row["graded_by"],
        created_at=row["created_at"],
        session_id=row["session_id"],
        answer=row["answer"],
        self_rating=row["self_rating"],
        hints_used=int(row["hints_used"] or 0),
        feedback=row["feedback"],
        interval_days=row["interval_days"],
        due_at=row["due_at"],
    )
