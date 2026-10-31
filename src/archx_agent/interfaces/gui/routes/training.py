"""HTTP endpoints for training. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.managers.training import METHODS


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class TrainingRoutes:
    @route(
        "GET",
        "/api/training/runs",
        "Training runs, newest first, with what this build can run.",
    )
    def get_training_runs(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        status = request.q("status")
        if status not in (
            None,
            "",
            "queued",
            "running",
            "completed",
            "failed",
            "refused",
        ):
            raise ApiError(400, "validation", "status must be a known training status")
        return {
            "runs": self.ws.trainer.jobs(
                status=status or None,
                dataset=request.q("dataset") or None,
                limit=request.q_int("limit", 20),
            ),
            "stats": self.ws.trainer.stats(),
            "methods": list(METHODS),
        }

    @route(
        "POST",
        "/api/training/runs",
        "Run a trainer here, or record the refusal with its reasons.",
    )
    def post_training_run(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.trainer.run(
            method=str(payload.get("method") or "ngram"),
            dataset=request.text("dataset", required=True) or "",
            seed=int(payload.get("seed") or 0),
            order=int(payload.get("order") or 3),
            smoothing=float(payload.get("smoothing") or 0.1),
            label_source=str(payload.get("label_source") or "directory"),
            notes=str(payload.get("notes") or ""),
        )

    @route(
        "GET",
        "/api/training/runs/{job_id}",
        "One run: its checks, metrics, artifact and reasons.",
    )
    def get_training_run(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.trainer.view(unquote(match.group("job_id")))

    @route(
        "GET", "/api/training/runs/{job_id}/metrics", "The metrics, grouped by split."
    )
    def get_training_metrics(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.trainer.metrics(unquote(match.group("job_id")))

    @route(
        "POST",
        "/api/training/preflight",
        "What would have to be true before a run means anything.",
    )
    def post_training_preflight(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.trainer.preflight(
            method=str(payload.get("method") or "ngram"),
            dataset=request.text("dataset", required=False),
            base_model=request.text("base_model", required=False),
        )
