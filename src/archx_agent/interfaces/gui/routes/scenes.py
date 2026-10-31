"""HTTP endpoints for scenes. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class ScenesRoutes:
    @route("GET", "/api/scenes", "Scenes and geometry ledger totals.")
    def get_scenes(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        service = self.ws.scene_workflow
        return {"scenes": service.list(), "stats": service.stats()}

    @route("POST", "/api/scenes", "Create an empty scene through the tool layer.")
    def post_scene(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.scene_workflow.create(
            request.text("name", required=True) or "",
            task_id=request.text("task_id", required=False),
        )

    @route(
        "GET", "/api/scenes/{scene_id}", "Measured geometry and outputs for one scene."
    )
    def get_scene(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.scene_workflow.view(unquote(match.group("scene_id")))

    @route(
        "POST",
        "/api/scenes/{scene_id}/{action}",
        "Edit, export, verify or locally render a scene.",
    )
    def post_scene_action(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        service = self.ws.scene_workflow
        scene_id = unquote(match.group("scene_id"))
        action = match.group("action")
        payload = request.payload()
        if action == "add":
            params, transform = payload.get("params", {}), payload.get("transform", {})
            if not isinstance(params, dict) or not isinstance(transform, dict):
                raise ApiError(
                    400, "validation", "params and transform must be JSON objects"
                )
            return service.add(
                scene_id,
                request.text("primitive", required=True) or "",
                name=request.text("name", required=False),
                params=params,
                transform=transform,
            )
        if action == "remove":
            return service.remove(scene_id, request.text("name", required=True) or "")
        if action == "export":
            return service.export(scene_id, request.text("kind", required=True) or "")
        if action in ("verify", "measure", "preview", "render"):
            return getattr(service, action)(scene_id)
        raise ApiError(400, "validation", "unknown scene action")
