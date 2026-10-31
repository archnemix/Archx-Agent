"""HTTP endpoints for memory. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from archx_agent.interfaces.gui.protocol import Request, route


class MemoryRoutes:
    @route("GET", "/api/memory", "Stored memories, newest first.")
    def get_memory(
        self, request: Request, match: re.Match[str]
    ) -> list[dict[str, Any]]:
        kinds = [value for value in (request.query.get("kind") or []) if value]
        items = self.ws.memory.list(
            kinds=kinds or None, limit=request.q_int("limit", 50)
        )
        return [item.to_dict() for item in items]

    @route(
        "POST", "/api/memory", "Store a memory (the same validation as `memory add`)."
    )
    def post_memory(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        kind = request.text("kind", default="permanent") or "permanent"
        title = request.text("title", required=True) or ""
        content = request.text("content", required=True) or ""
        # ``permanent`` only accepts preference/fact/instruction/constraint; the other
        # kinds accept the wider set. An empty field means "the default for this kind".
        default_category = "fact" if kind == "permanent" else "note"
        category = str(request.payload().get("category") or default_category)
        stored = self.ws.memory.add(
            kind,
            title=title,
            content=content,
            category=category,
            source="user:gui",
        )
        if stored.is_err:
            raise stored.error
        return stored.value.to_dict()
