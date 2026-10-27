"""The permission centre: who may do what, for how long, and who said so.

Rules this module exists to enforce:

* **Authority is explicit.** A capability is allowed only because a recorded
  grant says so, or because an approval was recorded for exactly that request.
  Nothing in the tool registry, an extension manifest or a model's arguments can
  create a grant.
* **A grant is narrow by construction.** It names one capability, one subject and
  one duration. Scope is *checked*, not assumed: a conversation grant does not
  apply in another conversation, and a task grant does not outlive its task.
* **An approval cannot be widened.** Approving requests exactly the capability,
  subject and scope that the user saw; there is deliberately no API to approve
  "and also allow writes".
* **Denials are recorded.** A refused operation leaves a `permission` trace event
  and (for tools) a `tool_runs` row, because "it silently did nothing" is the
  worst possible answer.

Durations, in increasing breadth:

``once``         consumed by the first successful check
``task``         valid while the same task id is in context
``conversation`` valid inside the conversation it was granted in
``project``      valid for the project it was granted in
``persistent``   valid until revoked (optionally time-boxed with ``hours``)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.result import Result
from archx_agent.helpers.timeutil import iso_now, new_id, parse_iso

from .base import BaseManager

PERMISSION_TABLES = ("permission_grants", "approval_requests")

DURATIONS = ("once", "task", "conversation", "project", "persistent")


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


CAPABILITIES: dict[str, Capability] = {
    "fs.read": Capability("fs.read", "read and list files inside the tool roots", "low", "reads"),
    "fs.write": Capability("fs.write", "create or modify files inside the tool roots", "medium", "writes"),
    "fs.delete": Capability("fs.delete", "delete files inside the tool roots", "high", "deletes"),
    "shell.run": Capability("shell.run", "run a local process", "high", "executes"),
    "mcp.call": Capability("mcp.call", "invoke a tool on a configured MCP server", "medium", "network"),
    "process.exec": Capability("process.exec", "run a program shipped by a trusted extension", "high", "executes"),
    # Declared now so grants/messages are consistent, but nothing implements it in
    # this build: a capability nobody can exercise must not be advertised as available.
    "net.fetch": Capability("net.fetch", "fetch a URL (no tool implements this yet)", "medium", "network"),
}

RISK_LEVELS = ("low", "medium", "high")


def capability_names() -> list[str]:
    return sorted(CAPABILITIES)


def _validate_capability(name: str) -> Capability:
    if name not in CAPABILITIES:
        raise ValidationError(
            f"unknown capability {name!r} (known: {', '.join(capability_names())})"
        )
    return CAPABILITIES[name]


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
        for key, value in (("conversation", self.conversation_id), ("task", self.task_id),
                           ("project", self.project_id)):
            if value:
                where = f"{self.scope}:{value}"
                break
        expiry = f", expires {self.expires_at}" if self.expires_at else ""
        return f"{self.capability} -> {self.subject} [{where}{expiry}]"


APPROVAL_STATUSES = ("pending", "approved", "denied", "expired")


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


class PermissionManager(BaseManager):
    """Grants, approvals and the check every protected operation calls."""

    tables = PERMISSION_TABLES

    def __init__(self, store, coordinator, *, events=None, config=None) -> None:
        self.config = config
        super().__init__(store, coordinator, events=events)

    # -- plumbing ---------------------------------------------------------
    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001 - a missing key must not break a check
            return default

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
                g["id"], g["scope"], g["capability"], g["subject"],
                json_text(g.get("constraints") or {}), g["duration"], g["granted_by"],
                g.get("reason") or "", g["created_at"], g.get("expires_at"), None, None,
                g.get("conversation_id"), g.get("task_id"), g.get("project_id"),
                0, None, g.get("approval_id"), g.get("notes"),
            ),
        )
        return {"id": g["id"]}

    def _apply_revoke(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "UPDATE permission_grants SET revoked_at=?, revoked_by=?, notes=COALESCE(?, notes)"
            " WHERE id=? AND revoked_at IS NULL",
            (payload["revoked_at"], payload["revoked_by"], payload.get("notes"), payload["id"]),
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
                (payload["used_at"], "system:consumed", "single-use grant consumed", payload["id"]),
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
                a["id"], a["capability"], a["subject"], a["scope"], a.get("conversation_id"),
                a.get("task_id"), a.get("project_id"), a["requested_by"], a.get("purpose") or "",
                json_text(a.get("payload") or {}), a["status"], a["created_at"],
                a.get("expires_at"), None, None, None, None,
            ),
        )
        return {"id": a["id"]}

    def _apply_decide(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "UPDATE approval_requests SET status=?, decided_at=?, decided_by=?,"
            " decision_reason=?, grant_id=? WHERE id=? AND status='pending'",
            (
                payload["status"], payload["decided_at"], payload["decided_by"],
                payload.get("reason") or "", payload.get("grant_id"), payload["id"],
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

    # -- capabilities -----------------------------------------------------
    @staticmethod
    def capabilities() -> list[dict[str, Any]]:
        return [c.to_dict() for c in CAPABILITIES.values()]

    # -- grants -----------------------------------------------------------
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
            raise ValidationError("a grant needs a subject (a tool name, or '*' for any subject)")
        duration = duration or self._cfg("permissions.default_duration", "once")
        if duration not in DURATIONS:
            raise ValidationError(f"unknown duration {duration!r} (expected one of {list(DURATIONS)})")
        if duration == "conversation" and not conversation_id:
            raise ValidationError(
                "a conversation grant needs a conversation (--conversation); otherwise it would "
                "silently apply to every conversation"
            )
        if duration == "task" and not task_id:
            raise ValidationError("a task grant needs a task (--task); otherwise it would apply to everything")
        if duration == "project" and not project_id:
            raise ValidationError("a project grant needs a project (--project)")
        notes = None
        if duration == "persistent" and self._cfg("permissions.require_confirmation", True) and not confirm:
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
            expires_at = (parse_iso(iso_now()) + timedelta(hours=hours)).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z")
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
            raise ValidationError(f"grant {grant_id} was already revoked at {current.revoked_at}")
        self._write(
            "permission.revoke",
            {"id": grant_id, "revoked_at": iso_now(), "revoked_by": by, "notes": reason or None},
        )
        updated = self.get(grant_id).ok_or_raise()
        self.trace("permission", "revoke", payload={"grant_id": grant_id, "by": by, "reason": reason})
        return updated

    def get(self, grant_id: str) -> Result[Grant]:
        row = self.store.query_one("SELECT * FROM permission_grants WHERE id = ?", (grant_id,))
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
                {"id": row["id"], "revoked_at": now, "revoked_by": "system:expiry",
                 "notes": "grant expired"},
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
    def _matches_scope(grant: Grant, *, conversation_id: str | None, task_id: str | None,
                       project_id: str | None) -> tuple[bool, str]:
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

    # -- the check --------------------------------------------------------
    def check(
        self,
        capability: str,
        *,
        subject: str,
        conversation_id: str | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
        consume: bool = False,
        purpose: str = "",
        request_approval_on_denial: bool = True,
    ) -> PermissionDecision:
        """Decide whether ``subject`` may perform ``capability`` right now.

        ``consume`` marks a single-use grant used. It is done *before* the work
        runs on purpose: a crash mid-operation must not hand back a fresh grant.
        """
        cap = _validate_capability(capability)
        denied = [str(x).strip() for x in (self._cfg("permissions.denied_capabilities", []) or [])]
        if capability in denied or cap.name in denied:
            decision = PermissionDecision(
                allowed=False, capability=cap.name, subject=subject, risk=cap.risk,
                reason=f"{cap.name} is denied by permissions.denied_capabilities",
            )
            self._trace_decision(decision, conversation_id, task_id, project_id, purpose)
            return decision

        for grant in self._active_grants(cap.name, subject):
            ok, why = self._matches_scope(
                grant, conversation_id=conversation_id, task_id=task_id, project_id=project_id
            )
            if not ok:
                continue
            if consume:
                self._write(
                    "permission.consume",
                    {
                        "id": grant.id,
                        "used_at": iso_now(),
                        "revoke": grant.scope == "once",
                        "use_count": grant.use_count + 1,
                    },
                )
            note = " (single-use grant consumed)" if consume and grant.scope == "once" else ""
            decision = PermissionDecision(
                allowed=True,
                capability=cap.name,
                subject=subject,
                risk=cap.risk,
                reason=f"granted by {grant.id} ({why}){note}",
                grant_id=grant.id,
                scope=grant.scope,
                expires_at=grant.expires_at,
            )
            self._trace_decision(decision, conversation_id, task_id, project_id, purpose)
            return decision

        scope = self._cfg("permissions.default_duration", "once")
        approval: Approval | None = None
        if request_approval_on_denial and self._cfg("permissions.approvals_enabled", True):
            try:
                approval = self.request_approval(
                    cap.name,
                    subject=subject,
                    scope=scope,
                    conversation_id=conversation_id,
                    task_id=task_id,
                    project_id=project_id,
                    purpose=purpose,
                )
                reason = (
                    f"{cap.name} is not granted for {subject!r}; approval {approval.id} is pending "
                    f"(archx-agent approvals approve {approval.id})"
                )
            except ValidationError as exc:
                reason = f"{cap.name} is not granted for {subject!r}: {exc.message}"
        elif not request_approval_on_denial:
            reason = (
                f"{cap.name} is not granted for {subject!r} "
                "(this check does not create approval requests)"
            )
        else:
            reason = (
                f"{cap.name} is not granted for {subject!r} and approvals are disabled "
                "(permissions.approvals_enabled=false)"
            )
        decision = PermissionDecision(
            allowed=False,
            capability=cap.name,
            subject=subject,
            risk=cap.risk,
            reason=reason,
            approval_id=approval.id if approval else None,
            scope=scope,
        )
        self._trace_decision(decision, conversation_id, task_id, project_id, purpose)
        return decision

    def _trace_decision(
        self,
        decision: PermissionDecision,
        conversation_id: str | None,
        task_id: str | None,
        project_id: str | None,
        purpose: str,
    ) -> None:
        self.trace(
            "permission",
            "check",
            status="ok" if decision.allowed else "denied",
            conversation_id=conversation_id,
            task_id=task_id,
            project_id=project_id,
            payload={
                "capability": decision.capability,
                "subject": decision.subject,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "grant_id": decision.grant_id,
                "approval_id": decision.approval_id,
                "risk": decision.risk,
                "purpose": purpose,
            },
        )

    # -- approvals --------------------------------------------------------
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
        existing = self._pending_for(cap.name, subject, conversation_id, task_id, project_id)
        if existing is not None:
            return existing
        limit = int(self._cfg("permissions.max_pending_approvals", 25))
        pending = int(self.store.scalar(
            "SELECT COUNT(*) FROM approval_requests WHERE status='pending'"
        ) or 0)
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
            expires_at=(parse_iso(iso_now()) + timedelta(minutes=minutes)).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z"),
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
            (capability, subject, conversation_id or "", task_id or "", project_id or ""),
        )
        return _approval_from_row(row) if row else None

    def approvals(self, *, status: str | None = None, limit: int = 100) -> list[Approval]:
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
        row = self.store.query_one("SELECT * FROM approval_requests WHERE id = ?", (approval_id,))
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
                + (f" ({current.decided_by} at {current.decided_at})" if current.decided_at else "")
            )
        if current.expires_at and current.expires_at <= iso_now():
            self._write("approval.expire", {"id": approval_id, "now": iso_now()})
            raise ValidationError(f"approval {approval_id} expired at {current.expires_at}")
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

    def deny(self, approval_id: str, *, by: str = "user:cli", reason: str = "denied by the user") -> Approval:
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
        self.trace("permission", "approval.denied", status="denied", payload=denied.to_dict())
        return denied


__all__ = [
    "CAPABILITIES",
    "Capability",
    "DURATIONS",
    "Approval",
    "Grant",
    "PermissionDecision",
    "PermissionManager",
    "RISK_LEVELS",
    "capability_names",
]
