"""HTTP endpoints for remote. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class RemoteRoutes:
    @route(
        "GET",
        "/api/remote/jobs",
        "Remote jobs, newest first, with why nothing is dispatched.",
    )
    def get_remote_jobs(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        service = self.ws.remotes
        status = request.q("status")
        from archx_agent.managers.remote import STATUSES

        if status not in (None, "") and status not in STATUSES:
            raise ApiError(400, "validation", "status must be a known remote status")
        return {
            "jobs": service.jobs(
                status=status or None, limit=request.q_int("limit", 20)
            ),
            "stats": service.stats(),
            "attempts": service.attempts(limit=request.q_int("limit", 20)),
        }

    @route(
        "POST", "/api/remote/export", "Write one portable bundle for a built dataset."
    )
    def post_remote_export(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.remotes.export(
            request.text("dataset", required=True) or "",
            method=str(payload.get("method") or "ngram"),
            order=int(payload.get("order") or 3),
            smoothing=float(payload.get("smoothing") or 0.1),
            seed=int(payload.get("seed") or 0),
        )

    @route(
        "GET",
        "/api/remote/jobs/{job_id}",
        "One remote job: hashes, endpoint and attempts.",
    )
    def get_remote_job(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.remotes.view(unquote(match.group("job_id")))

    @route(
        "POST",
        "/api/remote/jobs/{job_id}/approve",
        "Allow this bundle to leave the machine.",
    )
    def post_remote_approve(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.remotes.approve(unquote(match.group("job_id")), by="gui")

    @route(
        "POST",
        "/api/remote/jobs/{job_id}/dispatch",
        "Send the bundle and record the answer.",
    )
    def post_remote_dispatch(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.remotes.dispatch(
            unquote(match.group("job_id")),
            endpoint=payload.get("endpoint") or None,
        )

    @route(
        "POST",
        "/api/remote/jobs/{job_id}/collect",
        "Fetch the artifact and re-hash it here.",
    )
    def post_remote_collect(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.remotes.collect(unquote(match.group("job_id")))

    @route(
        "POST",
        "/api/remote/jobs/{job_id}/verify",
        "Re-read the artifact and compare it.",
    )
    def post_remote_verify(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.remotes.verify(unquote(match.group("job_id")))
