"""Targets operations for execution targets."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import (
    NotFoundError,
    ValidationError,
)
from archx_agent.managers.execution import KINDS, ExecutionTarget
from archx_agent.application.execution.probes import probe_backends


class ExecutionServiceTargetsMixin:
    """Targets responsibility for ExecutionService."""

    def probes(self) -> list[dict[str, Any]]:
        return [probe.to_dict() for probe in probe_backends(self.ws)]

    def probe(self, kind: str) -> dict[str, Any]:
        for probe in probe_backends(self.ws):
            if probe.kind == kind:
                return probe.to_dict()
        raise ValidationError(
            f"unknown backend {kind!r} (this build knows {', '.join(KINDS)})"
        )

    def ensure(
        self,
        kind: str,
        *,
        name: str | None = None,
        endpoint: str | None = None,
        spec: dict[str, Any] | None = None,
    ) -> ExecutionTarget:
        """Add a target if it is not there, and refuse to add one this machine cannot use."""
        probed = self.probe(kind)
        existing = [
            target for target in self.manager.targets() if target.name == (name or kind)
        ]
        if existing:
            return existing[0]
        if not probed["available"] and kind != "local":
            # A target that cannot run is still *recorded* - as refused, with the reason - because
            # "I set this up and it did not work" is exactly the thing a ledger should keep.
            return self.manager.add_target(
                kind=kind,
                name=name or kind,
                endpoint=endpoint,
                spec=spec or {},
                status="refused",
                refusal="; ".join(probed["why_not"]) or None,
            )
        return self.manager.add_target(
            kind=kind,
            name=name or kind,
            endpoint=endpoint,
            spec=spec or {},
            status="probed",
        )

    def blockers(self, target: ExecutionTarget) -> list[str]:
        """Why this target cannot run *now*. The probe is reality; the row's refusal is history.

        A target recorded while a backend was missing must start working when the backend arrives -
        otherwise the first probe would be a life sentence - so the stored refusal only speaks when
        the fresh probe still fails, and then it speaks with the probe's own words.
        """
        reasons: list[str] = []
        if not self.ws.config.get("execution.enabled", False):
            reasons.append(
                "execution is off: `archx-agent config set execution.enabled true` "
                "(a command in a sandbox is still a command)"
            )
        if target.kind != "local":
            probed = self.probe(target.kind)
            reasons.extend(probed["why_not"])
        if target.kind == "remote" and not (
            target.endpoint
            or str(self.ws.config.get("remote.endpoint", "") or "").strip()
        ):
            reasons.append(
                "this remote target has no endpoint: `archx-agent exec add remote --name vm1 "
                "--endpoint http://host:9001`, or set remote.endpoint"
            )
        # The same sentence twice is noise: a recorded refusal and a failed probe usually agree.
        seen: set[str] = set()
        unique: list[str] = []
        for reason in reasons:
            if reason in seen:
                continue
            seen.add(reason)
            unique.append(reason)
        return unique

    def _resolve(self, wanted: str | None) -> ExecutionTarget:
        """A target by name or kind; `local` always exists, even before a row is written."""
        name = (
            wanted or str(self.ws.config.get("execution.target", "local") or "local")
        ).strip()
        try:
            return self.manager.target(name)
        except NotFoundError:
            if name != "local":
                raise
            return self.ensure("local")
