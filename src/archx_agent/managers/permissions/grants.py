"""Grants operations for permission policy."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.result import Result
from archx_agent.helpers.timeutil import iso_now, new_id, parse_iso
from archx_agent.managers.permissions.constants import DURATIONS
from archx_agent.managers.permissions.records import Grant, _grant_from_row
from archx_agent.managers.permissions.capabilities import _validate_capability


class PermissionManagerGrantsMixin:
    """Grants responsibility for PermissionManager."""

    def grant(
        self,
        capability: str,
        *,
        subject: str = "*",
        duration: str | None = None,
        reason: str = "",
        granted_by: str = "user:cli",
        conversation_id: str | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
        hours: int | None = None,
        confirm: bool = False,
        approval_id: str | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> Grant:
        """Record an explicit grant. Only user-facing code calls this."""
        cap = _validate_capability(capability)
        subject = (subject or "").strip()
        if not subject:
            raise ValidationError(
                "a grant needs a subject (a tool name, or '*' for any subject)"
            )
        duration = duration or self._cfg("permissions.default_duration", "once")
        if duration not in DURATIONS:
            raise ValidationError(
                f"unknown duration {duration!r} (expected one of {list(DURATIONS)})"
            )
        if duration == "conversation" and not conversation_id:
            raise ValidationError(
                "a conversation grant needs a conversation (--conversation); otherwise it would "
                "silently apply to every conversation"
            )
        if duration == "task" and not task_id:
            raise ValidationError(
                "a task grant needs a task (--task); otherwise it would apply to everything"
            )
        if duration == "project" and not project_id:
            raise ValidationError("a project grant needs a project (--project)")
        notes = None
        if (
            duration == "persistent"
            and self._cfg("permissions.require_confirmation", True)
            and not confirm
        ):
            # No silent downgrade: the user typed "persistent", so they are told what is
            # missing rather than handed a shorter grant they did not ask for.
            raise ValidationError(
                "a persistent grant needs --confirm (it outlives the current task, conversation "
                "and project)"
            )
        expires_at = None
        if hours:
            if hours < 1:
                raise ValidationError("--for must be at least 1 hour")
            limit = int(self._cfg("permissions.max_grant_hours", 720))
            if hours > limit:
                raise ValidationError(
                    f"--for {hours}h exceeds permissions.max_grant_hours ({limit}h)"
                )
            expires_at = (
                (parse_iso(iso_now()) + timedelta(hours=hours))
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
        grant = Grant(
            id=new_id("pg_"),
            scope=duration,
            capability=cap.name,
            subject=subject,
            constraints=constraints or {},
            duration=duration,
            granted_by=granted_by,
            reason=reason,
            created_at=iso_now(),
            expires_at=expires_at,
            conversation_id=conversation_id,
            task_id=task_id,
            project_id=project_id,
            approval_id=approval_id,
            notes=notes,
        )
        self._write("permission.grant", {"grant": grant.to_dict()})
        self.trace(
            "permission",
            "grant",
            conversation_id=conversation_id,
            task_id=task_id,
            project_id=project_id,
            payload={
                "grant_id": grant.id,
                "capability": grant.capability,
                "subject": grant.subject,
                "scope": grant.scope,
                "expires_at": grant.expires_at,
                "granted_by": grant.granted_by,
                "reason": grant.reason,
                "notes": grant.notes,
                "approval_id": approval_id,
            },
        )
        return grant

    def revoke(self, grant_id: str, *, by: str = "user:cli", reason: str = "") -> Grant:
        grant = self.get(grant_id)
        if grant.is_err:
            raise grant.error
        current = grant.value
        if current.revoked_at:
            raise ValidationError(
                f"grant {grant_id} was already revoked at {current.revoked_at}"
            )
        self._write(
            "permission.revoke",
            {
                "id": grant_id,
                "revoked_at": iso_now(),
                "revoked_by": by,
                "notes": reason or None,
            },
        )
        updated = self.get(grant_id).ok_or_raise()
        self.trace(
            "permission",
            "revoke",
            payload={"grant_id": grant_id, "by": by, "reason": reason},
        )
        return updated

    def get(self, grant_id: str) -> Result[Grant]:
        row = self.store.query_one(
            "SELECT * FROM permission_grants WHERE id = ?", (grant_id,)
        )
        if row is None:
            return Result.err(NotFoundError(f"no grant {grant_id}"))
        return Result.ok(_grant_from_row(row))

    def grants(
        self,
        *,
        capability: str | None = None,
        subject: str | None = None,
        include_revoked: bool = False,
        include_expired: bool = False,
        limit: int = 200,
    ) -> list[Grant]:
        sql = "SELECT * FROM permission_grants WHERE 1=1"
        params: list[Any] = []
        if capability:
            sql += " AND capability = ?"
            params.append(capability)
        if subject:
            sql += " AND subject = ?"
            params.append(subject)
        if not include_revoked:
            sql += " AND revoked_at IS NULL"
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        now = iso_now()
        grants = [_grant_from_row(row) for row in self.store.query(sql, params)]
        if not include_expired:
            grants = [g for g in grants if not g.expired(now)]
        return grants

    def prune_expired(self) -> int:
        """Mark expired grants revoked, so an expired grant stops looking valid."""
        now = iso_now()
        rows = self.store.query(
            "SELECT id FROM permission_grants WHERE revoked_at IS NULL"
            " AND expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        for row in rows:
            self._write(
                "permission.revoke",
                {
                    "id": row["id"],
                    "revoked_at": now,
                    "revoked_by": "system:expiry",
                    "notes": "grant expired",
                },
            )
        return len(rows)

    def _active_grants(self, capability: str, subject: str) -> list[Grant]:
        now = iso_now()
        rows = self.store.query(
            "SELECT * FROM permission_grants WHERE capability = ? AND (subject = ? OR subject = '*')"
            " AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > ?)"
            " ORDER BY created_at DESC, id DESC",
            (capability, subject, now),
        )
        return [_grant_from_row(row) for row in rows]

    @staticmethod
    def _matches_scope(
        grant: Grant,
        *,
        conversation_id: str | None,
        task_id: str | None,
        project_id: str | None,
    ) -> tuple[bool, str]:
        if grant.duration == "persistent" or grant.scope == "persistent":
            return True, "persistent"
        if grant.scope == "once":
            return True, "single use"
        if grant.scope == "conversation":
            if conversation_id and grant.conversation_id == conversation_id:
                return True, f"conversation {conversation_id}"
            return False, "granted for a different conversation"
        if grant.scope == "task":
            if task_id and grant.task_id == task_id:
                return True, f"task {task_id}"
            return False, "granted for a different task"
        if grant.scope == "project":
            if project_id and grant.project_id == project_id:
                return True, f"project {project_id}"
            return False, "granted for a different project"
        return False, f"unknown scope {grant.scope!r}"
