"""The learning tutor: a plan, a hint ladder, a grade, and a schedule.

Learning Mode is where an AI tutor is most tempted to lie. "Great job, you understand it
now" costs nothing to say and is unfalsifiable. So the service is built around four refusals:

**It will not grade what it cannot check.** With an ``expected`` answer, grading is a
normalised string comparison and the record says ``graded_by = "exact"``. Without one, the
learner rates themselves 1-5 and the record says ``graded_by = "self"``. There is no third
path where the app implies it judged the answer.

**It will not help before you have tried.** ``learning.try_first`` is on by default: a hint
request for an item with no attempts is refused, with the reason and the next command. Hints
are ordered and revealed one at a time, so "show me hint 4 of 5" is possible but "show me
everything" is not.

**It will not pretend a schedule is magic.** After every attempt the interval, the ease, the
streak, the next due date and the resulting status are stored *and* returned, so the learner
can see exactly why an item comes back tomorrow rather than in three weeks.

**It will not finish a goal for you.** ``learning report`` and the review queue are progress;
completion is ``goal complete``, an explicit act against criteria the learner wrote.

Without a model the planner proposes *checkpoints of your own goal* (and says so). With a
model it asks for items in JSON, validates every field, and falls back to the checkpoints with
the reason attached - the same rule as Researcher Mode's plan.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Sequence

from archx_agent.helpers.exceptions import ArchxError, ConflictError, NotFoundError, ValidationError
from archx_agent.helpers.timeutil import iso_from_ts, iso_now, parse_iso
from archx_agent.managers.learning import (
    DEFAULT_MASTERY_STREAK,
    LearningGoal,
    LearningItem,
    LearningSession,
    due_in,
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


class LearningService:
    """Sessions, hints, grades and schedules. The manager owns the rows."""

    def __init__(self, workspace) -> None:
        self.ws = workspace
        self.manager = workspace.learning

    # -- config ---------------------------------------------------------
    def _cfg(self, key: str, default: Any) -> Any:
        try:
            return self.ws.config.get(key)
        except Exception:  # noqa: BLE001
            return default

    # -- choosing what to study -----------------------------------------
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

    # -- hints ----------------------------------------------------------
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

    # -- answering ------------------------------------------------------
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

    # -- sessions -------------------------------------------------------
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

    # -- planning -------------------------------------------------------
    def plan(
        self,
        goal_ref: str,
        *,
        use_model: bool = True,
        max_items: int | None = None,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        goal = self.manager.require_goal(goal_ref)
        cap = int(max_items or self._cfg("learning.max_plan_items", 8))
        items: list[dict[str, Any]] = []
        planned_by = "rules"
        why = (
            "no model was used, so these are checkpoints of your own goal - confirm, edit or "
            "delete them before you trust them as a curriculum"
        )
        if use_model:
            proposed, failure = self._model_plan(goal, cap, model_id=model_id)
            if proposed:
                items = proposed
                planned_by = "model"
                why = "a model proposed these from your goal; every field was validated"
            else:
                why = f"the model plan was unusable ({failure}); rule checkpoints were used instead"
        if not items:
            items = self._rule_plan(goal, cap)
        created = []
        for candidate in items[:cap]:
            created.append(
                self.manager.add_item(
                    goal.id,
                    candidate["prompt"],
                    expected=candidate.get("expected"),
                    hints=candidate.get("hints") or (),
                    explanation=candidate.get("explanation"),
                    subtopic=candidate.get("subtopic"),
                    source=planned_by,
                ).to_dict()
            )
        self.manager.update_goal(goal.id, planned_by=planned_by)
        return {
            "goal": self.manager.get_goal(goal.id).to_dict(),
            "items": created,
            "planned_by": planned_by,
            "why": why,
        }

    def _rule_plan(self, goal: LearningGoal, cap: int) -> list[dict[str, Any]]:
        """Checkpoints derived from the goal's own words - never invented facts."""
        pieces: list[str] = []
        for criteria in goal.success_criteria:
            pieces.append(f"Can you show this: {criteria.rstrip('.')}?")
        for chunk in re.split(r"[;\n]|,\s+(?=[a-z])", goal.objective):
            chunk = chunk.strip(" .")
            if len(chunk) >= 8:
                pieces.append(f"Explain in your own words: {chunk}")
        if not pieces:
            pieces = [
                f"What does {goal.topic or goal.title} mean, in your own words?",
                f"Which problem does {goal.topic or goal.title} solve, and what did people do before it?",
                f"Where would you apply {goal.topic or goal.title} in your own work?",
            ]
        seen: set[str] = set()
        planned: list[dict[str, Any]] = []
        for prompt in pieces:
            key = prompt.lower()
            if key in seen:
                continue
            seen.add(key)
            planned.append(
                {
                    "prompt": prompt,
                    "expected": None,
                    "hints": [],
                    "explanation": None,
                    "subtopic": goal.topic,
                }
            )
            if len(planned) >= cap:
                break
        return planned

    def _model_plan(
        self, goal: LearningGoal, cap: int, *, model_id: str | None
    ) -> tuple[list[dict[str, Any]], str]:
        prompt = textwrap.dedent(
            f"""
            Propose at most {cap} study items for this learning goal.
            Return ONLY a JSON array. Each element is an object with:
              "prompt": the question or task the learner must answer (a string),
              "expected": a short expected answer, or null if it cannot be checked,
              "hints": up to three strings, ordered from a nudge to nearly the answer,
              "explanation": one or two sentences shown after the attempt.

            Goal: {goal.title}
            Objective: {goal.objective}
            Level: {goal.level}
            Success criteria: {"; ".join(goal.success_criteria) or "not specified"}
            """
        ).strip()
        try:
            reply = self.ws.chat.send(
                prompt,
                model_id=model_id,
                system_prompt=(
                    "You design short, checkable study items. You return JSON and nothing else. "
                    "You never invent facts about the learner."
                ),
            )
        except Exception as exc:  # noqa: BLE001 - a failed plan must not fail the goal
            return [], f"{type(exc).__name__}: {exc}"[:200]
        return parse_plan_json(reply.text or ""), "the model did not return usable JSON"

    # -- reporting ------------------------------------------------------
    def report(self, goal_ref: str) -> str:
        goal = self.manager.require_goal(goal_ref)
        items = self.manager.items(goal.id)
        stats = self.manager.stats(goal.id)
        due = self.manager.due_items(goal.id)
        sessions = self.manager.sessions(goal.id, limit=10)
        attempts = self.manager.attempts(goal=goal.id, limit=10)
        lines = [
            f"# Learning: {goal.title}",
            "",
            f"- goal `{goal.id}` - status **{goal.status}** - level **{goal.level}**"
            + (f" - topic **{goal.topic}**" if goal.topic else ""),
            f"- objective: {goal.objective}",
            f"- items: {stats['items']} ({', '.join(f'{k} {v}' for k, v in stats['by_status'].items()) or 'none'})",
            f"- due now: {len(due)} - attempts: {stats['attempts']} - correct: {stats['correct']}"
            + (f" ({stats['accuracy']:.0%})" if stats["accuracy"] is not None else ""),
        ]
        if goal.success_criteria:
            lines += ["", "## Success criteria", ""]
            lines += [f"- {criterion}" for criterion in goal.success_criteria]
        lines += ["", "## What is scheduled next", ""]
        if due:
            for item in due[:10]:
                lines.append(
                    f"- {item.prompt} - **due now**"
                    + (f" (streak {item.streak}, interval {item.interval_days:g}d)"
                       if item.attempts else " (new)")
                )
        elif stats["items"]:
            upcoming = sorted(
                (item for item in items if item.due_at and item.status != "mastered"),
                key=lambda item: item.due_at or "",
            )
            for item in upcoming[:10]:
                lines.append(f"- {item.prompt} - next review {item.due_at}")
            if not upcoming:
                lines.append("- nothing scheduled: every item is mastered")
        else:
            lines.append("- nothing planned yet: `learning plan` proposes checkpoints, or add items yourself")
        if sessions:
            lines += ["", "## Recent sessions", ""]
            for session in sessions[:5]:
                lines.append(
                    f"- `{session.id}` {session.mode} {session.status} - "
                    f"{session.items_attempted} answered, {session.items_correct} correct"
                    + (f" - {session.summary}" if session.summary else "")
                )
        if attempts:
            lines += ["", "## Last attempts", ""]
            for attempt in attempts[:5]:
                mark = "correct" if attempt.correct else "not yet"
                lines.append(
                    f"- {attempt.created_at} - {mark} ({attempt.graded_by})"
                    + (f" - {attempt.feedback}" if attempt.feedback else "")
                )
        lines += [
            "",
            "## How this record is graded",
            "",
            "- answers are checked against the item's expected answer (`graded_by = exact`),",
            "- or the learner rates themselves (`graded_by = self`) - Archx did not check those.",
            "- a goal is completed by you, against your criteria; this report never does it for you.",
        ]
        return "\n".join(lines) + "\n"

    def write_report(self, goal_ref: str, path: str | None = None) -> str:
        goal = self.manager.require_goal(goal_ref)
        text = self.report(goal.id)
        if path is None:
            folder = Path(str(self.ws.config.get("paths.artifacts") or self.ws.config.home))
            folder.mkdir(parents=True, exist_ok=True)
            path = str(folder / f"learning-{goal.id}.md")
        target = Path(path)
        if target.parent and not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        if self.ws.tasks is not None:
            goal_row = self.manager.get_goal(goal.id)
            if goal_row.task_id:
                try:
                    self.ws.tasks.attach_artifact(
                        goal_row.task_id, "report", str(target), description="learning progress report"
                    )
                except Exception:  # noqa: BLE001 - the file is the deliverable
                    pass
        return str(target)


# --------------------------------------------------------------------------
# plan parsing (shared with tests, so the rules are visible)
# --------------------------------------------------------------------------
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


__all__ = [
    "Grade",
    "HintBeforeAttempt",
    "LearningService",
    "NothingToStudy",
    "grade_answer",
    "normalise",
    "parse_plan_json",
]
