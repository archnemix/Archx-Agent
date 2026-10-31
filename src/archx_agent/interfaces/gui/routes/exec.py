"""HTTP endpoints for exec. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class ExecRoutes:
    @route(
        "GET",
        "/api/exec/targets",
        "Which backends this machine could use, and why not.",
    )
    def get_exec_targets(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        service = self.ws.exec_env
        return {
            "probes": service.probes(),
            "targets": service.targets(),
            "stats": service.stats(),
        }

    @route(
        "POST",
        "/api/exec/targets",
        "Record a target (a refused one is recorded with its reason).",
    )
    def post_exec_target(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        payload = request.payload()
        spec = {
            key: payload[key]
            for key in ("image", "vm", "distro", "user", "network", "workdir")
            if payload.get(key)
        }
        target = self.ws.exec_env.ensure(
            str(payload.get("kind") or "local"),
            name=str(payload.get("name") or "") or None,
            endpoint=str(payload.get("endpoint") or "") or None,
            spec=spec,
        )
        return target.to_dict()

    @route("GET", "/api/exec/runs", "Every command, with the environment it ran in.")
    def get_exec_runs(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        service = self.ws.exec_env
        status = request.q("status")
        if status not in (None, "", "ok", "failed", "timeout", "refused", "detached"):
            raise ApiError(400, "validation", "status must be a known execution status")
        return {
            "runs": service.runs(
                target=request.q("target") or None,
                status=status or None,
                limit=request.q_int("limit", 20),
            ),
            "stats": service.stats(),
        }

    @route(
        "POST", "/api/exec/runs", "Run one command on a target and record where it ran."
    )
    def post_exec_run(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.exec_env.run(
            request.text("cmdline", required=True) or "",
            target=str(payload.get("target") or "") or None,
            cwd=request.text("cwd", required=False),
            timeout=int(payload.get("timeout") or 0) or None,
        )

    @route(
        "GET",
        "/api/exec/runs/{run_id}",
        "One run: the invocation, the output, the artifacts.",
    )
    def get_exec_run(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.exec_env.view(unquote(match.group("run_id")))

    @route(
        "POST",
        "/api/exec/push",
        "Send the project to a remote target, recording every hash.",
    )
    def post_exec_push(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.exec_env.push(
            str(payload.get("target") or "remote"),
            root=request.text("root", required=False),
        )

    @route(
        "POST",
        "/api/exec/pull",
        "Bring back what changed, refusing to clobber a local edit.",
    )
    def post_exec_pull(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.exec_env.pull(
            str(payload.get("target") or "remote"),
            root=request.text("root", required=False),
            force=bool(payload.get("force")),
        )
