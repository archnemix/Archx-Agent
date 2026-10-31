"""HTTP endpoints for access. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class AccessRoutes:
    @route("GET", "/api/approvals", "Approval requests, pending first.")
    def get_approvals(
        self, request: Request, match: re.Match[str]
    ) -> list[dict[str, Any]]:
        status = request.q("status") or None
        return [item.to_dict() for item in self.ws.permissions.approvals(status=status)]

    @route(
        "POST",
        "/api/approvals/{approval_id}/{decision}",
        "Approve exactly what was asked, or deny it.",
    )
    def post_approval(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        approval_id = unquote(match.group("approval_id"))
        decision = match.group("decision")
        if decision == "approve":
            hours = request.payload().get("hours")
            approval, grant = self.ws.permissions.approve(
                approval_id, by="user:gui", hours=int(hours) if hours else None
            )
            return {"approval": approval.to_dict(), "grant": grant.to_dict()}
        if decision == "deny":
            reason = str(request.payload().get("reason") or "denied in the GUI")
            return {
                "approval": self.ws.permissions.deny(
                    approval_id, by="user:gui", reason=reason
                ).to_dict()
            }
        raise ApiError(404, "no_route", f"unknown approval decision {decision!r}")

    @route(
        "GET", "/api/permissions", "Active grants, and every capability Archx knows."
    )
    def get_permissions(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        grants = [
            grant
            for grant in self.ws.permissions.grants(
                include_revoked=not request.q_bool("active_only", False),
                include_expired=not request.q_bool("active_only", False),
            )
            if grant.active or not request.q_bool("active_only", False)
        ]
        return {
            "grants": [grant.to_dict() for grant in grants],
            "capabilities": self.ws.permissions.capabilities(),
        }

    @route("POST", "/api/permissions/{grant_id}/revoke", "Revoke one grant.")
    def post_revoke(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        grant_id = unquote(match.group("grant_id"))
        reason = str(request.payload().get("reason") or "revoked in the GUI")
        return self.ws.permissions.revoke(
            grant_id, by="user:gui", reason=reason
        ).to_dict()
