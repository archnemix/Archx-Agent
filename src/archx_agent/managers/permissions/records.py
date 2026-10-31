"""Record types and row conversion for permission policy."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from archx_agent.helpers.timeutil import iso_now


@dataclass(frozen=True)
class Capability:
    """A protected operation.

    ``risk`` drives how loudly the CLI talks about it; ``effect`` says what
    actually happens to the world, which is what the user is consenting to.
    """

    name: str
    description: str
    risk: str
    effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk,
            "effect": self.effect,
        }


@dataclass
class Grant:
    id: str
    scope: str
    capability: str
    subject: str
    constraints: dict[str, Any] = field(default_factory=dict)
    duration: str = "task"
    granted_by: str = "user:cli"
    reason: str = ""
    created_at: str = ""
    expires_at: str | None = None
    revoked_at: str | None = None
    revoked_by: str | None = None
    conversation_id: str | None = None
    task_id: str | None = None
    project_id: str | None = None
    use_count: int = 0
    last_used_at: str | None = None
    approval_id: str | None = None
    notes: str | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def expired(self, now: str | None = None) -> bool:
        if not self.expires_at:
            return False
        return self.expires_at <= (now or iso_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capability": self.capability,
            "subject": self.subject,
            "scope": self.scope,
            "duration": self.duration,
            "granted_by": self.granted_by,
            "reason": self.reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
            "revoked_by": self.revoked_by,
            "conversation_id": self.conversation_id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "use_count": self.use_count,
            "last_used_at": self.last_used_at,
            "approval_id": self.approval_id,
            "constraints": self.constraints,
            "notes": self.notes,
            "active": self.active,
        }

    @property
    def summary(self) -> str:
        where = self.scope
        for key, value in (
            ("conversation", self.conversation_id),
            ("task", self.task_id),
            ("project", self.project_id),
        ):
            if value:
                where = f"{self.scope}:{value}"
                break
        expiry = f", expires {self.expires_at}" if self.expires_at else ""
        return f"{self.capability} -> {self.subject} [{where}{expiry}]"


@dataclass
class Approval:
    id: str
    capability: str
    subject: str
    scope: str
    requested_by: str
    status: str
    created_at: str
    purpose: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    conversation_id: str | None = None
    task_id: str | None = None
    project_id: str | None = None
    expires_at: str | None = None
    decided_at: str | None = None
    decided_by: str | None = None
    decision_reason: str | None = None
    grant_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capability": self.capability,
            "subject": self.subject,
            "scope": self.scope,
            "requested_by": self.requested_by,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "purpose": self.purpose,
            "payload": self.payload,
            "conversation_id": self.conversation_id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "decision_reason": self.decision_reason,
            "grant_id": self.grant_id,
        }


@dataclass
class PermissionDecision:
    """The answer to "may this operation proceed?" - with its evidence."""

    allowed: bool
    capability: str
    subject: str
    reason: str
    risk: str = "low"
    grant_id: str | None = None
    approval_id: str | None = None
    scope: str | None = None
    expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "capability": self.capability,
            "subject": self.subject,
            "reason": self.reason,
            "risk": self.risk,
            "grant_id": self.grant_id,
            "approval_id": self.approval_id,
            "scope": self.scope,
            "expires_at": self.expires_at,
        }


def _grant_from_row(row: dict[str, Any]) -> Grant:
    return Grant(
        id=row["id"],
        scope=row["scope"],
        capability=row["capability"],
        subject=row["subject"],
        constraints=json.loads(row["constraints"]) if row.get("constraints") else {},
        duration=row.get("duration") or row["scope"],
        granted_by=row["granted_by"],
        reason=row.get("reason") or "",
        created_at=row["created_at"],
        expires_at=row.get("expires_at"),
        revoked_at=row.get("revoked_at"),
        revoked_by=row.get("revoked_by"),
        conversation_id=row.get("conversation_id"),
        task_id=row.get("task_id"),
        project_id=row.get("project_id"),
        use_count=int(row.get("use_count") or 0),
        last_used_at=row.get("last_used_at"),
        approval_id=row.get("approval_id"),
        notes=row.get("notes"),
    )


def _approval_from_row(row: dict[str, Any]) -> Approval:
    return Approval(
        id=row["id"],
        capability=row["capability"],
        subject=row["subject"],
        scope=row["scope"],
        requested_by=row["requested_by"],
        status=row["status"],
        created_at=row["created_at"],
        purpose=row.get("purpose") or "",
        payload=json.loads(row["payload"]) if row.get("payload") else {},
        conversation_id=row.get("conversation_id"),
        task_id=row.get("task_id"),
        project_id=row.get("project_id"),
        expires_at=row.get("expires_at"),
        decided_at=row.get("decided_at"),
        decided_by=row.get("decided_by"),
        decision_reason=row.get("decision_reason"),
        grant_id=row.get("grant_id"),
    )
