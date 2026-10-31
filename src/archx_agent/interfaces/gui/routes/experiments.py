"""HTTP endpoints for experiments. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class ExperimentsRoutes:
    @route(
        "GET",
        "/api/experiments",
        "Experiments, with the counts that make them readable.",
    )
    def get_experiments(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        status = request.q("status")
        if status not in (None, "", "open", "closed"):
            raise ApiError(400, "validation", "status must be open or closed")
        rows = self.ws.experiment.list(
            status=status or None, limit=request.q_int("limit", 20)
        )
        counts = self.ws.experiments.run_counts()
        return {
            "experiments": [
                {**row.to_dict(), "stats": counts.get(row.id, {"runs": 0, "failed": 0})}
                for row in rows
            ],
            "roots": self.ws.tools.roots(),
            "stats": self.ws.experiment.stats(),
        }

    @route(
        "POST",
        "/api/experiments",
        "Declare an experiment: a command, its parameters, its metrics.",
    )
    def post_experiment(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        params = request.payload().get("params")
        if params is not None and not isinstance(params, list):
            raise ApiError(400, "validation", "params must be a list of objects")
        metrics = request.payload().get("metrics")
        if metrics is not None and not isinstance(metrics, dict):
            raise ApiError(400, "validation", "metrics must be an object")
        experiment = self.ws.experiment.create(
            request.text("name", required=True) or "",
            request.text("command", required=True) or "",
            root=request.text("root", required=False),
            hypothesis=request.text("hypothesis", required=False),
            params=params,
            metrics=metrics,
        )
        return experiment.to_dict()

    @route(
        "GET",
        "/api/experiments/{experiment_id}",
        "One experiment: its runs, metrics and counts.",
    )
    def get_experiment(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.experiment.show(unquote(match.group("experiment_id")))

    @route("POST", "/api/experiments/{experiment_id}/run", "Run the experiment once.")
    def post_experiment_run(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        experiment_id = unquote(match.group("experiment_id"))
        params = request.payload().get("params")
        if params is not None and not isinstance(params, dict):
            raise ApiError(400, "validation", "params must be an object")
        timeout = request.payload().get("timeout")
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            raise ApiError(400, "validation", "timeout must be a positive integer")
        run = self.ws.experiment.run(
            experiment_id,
            params,
            timeout=timeout,
            seed=request.text("seed", required=False),
            note=request.text("note", required=False),
        )
        return run.to_dict()

    @route(
        "GET",
        "/api/experiments/{experiment_id}/compare",
        "Line the runs up and name the best.",
    )
    def get_experiment_compare(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.experiment.compare(
            unquote(match.group("experiment_id")),
            metric=request.q("metric") or None,
            minimise=request.q_bool("minimise", False),
            limit=request.q_int("limit", 50),
        )

    @route(
        "GET", "/api/experiments/{experiment_id}/runs", "Every run of an experiment."
    )
    def get_experiment_runs(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        runs = self.ws.experiment.runs(
            unquote(match.group("experiment_id")), limit=request.q_int("limit", 50)
        )
        return {"runs": [run.to_dict() for run in runs]}

    @route(
        "POST",
        "/api/experiments/{experiment_id}/close",
        "Close it; the runs stay readable.",
    )
    def post_experiment_close(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.experiment.close(unquote(match.group("experiment_id"))).to_dict()

    @route(
        "POST", "/api/experiments/{experiment_id}/reopen", "Reopen a closed experiment."
    )
    def post_experiment_reopen(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.experiment.reopen(
            unquote(match.group("experiment_id"))
        ).to_dict()

    @route(
        "DELETE",
        "/api/experiments/{experiment_id}",
        "Delete an experiment and its runs.",
    )
    def delete_experiment(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        experiment_id = unquote(match.group("experiment_id"))
        self.ws.experiment.delete(experiment_id)
        return {"deleted": experiment_id}
