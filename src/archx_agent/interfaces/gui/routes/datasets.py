"""HTTP endpoints for datasets. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class DatasetsRoutes:
    @route("GET", "/api/datasets", "Datasets this home has prepared, newest first.")
    def get_datasets(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return {
            "datasets": self.ws.data.list(limit=request.q_int("limit", 20)),
            "roots": self.ws.tools.roots(),
            "stats": self.ws.data.stats(),
        }

    @route("POST", "/api/datasets", "Create a dataset over one or more source paths.")
    def post_dataset(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        sources = request.payload().get("sources") or (
            [request.text("source", required=True)]
            if request.text("source", required=False)
            else []
        )
        return self.ws.data.create(
            request.text("name", required=True) or "",
            [str(source) for source in sources],
            license=request.text("license", required=False),
            notes=request.text("notes", required=False),
        )

    @route(
        "GET", "/api/datasets/{dataset_id}", "One dataset: counts, splits, the ledger."
    )
    def get_dataset(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.data.view(unquote(match.group("dataset_id")))

    @route(
        "GET", "/api/datasets/{dataset_id}/records", "The candidates, kept and dropped."
    )
    def get_dataset_records(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        dataset_id = unquote(match.group("dataset_id"))
        status = request.q("status")
        if status not in (None, "", "kept", "dropped"):
            raise ApiError(400, "validation", "status must be kept or dropped")
        split = request.q("split")
        if split not in (None, "", "train", "val", "test"):
            raise ApiError(400, "validation", "split must be train, val or test")
        return {
            "dataset_id": dataset_id,
            "records": self.ws.data.records(
                dataset_id,
                status=status or None,
                split=split or None,
                limit=request.q_int("limit", 100),
            ),
        }

    @route(
        "POST",
        "/api/datasets/{dataset_id}/scan",
        "Measure every candidate (needs fs.read).",
    )
    def post_dataset_scan(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.data.scan(unquote(match.group("dataset_id")))

    @route(
        "POST",
        "/api/datasets/{dataset_id}/clean",
        "Apply the rules; removals keep their reason.",
    )
    def post_dataset_clean(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.data.clean(
            unquote(match.group("dataset_id")),
            min_chars=int(payload.get("min_chars") or 0),
            dedupe=bool(payload.get("dedupe", True)),
            normalize=bool(payload.get("normalize", False)),
            drop_empty=bool(payload.get("drop_empty", True)),
            require_license=bool(payload.get("require_license", False)),
        )

    @route(
        "POST",
        "/api/datasets/{dataset_id}/split",
        "Stable, seeded split; a leak is a refusal.",
    )
    def post_dataset_split(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        payload = request.payload()
        return self.ws.data.split(
            unquote(match.group("dataset_id")),
            train=float(payload.get("train", 0.8)),
            val=float(payload.get("val", 0.1)),
            test=float(payload.get("test", 0.1)),
            seed=str(payload.get("seed", "0")),
        )

    @route(
        "POST",
        "/api/datasets/{dataset_id}/build",
        "Write the export, record the manifest hash.",
    )
    def post_dataset_build(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.data.build(
            unquote(match.group("dataset_id")),
            force=bool(request.payload().get("force", False)),
        )

    @route(
        "GET",
        "/api/datasets/{dataset_id}/verify",
        "Recompute the manifest and disagree if it moved.",
    )
    def get_dataset_verify(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.data.verify(unquote(match.group("dataset_id")))

    @route(
        "GET",
        "/api/datasets/{dataset_id}/steps",
        "The ledger of steps that shaped the set.",
    )
    def get_dataset_steps(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        dataset_id = unquote(match.group("dataset_id"))
        return {"dataset_id": dataset_id, "steps": self.ws.data.steps(dataset_id)}
