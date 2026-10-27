"""Learning goals, reviewable items, sessions and attempts.

Learning Mode is not "a chat with the word 'lesson' in it". It is four records that make
progress checkable:

``goal``
    what is being learned, why, and what would count as finished. A goal is never marked
    complete because time passed - the user closes it, against criteria they wrote.
``item``
    one thing worth being able to recall or do, with an optional expected answer, an ordered
    list of hints and an explanation. Each item carries its own *schedule*: interval, ease,
    streak, lapses and due date, all stored so a review can be explained rather than guessed.
``session``
    a sitting: which goal, which mode (explain / practice / review), what was attempted and by
    whom it was graded. A session is also a task, like every other piece of work in the app.
``attempt``
    one answer, the grade, who graded it, how many hints were used, and the schedule change it
    caused. This is the row that makes "you are improving" a claim with evidence.

The tables were reserved in v8; v19 added the columns and the two child tables. The rule is
unchanged: one store, one writer, journaled writes, and no derived truth that is not stored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Iterable, Sequence

from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_from_ts, iso_now, new_id, parse_iso

from .base import BaseManager

LEARNING_TABLES = ("learning_goals", "learning_lessons", "learning_sessions", "learning_attempts")

LEVELS = ("beginner", "intermediate", "advanced")
GOAL_STATUSES = ("active", "paused", "completed", "abandoned")
TERMINAL_GOALS = frozenset({"completed", "abandoned"})
ITEM_STATUSES = ("new", "learning", "review", "mastered")
SESSION_MODES = ("explain", "practice", "review")
SESSION_STATUSES = ("open", "closed")
GRADERS = ("exact", "self", "model")
PLANNERS = ("model", "rules", "user")
#: a correct answer this many times in a row, with a long enough interval, is "mastered"
DEFAULT_MASTERY_STREAK = 4


def _json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _norm(text: str) -> str:
    """Whitespace-collapsed, case-folded, punctuation-insensitive comparison form."""
    out = []
    for char in (text or "").strip().lower():
        if char.isalnum() or char.isspace():
            out.append(char)
        else:
            out.append(" ")
    return " ".join("".join(out).split())


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
            "accuracy": round(self.correct_count / self.attempts, 3) if self.attempts else None,
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


class LearningManager(BaseManager):
    """Rows for goals, items, sessions and attempts. Scheduling lives in the service."""

    tables = LEARNING_TABLES

    def __init__(self, store, coordinator, *, events=None, config=None) -> None:
        self.config = config
        super().__init__(store, coordinator, events=events)

    def _cfg(self, key: str, default: Any) -> Any:
        config = getattr(self, "config", None)
        if config is None:
            return default
        try:
            return config.get(key)
        except Exception:  # noqa: BLE001 - a missing key must not break a read
            return default

    def register_handlers(self) -> None:
        self.coordinator.register("learning.goal", self._apply_goal)
        self.coordinator.register("learning.goal_update", self._apply_goal_update)
        self.coordinator.register("learning.item", self._apply_item)
        self.coordinator.register("learning.item_update", self._apply_item_update)
        self.coordinator.register("learning.session", self._apply_session)
        self.coordinator.register("learning.session_update", self._apply_session_update)
        self.coordinator.register("learning.attempt", self._apply_attempt)
        self.coordinator.register("learning.delete", self._apply_delete)

    # -- write handlers ---------------------------------------------------
    def _apply_goal(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        goal = payload["goal"]
        tx.execute(
            "INSERT INTO learning_goals(id, title, objective, level, status, path, created_at,"
            " updated_at, topic, success_criteria, priority, target_date, task_id, settings,"
            " completed_at, planned_by, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                goal["id"], goal["title"], goal["objective"], goal.get("level") or "beginner",
                goal["status"], goal.get("path"), goal["created_at"], goal["updated_at"],
                goal.get("topic"), json_text(goal.get("success_criteria") or []),
                int(goal.get("priority") or 5), goal.get("target_date"), goal.get("task_id"),
                json_text(goal.get("settings") or {}), goal.get("completed_at"),
                goal.get("planned_by") or "user", goal.get("source") or "user",
            ),
        )
        return {"id": goal["id"]}

    def _apply_goal_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = payload["fields"]
        if not fields:
            return {"id": payload["id"], "updated": 0}
        columns = ", ".join(f"{name} = ?" for name in fields)
        tx.execute(
            f"UPDATE learning_goals SET {columns} WHERE id = ?",
            (*fields.values(), payload["id"]),
        )
        return {"id": payload["id"], "updated": 1}

    def _apply_item(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        item = payload["item"]
        tx.execute(
            "INSERT INTO learning_lessons(id, goal_id, topic, subtopic, position, status,"
            " attempts, best_score, content, exercise, updated_at, expected, hints,"
            " explanation, ease, interval_days, streak, lapses, correct_count, due_at,"
            " last_reviewed_at, created_at, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item["id"], item["goal_id"], item["prompt"], item.get("subtopic"),
                int(item["position"]), item["status"], 0, None, None, None,
                item["updated_at"], item.get("expected"), json_text(item.get("hints") or []),
                item.get("explanation"), float(item.get("ease") or 2.5),
                float(item.get("interval_days") or 0.0), 0, 0, 0, item.get("due_at"),
                None, item.get("created_at") or item["updated_at"], item.get("source") or "user",
            ),
        )
        return {"id": item["id"]}

    def _apply_item_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = payload["fields"]
        if not fields:
            return {"id": payload["id"], "updated": 0}
        columns = ", ".join(f"{name} = ?" for name in fields)
        tx.execute(
            f"UPDATE learning_lessons SET {columns} WHERE id = ?",
            (*fields.values(), payload["id"]),
        )
        return {"id": payload["id"], "updated": 1}

    def _apply_session(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        session = payload["session"]
        tx.execute(
            "INSERT INTO learning_sessions(id, goal_id, task_id, mode, status, started_at,"
            " ended_at, items_attempted, items_correct, hints_used, graded_by, summary,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                session["id"], session["goal_id"], session.get("task_id"), session["mode"],
                session["status"], session["started_at"], session.get("ended_at"), 0, 0, 0,
                None, None, session["created_at"],
            ),
        )
        return {"id": session["id"]}

    def _apply_session_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = payload["fields"]
        if not fields:
            return {"id": payload["id"], "updated": 0}
        columns = ", ".join(f"{name} = ?" for name in fields)
        tx.execute(
            f"UPDATE learning_sessions SET {columns} WHERE id = ?",
            (*fields.values(), payload["id"]),
        )
        return {"id": payload["id"]}

    def _apply_attempt(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        attempt = payload["attempt"]
        tx.execute(
            "INSERT INTO learning_attempts(session_id, goal_id, item_id, answer, correct,"
            " graded_by, self_rating, hints_used, feedback, interval_days, due_at, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                attempt.get("session_id"), attempt["goal_id"], attempt["item_id"],
                attempt.get("answer"), 1 if attempt["correct"] else 0, attempt["graded_by"],
                attempt.get("self_rating"), int(attempt.get("hints_used") or 0),
                attempt.get("feedback"), attempt.get("interval_days"), attempt.get("due_at"),
                attempt["created_at"],
            ),
        )
        row = tx.query("SELECT last_insert_rowid() AS id")
        return {"id": int(row[0]["id"]) if row else None}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("kind") == "item":
            tx.execute("DELETE FROM learning_attempts WHERE item_id = ?", (payload["id"],))
            tx.execute("DELETE FROM learning_lessons WHERE id = ?", (payload["id"],))
            return {"id": payload["id"], "deleted": 1}
        goal_id = payload["id"]
        tx.execute(
            "DELETE FROM learning_attempts WHERE goal_id = ?", (goal_id,)
        )
        tx.execute("DELETE FROM learning_sessions WHERE goal_id = ?", (goal_id,))
        tx.execute("DELETE FROM learning_lessons WHERE goal_id = ?", (goal_id,))
        tx.execute("DELETE FROM learning_goals WHERE id = ?", (goal_id,))
        return {"id": goal_id, "deleted": 1}

    # -- goals ------------------------------------------------------------
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
            raise ValidationError("a learning goal needs a title of at least three characters")
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
            self.store.scalar("SELECT COUNT(*) FROM learning_goals WHERE status = 'active'") or 0
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

    def list_goals(self, *, status: str | None = None, limit: int = 20) -> list[LearningGoal]:
        if status is not None and status not in GOAL_STATUSES:
            raise ValidationError(f"unknown goal status {status!r}")
        clause = " WHERE status = ?" if status else ""
        params: tuple[Any, ...] = (status, max(1, limit)) if status else (max(1, limit),)
        rows = self.store.query(
            "SELECT * FROM learning_goals" + clause
            + " ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,"
            " priority DESC, updated_at DESC LIMIT ?",
            params,
        )
        return [_goal_from_row(row) for row in rows]

    def update_goal(self, ref: str, **fields: Any) -> LearningGoal:
        goal = self.require_goal(ref)
        allowed = {
            "title", "objective", "level", "status", "topic", "priority",
            "target_date", "success_criteria", "settings", "planned_by",
        }
        changes: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "level" and value not in LEVELS:
                raise ValidationError(f"level must be one of {', '.join(LEVELS)}")
            if key == "status":
                if value not in GOAL_STATUSES:
                    raise ValidationError(f"status must be one of {', '.join(GOAL_STATUSES)}")
                if value == "completed":
                    changes["completed_at"] = iso_now()
                elif goal.status == "completed":
                    changes["completed_at"] = None
            if key == "priority":
                if not 0 <= int(value) <= 9:
                    raise ValidationError("priority must be between 0 and 9")
                value = int(value)
            if key == "success_criteria":
                value = [str(item).strip() for item in (value or []) if str(item).strip()]
            changes[key] = json_text(value) if isinstance(value, (list, dict)) else value
        if not changes:
            return goal
        changes["updated_at"] = iso_now()
        self._write("learning.goal_update", {"id": goal.id, "fields": changes})
        return self.get_goal(goal.id)

    def complete_goal(self, ref: str, *, confirmed_by: str = "user:cli", note: str = "") -> LearningGoal:
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

    # -- items ------------------------------------------------------------
    def add_item(
        self,
        goal_ref: str,
        prompt: str,
        *,
        expected: str | None = None,
        hints: Iterable[str] = (),
        explanation: str | None = None,
        subtopic: str | None = None,
        position: int | None = None,
        source: str = "user",
    ) -> LearningItem:
        goal = self.require_goal(goal_ref)
        prompt = (prompt or "").strip()
        if len(prompt) < 3:
            raise ValidationError("an item needs a question or task of at least three characters")
        if goal.status in TERMINAL_GOALS:
            raise ConflictError(f"goal {goal.id} is {goal.status}; reopen it before adding items")
        clean_hints = [str(hint).strip() for hint in hints if str(hint).strip()]
        max_hints = int(self._cfg("learning.max_hints", 5))
        if len(clean_hints) > max_hints:
            raise ValidationError(
                f"at most {max_hints} hints per item (learning.max_hints); a hint ladder longer"
                " than that is the answer"
            )
        if position is None:
            position = int(
                self.store.scalar(
                    "SELECT COALESCE(MAX(position), 0) + 1 FROM learning_lessons WHERE goal_id = ?",
                    (goal.id,),
                )
                or 1
            )
        item = LearningItem(
            id=new_id("li_"),
            goal_id=goal.id,
            prompt=prompt,
            position=int(position),
            status="new",
            updated_at=iso_now(),
            subtopic=subtopic,
            expected=(expected or "").strip() or None,
            hints=clean_hints,
            explanation=(explanation or "").strip() or None,
            ease=float(self._cfg("learning.start_ease", 2.5)),
            interval_days=0.0,
            due_at=None,
            created_at=iso_now(),
            source=source,
        )
        self._write("learning.item", {"item": item.to_dict()})
        return self.get_item(item.id)

    def get_item(self, item_ref: str) -> LearningItem:
        rows = self.store.query("SELECT * FROM learning_lessons WHERE id = ?", (item_ref,))
        if not rows:
            raise NotFoundError(f"no learning item {item_ref!r}")
        return _item_from_row(rows[0])

    def find_item(self, ref: str) -> LearningItem | None:
        rows = self.store.query("SELECT * FROM learning_lessons WHERE id = ?", (ref,))
        if rows:
            return _item_from_row(rows[0])
        rows = self.store.query(
            "SELECT * FROM learning_lessons WHERE id LIKE ? ORDER BY created_at DESC LIMIT 2",
            (ref + "%",),
        )
        if len(rows) > 1:
            raise ValidationError(f"{ref!r} matches more than one item; use the id")
        return _item_from_row(rows[0]) if rows else None

    def require_item(self, ref: str) -> LearningItem:
        item = self.find_item(ref)
        if item is None:
            raise NotFoundError(f"no learning item {ref!r}")
        return item

    def items(self, goal_ref: str, *, status: str | None = None) -> list[LearningItem]:
        goal = self.require_goal(goal_ref)
        if status is not None and status not in ITEM_STATUSES:
            raise ValidationError(f"unknown item status {status!r}")
        clause = " AND status = ?" if status else ""
        params: tuple[Any, ...] = (goal.id, status) if status else (goal.id,)
        rows = self.store.query(
            "SELECT * FROM learning_lessons WHERE goal_id = ?" + clause
            + " ORDER BY position ASC, created_at ASC",
            params,
        )
        return [_item_from_row(row) for row in rows]

    def due_items(self, goal_ref: str, *, at: str | None = None, limit: int | None = None) -> list[LearningItem]:
        goal = self.require_goal(goal_ref)
        moment = at or iso_now()
        rows = self.store.query(
            "SELECT * FROM learning_lessons WHERE goal_id = ? AND status != 'mastered'"
            " AND ((due_at IS NOT NULL AND due_at <= ?) OR due_at IS NULL)"
            # Something that was seen and has come due comes before something brand new:
            # review first, then new material. Ties fall back to the plan's own order.
            " ORDER BY (due_at IS NULL) ASC, due_at ASC, position ASC",
            (goal.id, moment),
        )
        items = [_item_from_row(row) for row in rows]
        if limit is not None:
            items = items[: max(0, int(limit))]
        return items

    def update_item(self, item_ref: str, **fields: Any) -> LearningItem:
        item = self.require_item(item_ref)
        allowed = {
            "topic", "subtopic", "position", "status", "expected", "hints", "explanation",
            "best_score", "ease", "interval_days", "streak", "lapses", "attempts",
            "correct_count", "due_at", "last_reviewed_at",
        }
        changes: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "status" and value not in ITEM_STATUSES:
                raise ValidationError(f"status must be one of {', '.join(ITEM_STATUSES)}")
            if key == "hints":
                cleaned = [str(hint).strip() for hint in value if str(hint).strip()]
                max_hints = int(self._cfg("learning.max_hints", 5))
                if len(cleaned) > max_hints:
                    raise ValidationError(
                        f"at most {max_hints} hints per item (learning.max_hints); a hint"
                        " ladder longer than that is the answer"
                    )
                value = cleaned
            changes[key] = json_text(value) if isinstance(value, (list, dict)) else value
        if not changes:
            return item
        changes["updated_at"] = iso_now()
        self._write("learning.item_update", {"id": item.id, "fields": changes})
        return self.get_item(item.id)

    def delete_item(self, item_ref: str) -> dict[str, Any]:
        item = self.require_item(item_ref)
        return self._write("learning.delete", {"kind": "item", "id": item.id})

    # -- sessions ---------------------------------------------------------
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
            raise ValidationError(f"status must be one of {', '.join(SESSION_STATUSES)}")
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
        rows = self.store.query("SELECT * FROM learning_sessions WHERE id = ?", (session_id,))
        if not rows:
            raise NotFoundError(f"no learning session {session_id!r}")
        return _session_from_row(rows[0])

    def sessions(self, goal_ref: str | None = None, *, limit: int = 20) -> list[LearningSession]:
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

    def attempts(self, *, item: str | None = None, goal: str | None = None,
                 session: str | None = None, limit: int = 50) -> list[LearningAttempt]:
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

    def close_session(self, session_id: str, *, summary: str | None = None) -> LearningSession:
        session = self.get_session(session_id)
        if session.status == "closed":
            return session
        self._write(
            "learning.session_update",
            {
                "id": session.id,
                "fields": {"status": "closed", "ended_at": iso_now(), "summary": summary},
            },
        )
        return self.get_session(session.id)

    # -- summary reads ----------------------------------------------------
    def stats(self, goal_ref: str | None = None) -> dict[str, Any]:
        if goal_ref:
            goal = self.require_goal(goal_ref)
            return self._goal_stats(goal)
        goals = self.list_goals(limit=500)
        totals = {"goals": len(goals), "items": 0, "due": 0, "attempts": 0, "correct": 0,
                  "mastered": 0, "sessions": 0}
        by_status: dict[str, int] = {}
        for goal in goals:
            stats = self._goal_stats(goal)
            by_status[goal.status] = by_status.get(goal.status, 0) + 1
            for key in ("items", "due", "attempts", "correct", "mastered", "sessions"):
                totals[key] += int(stats[key])
        totals["by_status"] = by_status
        totals["accuracy"] = round(totals["correct"] / totals["attempts"], 3) if totals["attempts"] else None
        return totals

    def _goal_stats(self, goal: LearningGoal) -> dict[str, Any]:
        items = self.items(goal.id)
        by_status: dict[str, int] = {}
        for item in items:
            by_status[item.status] = by_status.get(item.status, 0) + 1
        attempts = int(
            self.store.scalar(
                "SELECT COUNT(*) FROM learning_attempts WHERE goal_id = ?", (goal.id,)
            )
            or 0
        )
        correct = int(
            self.store.scalar(
                "SELECT COUNT(*) FROM learning_attempts WHERE goal_id = ? AND correct = 1",
                (goal.id,),
            )
            or 0
        )
        return {
            "goal_id": goal.id,
            "title": goal.title,
            "status": goal.status,
            "items": len(items),
            "by_status": by_status,
            "due": len(self.due_items(goal.id)),
            "mastered": by_status.get("mastered", 0),
            "attempts": attempts,
            "correct": correct,
            "accuracy": round(correct / attempts, 3) if attempts else None,
            "sessions": int(
                self.store.scalar(
                    "SELECT COUNT(*) FROM learning_sessions WHERE goal_id = ?", (goal.id,)
                )
                or 0
            ),
        }

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        terms = [word for word in (query or "").lower().split() if len(word) >= 2]
        if not terms:
            raise ValidationError("a learning search needs at least two characters")
        hits: list[dict[str, Any]] = []
        for goal in self.list_goals(limit=500):
            haystack = " ".join(
                [goal.title, goal.objective, " ".join(goal.success_criteria)]
            ).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                hits.append(
                    {
                        "kind": "goal",
                        "id": goal.id,
                        "title": goal.title,
                        "score": round(score / len(terms), 4),
                        "status": goal.status,
                    }
                )
        for row in self.store.query("SELECT * FROM learning_lessons ORDER BY position LIMIT 2000"):
            item = _item_from_row(row)
            haystack = " ".join([item.prompt, item.expected or "", " ".join(item.hints)]).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                hits.append(
                    {
                        "kind": "item",
                        "id": item.id,
                        "title": item.prompt,
                        "score": round(score / len(terms), 4),
                        "status": item.status,
                        "goal_id": item.goal_id,
                    }
                )
        hits.sort(key=lambda hit: (-hit["score"], hit["kind"], hit["title"].lower()))
        return hits[: max(1, limit)]

    def next_due_at(self, goal_ref: str) -> str | None:
        goal = self.require_goal(goal_ref)
        value = self.store.scalar(
            "SELECT MIN(due_at) FROM learning_lessons WHERE goal_id = ? AND status != 'mastered'"
            " AND due_at IS NOT NULL AND due_at > ?",
            (goal.id, iso_now()),
        )
        return str(value) if value else None


def due_in(days: float, *, start: str | None = None) -> str:
    """An ISO timestamp ``days`` from ``start`` (or now) - the schedule's own arithmetic."""
    moment = parse_iso(start) if start else parse_iso(iso_now())
    return iso_from_ts((moment + timedelta(days=days)).timestamp())


__all__ = [
    "GRADERS",
    "GOAL_STATUSES",
    "ITEM_STATUSES",
    "LEARNING_TABLES",
    "LEVELS",
    "LearningAttempt",
    "LearningGoal",
    "LearningItem",
    "LearningManager",
    "LearningSession",
    "PLANNERS",
    "SESSION_MODES",
    "SESSION_STATUSES",
    "TERMINAL_GOALS",
    "due_in",
]
