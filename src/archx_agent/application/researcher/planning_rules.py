"""Planning rules operations for evidence-based research."""

from __future__ import annotations

from typing import Any

from archx_agent.application.researcher.text import _subject


def _rules_plan(question: str, limit: int) -> list[dict[str, Any]]:
    """A deterministic plan, with the reason for each subquestion.

    The first subquestion is the user's own question, because a plan that never asks the
    thing you asked is a plan that answers something else. The rest are facets chosen by the
    shape of the question. Deliberately plain: it exists so research works without a model,
    and ``planned_by = 'rules'`` says where it came from.
    """
    core = " ".join((question or "").strip().rstrip("?.").split())
    subject = _subject(question)
    lowered = core.lower()
    if lowered.startswith(("should i", "is it better", "compare", "versus", "vs")):
        facets = [
            (f"What are the benefits of {subject}?", "benefits"),
            (f"What are the costs and risks of {subject}?", "costs"),
            ("What alternatives exist, and how do they compare?", "alternatives"),
        ]
    elif lowered.startswith(("how do", "how to", "how can", "how does")):
        facets = [
            (f"What is required to do this, and what are the steps?", "procedure"),
            (f"What commonly goes wrong with {subject}?", "failure modes"),
            (
                f"What alternatives or better approaches exist for {subject}?",
                "alternatives",
            ),
        ]
    elif lowered.startswith(("why ", "when ")):
        facets = [
            ("What causes this behaviour?", "causes"),
            (f"When is the opposite true, and what are the exceptions?", "exceptions"),
            (f"What evidence supports this explanation?", "evidence"),
        ]
    elif lowered.startswith(("what ", "who ", "define", "explain", "describe")):
        facets = [
            (f"What are the limits, risks or trade-offs of {subject}?", "limits"),
            (
                f"What evidence or examples support the answer about {subject}?",
                "evidence",
            ),
            (f"What is uncertain or disputed about {subject}?", "gaps"),
        ]
    else:
        facets = [
            (f"What is already known about {subject}?", "background"),
            (f"What evidence supports the main claims about {subject}?", "evidence"),
            (f"What is uncertain, disputed or missing about {subject}?", "gaps"),
        ]
    plan = [
        {
            "question": f"{core}?",
            "why": "rule: the question you asked",
            "origin": "rules",
        }
    ]
    for text, reason in facets:
        plan.append({"question": text, "why": f"rule: {reason}", "origin": "rules"})
        if len(plan) >= max(1, int(limit)):
            break
    return plan[: max(1, int(limit))]
