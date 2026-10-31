"""Decisions operations for permission policy."""

from __future__ import annotations

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.permissions.records import Approval, PermissionDecision
from archx_agent.managers.permissions.capabilities import _validate_capability


class PermissionManagerDecisionsMixin:
    """Decisions responsibility for PermissionManager."""

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
        denied = [
            str(x).strip()
            for x in (self._cfg("permissions.denied_capabilities", []) or [])
        ]
        if capability in denied or cap.name in denied:
            decision = PermissionDecision(
                allowed=False,
                capability=cap.name,
                subject=subject,
                risk=cap.risk,
                reason=f"{cap.name} is denied by permissions.denied_capabilities",
            )
            self._trace_decision(
                decision, conversation_id, task_id, project_id, purpose
            )
            return decision

        for grant in self._active_grants(cap.name, subject):
            ok, why = self._matches_scope(
                grant,
                conversation_id=conversation_id,
                task_id=task_id,
                project_id=project_id,
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
            note = (
                " (single-use grant consumed)"
                if consume and grant.scope == "once"
                else ""
            )
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
            self._trace_decision(
                decision, conversation_id, task_id, project_id, purpose
            )
            return decision

        scope = self._cfg("permissions.default_duration", "once")
        approval: Approval | None = None
        if request_approval_on_denial and self._cfg(
            "permissions.approvals_enabled", True
        ):
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
