"""Transactional write handlers for learning records."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.jsonio import json_text


class LearningManagerWritesMixin:
    """Writes responsibility for LearningManager."""

    def register_handlers(self) -> None:
        self.coordinator.register("learning.goal", self._apply_goal)
        self.coordinator.register("learning.goal_update", self._apply_goal_update)
        self.coordinator.register("learning.item", self._apply_item)
        self.coordinator.register("learning.item_update", self._apply_item_update)
        self.coordinator.register("learning.session", self._apply_session)
        self.coordinator.register("learning.session_update", self._apply_session_update)
        self.coordinator.register("learning.attempt", self._apply_attempt)
        self.coordinator.register("learning.delete", self._apply_delete)

    def _apply_goal(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        goal = payload["goal"]
        tx.execute(
            "INSERT INTO learning_goals(id, title, objective, level, status, path, created_at,"
            " updated_at, topic, success_criteria, priority, target_date, task_id, settings,"
            " completed_at, planned_by, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                goal["id"],
                goal["title"],
                goal["objective"],
                goal.get("level") or "beginner",
                goal["status"],
                goal.get("path"),
                goal["created_at"],
                goal["updated_at"],
                goal.get("topic"),
                json_text(goal.get("success_criteria") or []),
                int(goal.get("priority") or 5),
                goal.get("target_date"),
                goal.get("task_id"),
                json_text(goal.get("settings") or {}),
                goal.get("completed_at"),
                goal.get("planned_by") or "user",
                goal.get("source") or "user",
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
                item["id"],
                item["goal_id"],
                item["prompt"],
                item.get("subtopic"),
                int(item["position"]),
                item["status"],
                0,
                None,
                None,
                None,
                item["updated_at"],
                item.get("expected"),
                json_text(item.get("hints") or []),
                item.get("explanation"),
                float(item.get("ease") or 2.5),
                float(item.get("interval_days") or 0.0),
                0,
                0,
                0,
                item.get("due_at"),
                None,
                item.get("created_at") or item["updated_at"],
                item.get("source") or "user",
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
                session["id"],
                session["goal_id"],
                session.get("task_id"),
                session["mode"],
                session["status"],
                session["started_at"],
                session.get("ended_at"),
                0,
                0,
                0,
                None,
                None,
                session["created_at"],
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
                attempt.get("session_id"),
                attempt["goal_id"],
                attempt["item_id"],
                attempt.get("answer"),
                1 if attempt["correct"] else 0,
                attempt["graded_by"],
                attempt.get("self_rating"),
                int(attempt.get("hints_used") or 0),
                attempt.get("feedback"),
                attempt.get("interval_days"),
                attempt.get("due_at"),
                attempt["created_at"],
            ),
        )
        row = tx.query("SELECT last_insert_rowid() AS id")
        return {"id": int(row[0]["id"]) if row else None}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("kind") == "item":
            tx.execute(
                "DELETE FROM learning_attempts WHERE item_id = ?", (payload["id"],)
            )
            tx.execute("DELETE FROM learning_lessons WHERE id = ?", (payload["id"],))
            return {"id": payload["id"], "deleted": 1}
        goal_id = payload["id"]
        tx.execute("DELETE FROM learning_attempts WHERE goal_id = ?", (goal_id,))
        tx.execute("DELETE FROM learning_sessions WHERE goal_id = ?", (goal_id,))
        tx.execute("DELETE FROM learning_lessons WHERE goal_id = ?", (goal_id,))
        tx.execute("DELETE FROM learning_goals WHERE id = ?", (goal_id,))
        return {"id": goal_id, "deleted": 1}
