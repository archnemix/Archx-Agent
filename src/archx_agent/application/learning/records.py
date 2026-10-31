"""LearningService records, constants and pure validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from archx_agent.helpers.exceptions import ArchxError, ValidationError
from archx_agent.managers.learning import (
    LearningItem,
)

class HintBeforeAttempt(ArchxError):
    """The hint ladder was asked for help the learner has not earned yet."""

    def __init__(self, message: str, *, item_id: str, hints: int) -> None:
        super().__init__(message)
        self.message = message
        self.item_id = item_id
        self.hints = hints

class NothingToStudy(ArchxError):
    """The goal has nothing new and nothing due - which is a result, not a failure."""

    def __init__(self, message: str, *, goal_id: str) -> None:
        super().__init__(message)
        self.message = message
        self.goal_id = goal_id

@dataclass
class Grade:
    correct: bool
    graded_by: str
    feedback: str
    expected: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "correct": self.correct,
            "graded_by": self.graded_by,
            "feedback": self.feedback,
            "expected": self.expected,
        }

def normalise(text: str) -> str:
    """Case-folded, punctuation-insensitive, whitespace-collapsed comparison form."""
    cleaned = "".join(char if (char.isalnum() or char.isspace()) else " " for char in (text or "").lower())
    return " ".join(cleaned.split())

def grade_answer(item: LearningItem, answer: str, *, self_rating: int | None) -> Grade:
    """The only two ways an answer is graded here: a match, or the learner's own rating."""
    answer_text = (answer or "").strip()
    if not answer_text and self_rating is None:
        raise ValidationError("an answer needs text, a self-rating, or both")
    if item.expected:
        got = normalise(answer_text)
        want = normalise(item.expected)
        if got == want:
            return Grade(True, "exact", "matched your expected answer exactly.", item.expected)
        want_terms = [term for term in want.split() if len(term) >= 3]
        got_terms = set(got.split())
        if want_terms and all(term in got_terms for term in want_terms):
            return Grade(
                True, "exact",
                "matched every term of the expected answer (not the exact wording).",
                item.expected,
            )
        return Grade(
            False, "exact",
            f"not yet. The expected answer is: {item.expected}",
            item.expected,
        )
    if self_rating is None:
        raise ValidationError(
            "this item has no expected answer, so Archx cannot grade it. "
            "Rate yourself with --self-rate 1-5, or add an expected answer to the item."
        )
    rating = int(self_rating)
    if not 1 <= rating <= 5:
        raise ValidationError("a self-rating must be between 1 and 5")
    correct = rating >= 3
    return Grade(
        correct, "self",
        f"you rated this {rating}/5, so it counts as {'known' if correct else 'not yet known'} "
        "for the schedule. Archx did not check the answer.",
    )

def parse_plan_json(raw: str) -> list[dict[str, Any]]:
    """Accept only a JSON array of usable items; anything else is a failed plan."""
    text = (raw or "").strip()
    if not text:
        return []
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        import json

        data = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        prompt = str(entry.get("prompt") or entry.get("question") or "").strip()
        if len(prompt) < 5:
            continue
        expected = entry.get("expected")
        expected = str(expected).strip() if isinstance(expected, str) and expected.strip() else None
        raw_hints = entry.get("hints") or []
        hints = [str(hint).strip() for hint in raw_hints if str(hint).strip()][:3] if isinstance(raw_hints, list) else []
        explanation = entry.get("explanation")
        explanation = str(explanation).strip() if isinstance(explanation, str) and explanation.strip() else None
        items.append(
            {
                "prompt": prompt,
                "expected": expected,
                "hints": hints,
                "explanation": explanation,
                "subtopic": entry.get("subtopic") if isinstance(entry.get("subtopic"), str) else None,
            }
        )
    return items
