"""LearningService: planning operations."""

from __future__ import annotations

import re
import textwrap
from typing import Any
from archx_agent.managers.learning import (
    LearningGoal,
)

from .records import parse_plan_json

class LearningServicePlanningMixin:
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
