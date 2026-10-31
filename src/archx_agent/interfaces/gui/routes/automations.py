"""HTTP endpoints for automations. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class AutomationsRoutes:
    @route(
        "GET", "/api/automations", "Durable schedules and their queued/observed runs."
    )
    def get_automations(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return {
            "automations": self.ws.automations.list(),
            "runs": self.ws.automations.runs(),
        }

    @route(
        "POST",
        "/api/automations",
        "Create a disabled automation; never grant execution.",
    )
    def post_automation(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.automation.create(
            request.text("name", required=True),
            payload.get("command"),
            interval=payload.get("interval"),
            at=payload.get("at"),
            watch=payload.get("watch"),
            cwd=payload.get("cwd"),
            timeout=payload.get("timeout", 60),
        )

    @route(
        "POST",
        "/api/automations/tick",
        "Enqueue due occurrences atomically; do not run commands.",
    )
    def post_automation_tick(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.automation.tick()

    @route(
        "POST",
        "/api/automations/{automation_id}/{action}",
        "Enable or disable scheduling; queued jobs are separate.",
    )
    def post_automation_control(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        action = match.group("action")
        if action not in ("enable", "disable"):
            raise ApiError(400, "validation", "unknown automation action")
        return self.ws.automation.enable(
            unquote(match.group("automation_id")), action == "enable"
        )
