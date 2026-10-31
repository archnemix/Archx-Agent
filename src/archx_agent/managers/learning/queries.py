"""Read and search operations for learning records."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.learning.records import LearningGoal, _item_from_row


class LearningManagerQueriesMixin:
    """Queries responsibility for LearningManager."""

    def stats(self, goal_ref: str | None = None) -> dict[str, Any]:
        if goal_ref:
            goal = self.require_goal(goal_ref)
            return self._goal_stats(goal)
        goals = self.list_goals(limit=500)
        totals = {
            "goals": len(goals),
            "items": 0,
            "due": 0,
            "attempts": 0,
            "correct": 0,
            "mastered": 0,
            "sessions": 0,
        }
        by_status: dict[str, int] = {}
        for goal in goals:
            stats = self._goal_stats(goal)
            by_status[goal.status] = by_status.get(goal.status, 0) + 1
            for key in ("items", "due", "attempts", "correct", "mastered", "sessions"):
                totals[key] += int(stats[key])
        totals["by_status"] = by_status
        totals["accuracy"] = (
            round(totals["correct"] / totals["attempts"], 3)
            if totals["attempts"]
            else None
        )
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
                    "SELECT COUNT(*) FROM learning_sessions WHERE goal_id = ?",
                    (goal.id,),
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
        for row in self.store.query(
            "SELECT * FROM learning_lessons ORDER BY position LIMIT 2000"
        ):
            item = _item_from_row(row)
            haystack = " ".join(
                [item.prompt, item.expected or "", " ".join(item.hints)]
            ).lower()
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
