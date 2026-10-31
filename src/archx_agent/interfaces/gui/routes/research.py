"""HTTP endpoints for research. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.application.researcher import ResearchBlocked


from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
)


from archx_agent.interfaces.gui.protocol import ApiError, Request, Response, route


class ResearchRoutes:
    @route("GET", "/api/research", "Research runs.")
    def get_research(
        self, request: Request, match: re.Match[str]
    ) -> list[dict[str, Any]]:
        closure = request.q("closed")
        closed = (
            None
            if closure in (None, "")
            else str(closure).lower() in {"1", "true", "yes"}
        )
        runs = self.ws.research.list(
            limit=request.q_int("limit", 20),
            status=request.q("status") or None,
            closed=closed,
        )
        return [run.to_dict() for run in runs]

    @route("POST", "/api/research", "Run a research question now, in this process.")
    def post_research(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        question = request.text("question", required=True) or ""
        mode = request.payload().get("mode") or None
        urls = request.payload().get("urls") or []
        if isinstance(urls, str):
            urls = [line.strip() for line in urls.splitlines() if line.strip()]
        if not isinstance(urls, list):
            raise ApiError(400, "validation", "urls must be a list of URLs")
        subquestions = request.payload().get("subquestions") or []
        if isinstance(subquestions, str):
            subquestions = [
                line.strip() for line in subquestions.splitlines() if line.strip()
            ]
        use_model = request.payload().get("use_model", True)
        try:
            result = self.ws.researcher.run(
                question,
                mode=mode,
                urls=[str(url) for url in urls],
                subquestions=[str(item) for item in subquestions] or None,
                model_id=request.payload().get("model_id") or None,
                use_model=bool(use_model),
                allow_private_hosts=request.payload().get("allow_private_hosts"),
            )
        except ApprovalRequiredError as exc:
            raise ApiError(403, "approval_required", exc.message) from exc
        except ResearchBlocked as blocked:
            # The run row already exists and says `failed`; the GUI reports the decision
            # that would unblock it rather than pretending the question was answered.
            raise ApiError(
                403,
                "approval_required",
                blocked.message,
                data={"run_id": blocked.run_id, "approval_id": blocked.approval_id},
            ) from blocked
        return result

    @route(
        "GET",
        "/api/research/{run_id}",
        "One run: its report, sources and verification.",
    )
    def get_research_run(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        run_id = unquote(match.group("run_id"))
        run = self.ws.research.get(run_id)
        sources = self.ws.research.sources(run_id)
        from archx_agent.application.researcher import ResearchRunner, citation_numbers

        labels = citation_numbers(sources)
        verification = ResearchRunner.verify(run.report or "", list(labels.values()))
        return {
            "run": run.to_dict(),
            "sources": [source.to_dict() for source in sources],
            "labels": {str(source_id): label for source_id, label in labels.items()},
            "verification": verification,
        }

    @route(
        "POST",
        "/api/research/{run_id}/close",
        "Mark a run done - your call, not the runner's.",
    )
    def post_research_close(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        run_id = unquote(match.group("run_id"))
        note = request.payload().get("note") or ""
        if not isinstance(note, str):
            raise ApiError(400, "validation", "note must be text")
        run = self.ws.research.close(run_id, note=note, by="user:gui")
        return run.to_dict()

    @route("POST", "/api/research/{run_id}/reopen", "Undo a close.")
    def post_research_reopen(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        run = self.ws.research.reopen(unquote(match.group("run_id")), by="user:gui")
        return run.to_dict()

    @route("GET", "/api/research/{run_id}/report", "The report itself, as text.")
    def get_report(self, request: Request, match: re.Match[str]) -> Response:
        run_id = unquote(match.group("run_id"))
        run = self.ws.research.get(run_id)
        return Response(
            body=(run.report or "").encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{run_id}.md"'},
        )
