"""HTTP endpoints for learning. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.application.learning import HintBeforeAttempt, NothingToStudy


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class LearningRoutes:
    @route("GET", "/api/learning", "Learning goals with their progress.")
    def get_learning(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        goals = self.ws.learning.list_goals(limit=request.q_int("limit", 20))
        return {
            "goals": [
                {**goal.to_dict(), "stats": self.ws.learning.stats(goal.id)}
                for goal in goals
            ],
            "stats": self.ws.learning.stats(),
        }

    @route("POST", "/api/learning/goals", "Create a learning goal.")
    def post_learning_goal(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        goal = self.ws.learning.create_goal(
            request.text("title", required=True) or "",
            objective=request.payload().get("objective") or None,
            topic=request.payload().get("topic") or None,
            level=str(request.payload().get("level") or "beginner"),
            success_criteria=request.payload().get("criteria") or [],
            priority=int(request.payload().get("priority") or 5),
        )
        return {**goal.to_dict(), "stats": self.ws.learning.stats(goal.id)}

    @route(
        "GET",
        "/api/learning/goals/{goal_id}",
        "One goal: items, schedule, next question, sessions.",
    )
    def get_learning_goal(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        goal = self.ws.learning.require_goal(unquote(match.group("goal_id")))
        items = self.ws.learning.items(goal.id)
        try:
            nxt = self.ws.tutor.next_item(goal.id)
            nxt["item"].pop("expected", None)
            nxt["item"].pop("explanation", None)
            nxt["item"].pop("hints", None)
        except NothingToStudy as exc:
            nxt = {"nothing_to_study": True, "message": exc.message}
        return {
            "goal": goal.to_dict(),
            "items": [item.to_dict() for item in items],
            "stats": self.ws.learning.stats(goal.id),
            "next": nxt,
            "sessions": [
                session.to_dict()
                for session in self.ws.learning.sessions(goal.id, limit=5)
            ],
        }

    @route("POST", "/api/learning/goals/{goal_id}/items", "Add one item to a goal.")
    def post_learning_item(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        goal = self.ws.learning.require_goal(unquote(match.group("goal_id")))
        payload = request.payload()
        hints = payload.get("hints") or []
        if isinstance(hints, str):
            hints = [line for line in hints.splitlines() if line.strip()]
        item = self.ws.learning.add_item(
            goal.id,
            request.text("prompt", required=True) or "",
            expected=(str(payload.get("expected") or "").strip() or None),
            hints=[str(hint) for hint in hints],
            explanation=(str(payload.get("explanation") or "").strip() or None),
        )
        return {**item.to_dict(), "goal": goal.to_dict()}

    @route("POST", "/api/learning/goals/{goal_id}/plan", "Propose items for a goal.")
    def post_learning_plan(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        goal = self.ws.learning.require_goal(unquote(match.group("goal_id")))
        return self.ws.tutor.plan(
            goal.id,
            use_model=bool(request.payload().get("use_model", False)),
            max_items=request.payload().get("max_items"),
        )

    @route(
        "POST",
        "/api/learning/goals/{goal_id}/answer",
        "Answer an item: grade, schedule, explanation.",
    )
    def post_learning_answer(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        goal = self.ws.learning.require_goal(unquote(match.group("goal_id")))
        item_id = request.text("item_id", required=True) or ""
        item = self.ws.learning.require_item(item_id)
        if item.goal_id != goal.id:
            raise ApiError(
                400, "validation", f"item {item.id} does not belong to goal {goal.id}"
            )
        rating = request.payload().get("self_rating")
        result = self.ws.tutor.answer(
            item.id,
            str(request.payload().get("answer") or ""),
            self_rating=int(rating) if rating not in (None, "") else None,
            hints_used=int(request.payload().get("hints_used") or 0),
        )
        return result

    @route(
        "POST",
        "/api/learning/items/{item_id}/hint",
        "Reveal one hint (refused before an attempt).",
    )
    def post_learning_hint(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        item = self.ws.learning.require_item(unquote(match.group("item_id")))
        level = int(request.payload().get("level") or 1)
        try:
            return self.ws.tutor.hint(item.id, level=level)
        except HintBeforeAttempt as refused:
            raise ApiError(
                409, "try_first", refused.message, data={"item_id": refused.item_id}
            ) from refused

    @route(
        "POST",
        "/api/learning/goals/{goal_id}/review",
        "Start a review session of what is due.",
    )
    def post_learning_review(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        goal = self.ws.learning.require_goal(unquote(match.group("goal_id")))
        try:
            return self.ws.tutor.review(goal.id)
        except NothingToStudy as exc:
            raise ApiError(409, "nothing_due", exc.message) from exc
