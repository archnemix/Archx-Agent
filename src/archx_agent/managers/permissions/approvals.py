"""Approvals operations for permission policy."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.result import Result
from archx_agent.helpers.timeutil import iso_now, new_id, parse_iso
from archx_agent.managers.permissions.constants import DURATIONS, APPROVAL_STATUSES
from archx_agent.managers.permissions.records import Grant, Approval, _approval_from_row
from archx_agent.managers.permissions.capabilities import _validate_capability


class PermissionManagerApprovalsMixin:
    """Approvals responsibility for PermissionManager."""

    def request_approval(
        self,
        capability: str,
        *,
        subject: str,
        scope: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
        requested_by: str = "tool",
        purpose: str = "",
        payload: dict[str, Any] | None = None,
    ) -> Approval:
        cap = _validate_capability(capability)
        scope = scope or self._cfg("permissions.default_duration", "once")
        if scope not in DURATIONS:
            raise ValidationError(f"unknown duration {scope!r}")
        existing = self._pending_for(
            cap.name, subject, conversation_id, task_id, project_id
        )
        if existing is not None:
            return existing
        limit = int(self._cfg("permissions.max_pending_approvals", 25))
        pending = int(
            self.store.scalar(
                "SELECT COUNT(*) FROM approval_requests WHERE status='pending'"
            )
            or 0
        )
        if pending >= limit:
            raise ValidationError(
                f"{pending} approvals are already pending (permissions.max_pending_approvals={limit});"
                " approve or deny one first"
            )
        minutes = int(self._cfg("permissions.approval_ttl_minutes", 60))
        approval = Approval(
            id=new_id("ap_"),
            capability=cap.name,
            subject=subject,
            scope=scope,
            requested_by=requested_by,
            status="pending",
            created_at=iso_now(),
            purpose=purpose,
            payload=payload or {},
            conversation_id=conversation_id,
            task_id=task_id,
            project_id=project_id,
            expires_at=(parse_iso(iso_now()) + timedelta(minutes=minutes))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
        )
        self._write("approval.request", {"approval": approval.to_dict()})
        self.trace(
            "permission",
            "approval.requested",
            status="pending",
            conversation_id=conversation_id,
            task_id=task_id,
            project_id=project_id,
            payload=approval.to_dict(),
        )
        return approval

    def _pending_for(
        self,
        capability: str,
        subject: str,
        conversation_id: str | None,
        task_id: str | None,
        project_id: str | None,
    ) -> Approval | None:
        row = self.store.query_one(
            "SELECT * FROM approval_requests WHERE status='pending' AND capability=? AND subject=?"
            " AND IFNULL(conversation_id,'')=? AND IFNULL(task_id,'')=? AND IFNULL(project_id,'')=?"
            " ORDER BY created_at DESC LIMIT 1",
            (
                capability,
                subject,
                conversation_id or "",
                task_id or "",
                project_id or "",
            ),
        )
        return _approval_from_row(row) if row else None

    def approvals(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[Approval]:
        sql = "SELECT * FROM approval_requests"
        params: list[Any] = []
        if status:
            if status not in APPROVAL_STATUSES:
                raise ValidationError(f"unknown approval status {status!r}")
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        return [_approval_from_row(row) for row in self.store.query(sql, params)]

    def pending(self, *, limit: int = 50) -> list[Approval]:
        self.expire_pending()
        return self.approvals(status="pending", limit=limit)

    def get_approval(self, approval_id: str) -> Result[Approval]:
        row = self.store.query_one(
            "SELECT * FROM approval_requests WHERE id = ?", (approval_id,)
        )
        if row is None:
            return Result.err(NotFoundError(f"no approval {approval_id}"))
        return Result.ok(_approval_from_row(row))

    def expire_pending(self) -> int:
        now = iso_now()
        rows = self.store.query(
            "SELECT id FROM approval_requests WHERE status='pending' AND expires_at IS NOT NULL"
            " AND expires_at <= ?",
            (now,),
        )
        for row in rows:
            self._write("approval.expire", {"id": row["id"], "now": now})
        return len(rows)

    def approve(
        self,
        approval_id: str,
        *,
        by: str = "user:cli",
        reason: str = "",
        hours: int | None = None,
    ) -> tuple[Approval, Grant]:
        """Approve exactly what was requested - no more.

        The request already names the capability, the subject and the scope. There
        is intentionally no argument to change them: widening authority is a
        separate, explicit ``permissions grant``.
        """
        approval = self.get_approval(approval_id)
        if approval.is_err:
            raise approval.error
        current = approval.value
        if current.status != "pending":
            raise ValidationError(
                f"approval {approval_id} is already {current.status}"
                + (
                    f" ({current.decided_by} at {current.decided_at})"
                    if current.decided_at
                    else ""
                )
            )
        if current.expires_at and current.expires_at <= iso_now():
            self._write("approval.expire", {"id": approval_id, "now": iso_now()})
            raise ValidationError(
                f"approval {approval_id} expired at {current.expires_at}"
            )
        grant = self.grant(
            current.capability,
            subject=current.subject,
            duration=current.scope,
            reason=reason or f"approved request {approval_id}",
            granted_by=f"approval:{approval_id}",
            conversation_id=current.conversation_id,
            task_id=current.task_id,
            project_id=current.project_id,
            hours=hours,
            approval_id=approval_id,
            confirm=True,
        )
        self._write(
            "approval.decide",
            {
                "id": approval_id,
                "status": "approved",
                "decided_at": iso_now(),
                "decided_by": by,
                "reason": reason,
                "grant_id": grant.id,
            },
        )
        decided = self.get_approval(approval_id).ok_or_raise()
        self.trace("permission", "approval.approved", payload=decided.to_dict())
        return decided, grant

    def deny(
        self,
        approval_id: str,
        *,
        by: str = "user:cli",
        reason: str = "denied by the user",
    ) -> Approval:
        approval = self.get_approval(approval_id)
        if approval.is_err:
            raise approval.error
        current = approval.value
        if current.status != "pending":
            raise ValidationError(f"approval {approval_id} is already {current.status}")
        self._write(
            "approval.decide",
            {
                "id": approval_id,
                "status": "denied",
                "decided_at": iso_now(),
                "decided_by": by,
                "reason": reason,
                "grant_id": None,
            },
        )
        denied = self.get_approval(approval_id).ok_or_raise()
        self.trace(
            "permission", "approval.denied", status="denied", payload=denied.to_dict()
        )
        return denied
