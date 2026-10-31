"""Items operations for learning records."""

from __future__ import annotations

from typing import Any, Iterable

from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.learning.constants import TERMINAL_GOALS, ITEM_STATUSES
from archx_agent.managers.learning.records import LearningItem, _item_from_row


class LearningManagerItemsMixin:
    """Items responsibility for LearningManager."""

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
            raise ValidationError(
                "an item needs a question or task of at least three characters"
            )
        if goal.status in TERMINAL_GOALS:
            raise ConflictError(
                f"goal {goal.id} is {goal.status}; reopen it before adding items"
            )
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
        rows = self.store.query(
            "SELECT * FROM learning_lessons WHERE id = ?", (item_ref,)
        )
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
            "SELECT * FROM learning_lessons WHERE goal_id = ?"
            + clause
            + " ORDER BY position ASC, created_at ASC",
            params,
        )
        return [_item_from_row(row) for row in rows]

    def due_items(
        self, goal_ref: str, *, at: str | None = None, limit: int | None = None
    ) -> list[LearningItem]:
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
            "topic",
            "subtopic",
            "position",
            "status",
            "expected",
            "hints",
            "explanation",
            "best_score",
            "ease",
            "interval_days",
            "streak",
            "lapses",
            "attempts",
            "correct_count",
            "due_at",
            "last_reviewed_at",
        }
        changes: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "status" and value not in ITEM_STATUSES:
                raise ValidationError(
                    f"status must be one of {', '.join(ITEM_STATUSES)}"
                )
            if key == "hints":
                cleaned = [str(hint).strip() for hint in value if str(hint).strip()]
                max_hints = int(self._cfg("learning.max_hints", 5))
                if len(cleaned) > max_hints:
                    raise ValidationError(
                        f"at most {max_hints} hints per item (learning.max_hints); a hint"
                        " ladder longer than that is the answer"
                    )
                value = cleaned
            changes[key] = (
                json_text(value) if isinstance(value, (list, dict)) else value
            )
        if not changes:
            return item
        changes["updated_at"] = iso_now()
        self._write("learning.item_update", {"id": item.id, "fields": changes})
        return self.get_item(item.id)

    def delete_item(self, item_ref: str) -> dict[str, Any]:
        item = self.require_item(item_ref)
        return self._write("learning.delete", {"kind": "item", "id": item.id})
