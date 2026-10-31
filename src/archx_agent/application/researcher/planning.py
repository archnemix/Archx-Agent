"""Planning operations for evidence-based research."""

from __future__ import annotations

import textwrap
from typing import Any, Sequence

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ArchxError,
    ValidationError,
)
from archx_agent.application.researcher.text import _short, _clean
from archx_agent.application.researcher.parsing import _parse_plan
from archx_agent.application.researcher.planning_rules import _rules_plan


class ResearchRunnerPlanningMixin:
    """Planning responsibility for ResearchRunner."""

    def plan(
        self,
        question: str,
        *,
        max_subquestions: int | None = None,
        conversation_id: str | None = None,
        model_id: str | None = None,
        subquestions: Sequence[str] | None = None,
    ) -> tuple[list[dict[str, Any]], str, list[str], dict[str, Any]]:
        """Return ``(plan, planned_by, notes, meta)``. Never raises for a bad model reply."""
        limit = int(max_subquestions or self._cfg("research.max_subquestions", 8))
        limit = max(1, min(limit, 50))
        if subquestions:
            picked = [
                {
                    "question": _clean(item),
                    "why": "the user asked this",
                    "origin": "user",
                }
                for item in subquestions
                if _clean(item)
            ]
            if not picked:
                raise ValidationError(
                    "--subquestion needs at least one non-empty question"
                )
            return (
                picked[:limit],
                "user",
                [],
                {
                    "model_id": None,
                    "simulated": False,
                    "reason": "the user supplied the subquestions",
                },
            )
        notes: list[str] = []
        meta: dict[str, Any] = {"model_id": None, "simulated": False, "reason": ""}
        prompt = textwrap.dedent(
            f"""
            You are planning a research run. Break the question into at most {limit}
            subquestions that can each be answered from documents.

            Question: {question}

            Reply with JSON only, no prose, in exactly this shape:
            {{"subquestions": [{{"question": "...", "why": "..."}}]}}
            """
        ).strip()
        try:
            reply = self.ws.chat.send(
                prompt,
                conversation_id=conversation_id,
                model_id=model_id,
                system_prompt=(
                    "You produce research plans as JSON. You never invent sources. "
                    "If the question is unclear, plan subquestions that would clarify it."
                ),
            )
            meta["model_id"] = (reply.model or {}).get("id")
            meta["simulated"] = bool(reply.simulated)
            parsed = _parse_plan(reply.text, limit)
            if parsed:
                meta["reason"] = "a model returned a plan that validated"
                return parsed, "model", notes, meta
            notes.append(
                "the model's plan did not parse or validate, so a rule plan was used"
            )
            meta["reason"] = "the model reply was not a usable plan"
        except ApprovalRequiredError:
            raise
        except ArchxError as exc:
            notes.append(
                f"planning with a model failed ({_short(getattr(exc, 'message', exc))}); "
                "a rule plan was used"
            )
            meta["reason"] = "the model call failed"
        except Exception as exc:  # noqa: BLE001 - planning must not kill the run
            notes.append(f"planning with a model failed ({exc}); rule plan used")
            meta["reason"] = "the model call failed"
        plan = _rules_plan(question, limit)
        if not meta["reason"]:
            meta["reason"] = "no model was available, so the plan came from rules"
        return plan, "rules", notes, meta
