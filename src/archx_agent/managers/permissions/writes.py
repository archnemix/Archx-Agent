"""Transactional write handlers for permission policy."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.jsonio import json_text


class PermissionManagerWritesMixin:
    """Writes responsibility for PermissionManager."""

    def register_handlers(self) -> None:
        self.coordinator.register("permission.grant", self._apply_grant)
        self.coordinator.register("permission.revoke", self._apply_revoke)
        self.coordinator.register("permission.consume", self._apply_consume)
        self.coordinator.register("approval.request", self._apply_request)
        self.coordinator.register("approval.decide", self._apply_decide)
        self.coordinator.register("approval.expire", self._apply_expire)

    def _apply_grant(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        g = payload["grant"]
        tx.execute(
            "INSERT INTO permission_grants(id, scope, capability, subject, constraints, duration,"
            " granted_by, reason, created_at, expires_at, revoked_at, revoked_by,"
            " conversation_id, task_id, project_id, use_count, last_used_at, approval_id, notes)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                g["id"],
                g["scope"],
                g["capability"],
                g["subject"],
                json_text(g.get("constraints") or {}),
                g["duration"],
                g["granted_by"],
                g.get("reason") or "",
                g["created_at"],
                g.get("expires_at"),
                None,
                None,
                g.get("conversation_id"),
                g.get("task_id"),
                g.get("project_id"),
                0,
                None,
                g.get("approval_id"),
                g.get("notes"),
            ),
        )
        return {"id": g["id"]}

    def _apply_revoke(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "UPDATE permission_grants SET revoked_at=?, revoked_by=?, notes=COALESCE(?, notes)"
            " WHERE id=? AND revoked_at IS NULL",
            (
                payload["revoked_at"],
                payload["revoked_by"],
                payload.get("notes"),
                payload["id"],
            ),
        )
        return {"id": payload["id"]}

    def _apply_consume(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "UPDATE permission_grants SET use_count = use_count + 1, last_used_at=? WHERE id=?",
            (payload["used_at"], payload["id"]),
        )
        if payload.get("revoke"):
            tx.execute(
                "UPDATE permission_grants SET revoked_at=?, revoked_by=?, notes=COALESCE(?, notes)"
                " WHERE id=? AND revoked_at IS NULL",
                (
                    payload["used_at"],
                    "system:consumed",
                    "single-use grant consumed",
                    payload["id"],
                ),
            )
        return {"id": payload["id"], "use_count": payload.get("use_count")}

    def _apply_request(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        a = payload["approval"]
        tx.execute(
            "INSERT INTO approval_requests(id, capability, subject, scope, conversation_id,"
            " task_id, project_id, requested_by, purpose, payload, status, created_at,"
            " expires_at, decided_at, decided_by, decision_reason, grant_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                a["id"],
                a["capability"],
                a["subject"],
                a["scope"],
                a.get("conversation_id"),
                a.get("task_id"),
                a.get("project_id"),
                a["requested_by"],
                a.get("purpose") or "",
                json_text(a.get("payload") or {}),
                a["status"],
                a["created_at"],
                a.get("expires_at"),
                None,
                None,
                None,
                None,
            ),
        )
        return {"id": a["id"]}

    def _apply_decide(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "UPDATE approval_requests SET status=?, decided_at=?, decided_by=?,"
            " decision_reason=?, grant_id=? WHERE id=? AND status='pending'",
            (
                payload["status"],
                payload["decided_at"],
                payload["decided_by"],
                payload.get("reason") or "",
                payload.get("grant_id"),
                payload["id"],
            ),
        )
        return {"id": payload["id"], "status": payload["status"]}

    def _apply_expire(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "UPDATE approval_requests SET status='expired', decided_at=?, decided_by='system:expiry',"
            " decision_reason='request expired before a decision' WHERE status='pending' AND id=?",
            (payload["now"], payload["id"]),
        )
        return {"id": payload["id"]}
