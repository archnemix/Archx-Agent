"""HTTP endpoints for overview. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


import time


from typing import Any


from archx_agent import __version__


from archx_agent.helpers.timeutil import iso_now


from archx_agent.interfaces.gui.protocol import CSRF_HEADER, CSRF_VALUE, Request, route


class OverviewRoutes:
    def health(self) -> dict[str, Any]:
        return {
            "app": "archx-agent",
            "version": __version__,
            "started_at": iso_now(),
            "uptime_seconds": round(time.time() - self.started_at, 3),
            "requests": self.requests,
            "auth": "token",
            "csrf_header": f"{CSRF_HEADER}: {CSRF_VALUE}",
        }

    @route(
        "GET", "/api/status", "One screen: what this home holds, and what is blocked."
    )
    def get_status(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        info = self.ws.info()
        jobs = self.ws.jobs.stats() if self.ws.jobs is not None else {}
        approvals = (
            self.ws.permissions.pending() if self.ws.permissions is not None else []
        )
        models = self.ws.models.list()
        usable = [m for m in models if self.ws.runtime_availability(m)[0]]
        research = self.ws.research.stats() if self.ws.research is not None else {}
        return {
            **info,
            "version": __version__,
            "jobs": jobs,
            "approvals_pending": len(approvals),
            "models_total": len(models),
            "models_usable": len(usable),
            "research": research,
            "play": self.ws.play_mode.stats(),
            "media": self.ws.voice.stats(),
            "datasets": self.ws.data.stats(),
            "training": self.ws.trainer.stats(),
            "remote": self.ws.remotes.stats(),
            "execution": self.ws.exec_env.stats(),
            "simulated_allowed": self.ws.allow_test_double,
            "net_fetch_granted": self._net_fetch_granted(),
        }

    def _net_fetch_granted(self) -> bool:
        if self.ws.permissions is None:
            return False
        return any(
            grant.capability == "net.fetch" and grant.active
            for grant in self.ws.permissions.grants(include_expired=False)
        )
