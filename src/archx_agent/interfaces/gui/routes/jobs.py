"""HTTP endpoints for jobs. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class JobsRoutes:
    @route("GET", "/api/tasks", "Task history.")
    def get_tasks(self, request: Request, match: re.Match[str]) -> list[dict[str, Any]]:
        tasks = self.ws.tasks.list(
            status=request.q("status") or None,
            kind=request.q("kind") or None,
            limit=request.q_int("limit", 30),
        )
        return [task.to_dict() for task in tasks]

    @route(
        "GET",
        "/api/tasks/{task_id}",
        "One task: its record, timeline, tools and artifacts.",
    )
    def get_task(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        task_id = unquote(match.group("task_id"))
        task = self.ws.tasks.get(task_id)
        return {
            "task": task.to_dict(),
            "timeline": self.ws.tasks.timeline(task_id),
            "tools": self.ws.tasks.tool_runs(task_id),
            "artifacts": [
                artifact.to_dict() for artifact in self.ws.tasks.artifacts(task_id)
            ],
        }

    @route("GET", "/api/jobs", "The queue: what is queued, what ran, what failed.")
    def get_jobs(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        jobs = self.ws.jobs.list(
            status=request.q("status") or None,
            kind=request.q("kind") or None,
            limit=request.q_int("limit", 30),
        )
        return {
            "jobs": [job.to_dict() for job in jobs],
            "stats": self.ws.jobs.stats(),
            "queue": [job.to_dict() for job in self.ws.jobs.queue()],
        }

    @route(
        "POST", "/api/jobs/{job_id}/{action}", "pause, resume, cancel or retry one job."
    )
    def post_job_action(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        job_id = unquote(match.group("job_id"))
        action = match.group("action")
        handlers = {
            "pause": self.ws.jobs.pause,
            "resume": self.ws.jobs.resume,
            "cancel": self.ws.jobs.cancel,
            "retry": self.ws.jobs.retry,
        }
        handler = handlers.get(action)
        if handler is None:
            raise ApiError(404, "no_route", f"unknown job action {action!r}")
        return handler(job_id).to_dict()

    @route(
        "POST",
        "/api/jobs/drain",
        "Run queued jobs now, in this process, up to a limit.",
    )
    def post_jobs_drain(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        max_jobs = int(request.payload().get("max_jobs", 1))
        if max_jobs < 1 or max_jobs > 50:
            raise ApiError(400, "validation", "max_jobs must be between 1 and 50")
        from archx_agent.application.scheduler import JobRunner

        runner = JobRunner(self.ws)
        ran: list[dict[str, Any]] = []
        for _ in range(max_jobs):
            job = runner.run_once()
            if job is None:
                break
            ran.append(job.to_dict())
        return {"ran": ran, "stats": self.ws.jobs.stats()}
