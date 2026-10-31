"""Presentation operations for execution targets."""

from __future__ import annotations

from typing import Any


class ExecutionServicePresentationMixin:
    """Presentation responsibility for ExecutionService."""

    def _view(self, run) -> dict[str, Any]:
        payload = run.to_dict()
        payload["sentence"] = self._sentence(run)
        payload["reasons"] = (
            []
            if run.status != "refused"
            else [part.strip() for part in (run.note or "").split("; ") if part.strip()]
        )
        return payload

    @staticmethod
    def _sentence(run) -> str:
        where = {
            "local": "on this machine",
            "remote": "on another machine",
            "docker": "in a container",
            "wsl": "in WSL",
            "vmware": "inside a VMware guest",
            "virtualbox": "inside a VirtualBox guest",
            "windows-sandbox": "in a Windows Sandbox",
        }.get(run.kind, f"on a {run.kind} target")
        if run.status == "refused":
            return f"nothing ran: {run.kind} is not usable here"
        if run.status == "detached":
            return f"`{run.command}` was started {where}, which reports nothing back"
        if run.status == "timeout":
            return f"`{run.command}` ran {where} and was killed at the timeout"
        if run.status == "failed" and run.exit_code is None:
            return f"`{run.command}` never ran {where}: {run.note}"
        return f"`{run.command}` ran {where} and exited {run.exit_code}"

    def view(self, wanted: str) -> dict[str, Any]:
        return self._view(self.manager.run_(wanted))

    def runs(
        self, *, target: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        target_id = None
        if target:
            target_id = self.manager.target(target).id
        return [
            run.to_dict()
            for run in self.manager.runs(
                target_id=target_id, status=status, limit=limit
            )
        ]

    def targets(self) -> list[dict[str, Any]]:
        return [target.to_dict() for target in self.manager.targets()]

    def stats(self) -> dict[str, Any]:
        base = self.manager.stats()
        base["enabled"] = bool(self.ws.config.get("execution.enabled", False))
        base["default_target"] = str(
            self.ws.config.get("execution.target", "local") or "local"
        )
        base["probes"] = {probe["kind"]: probe["available"] for probe in self.probes()}
        return base
