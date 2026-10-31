"""Evaluation operations for training workflows."""

from __future__ import annotations

import json
from typing import Any

from archx_agent.helpers.exceptions import (
    NotFoundError,
    ValidationError,
)
from archx_agent.managers.training import (
    TrainingJob,
)
from archx_agent.application.training.tokenization import tokenize
from archx_agent.application.training.ngram import NGramModel
from archx_agent.application.training.centroid import CentroidModel


class TrainingServiceEvaluationMixin:
    """Evaluation responsibility for TrainingService."""

    def view(self, wanted: str) -> dict[str, Any]:
        job = self.manager.resolve(wanted)
        payload = job.to_dict()
        payload["metric_rows"] = [row.to_dict() for row in self.manager.metrics(job.id)]
        payload["reasons"] = (
            []
            if job.status != "refused"
            else [
                part.strip() for part in (job.refusal or "").split("; ") if part.strip()
            ]
        )
        payload["sentence"] = self._sentence(job)
        return payload

    @staticmethod
    def _sentence(job: TrainingJob) -> str:
        if job.status == "completed":
            return f"{job.method} trained on {job.dataset_id} and wrote {job.artifact_path}"
        if job.status == "refused":
            return f"{job.method} was refused before it started: {job.refusal}"
        if job.status == "failed":
            return f"{job.method} started and failed: {job.error}"
        return f"{job.method} is {job.status}"

    def jobs(
        self, *, status: str | None = None, dataset: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        return [
            job.to_dict()
            for job in self.manager.jobs(status=status, dataset_id=dataset, limit=limit)
        ]

    def metrics(self, wanted: str) -> dict[str, Any]:
        job = self.manager.resolve(wanted)
        grouped: dict[str, dict[str, float]] = {}
        for row in self.manager.metrics(job.id):
            grouped.setdefault(row.split, {})[row.name] = row.value
        return {
            "job_id": job.id,
            "method": job.method,
            "status": job.status,
            "by_split": grouped,
        }

    def compare(self, job_ids: list[str]) -> dict[str, Any]:
        """Line runs up on one metric - and say plainly where a comparison is not possible."""
        jobs = [self.manager.resolve(wanted) for wanted in job_ids]
        if not jobs:
            raise ValidationError("nothing to compare")
        metric = "perplexity" if jobs[0].method == "ngram" else "accuracy"
        rows: list[dict[str, Any]] = []
        notes: list[str] = []
        for job in jobs:
            value = self.manager.latest_metric(job.id, metric, split="val")
            if value is None:
                value = self.manager.latest_metric(job.id, metric, split="test")
            rows.append(
                {
                    "job_id": job.id,
                    "method": job.method,
                    "status": job.status,
                    "metric": metric,
                    "value": value,
                }
            )
            if job.status != "completed":
                notes.append(
                    f"{job.id} did not run ({job.status}), so it has no {metric}"
                )
            if job.method != jobs[0].method:
                notes.append(
                    f"{job.id} is a {job.method} run: its {metric} is not comparable with a "
                    f"{jobs[0].method} run"
                )
        ranked = [row for row in rows if row["value"] is not None]
        lower_is_better = metric == "perplexity"
        best = None
        if len({row["method"] for row in rows}) > 1:
            # Two methods do not produce comparable numbers, so no winner is named even if only
            # one of them happens to have a value.
            notes.append("the runs use different methods, so no winner is named")
        elif not ranked:
            notes.append(f"no run has a {metric} to rank")
        elif len(ranked) < len(rows):
            notes.append(
                f"only {len(ranked)} of {len(rows)} runs produced a {metric}, so no winner is named"
            )
        else:
            best = (min if lower_is_better else max)(
                ranked, key=lambda row: row["value"]
            )["job_id"]
        return {
            "metric": metric,
            "lower_is_better": lower_is_better,
            "rows": rows,
            "best": best,
            "notes": notes,
        }

    def predict(self, wanted: str, text: str) -> dict[str, Any]:
        """Use the artifact the run wrote - re-read from disk, not from a copy in memory."""
        job = self.manager.resolve(wanted)
        if job.status != "completed":
            raise ValidationError(
                f"{job.id} is {job.status}; there is no artifact to use: {self._sentence(job)}"
            )
        if not job.artifact_path:
            raise NotFoundError(f"{job.id} recorded no artifact")
        raw = self._read_text(job.artifact_path)
        payload = json.loads(raw)
        kind = payload.get("kind")
        if kind == "ngram":
            model = NGramModel.from_dict(payload)
            return {
                "job_id": job.id,
                "kind": "ngram",
                "perplexity": model.perplexity(text),
                "tokens": len(tokenize(text)),
            }
        if kind == "centroid":
            model = CentroidModel.from_dict(payload)
            return {
                "job_id": job.id,
                "kind": "centroid",
                "label": model.predict(text),
                "labels": model.labels,
            }
        raise ValidationError(f"{job.artifact_path} is not a model this build can load")

    def stats(self) -> dict[str, Any]:
        base = self.manager.stats()
        base["enabled"] = bool(self.ws.config.get("training.enabled", False))
        base["base_model"] = str(self.ws.config.get("training.base_model", "") or "")
        base["weights_dir"] = str(self.ws.config.get("training.weights_dir", "") or "")
        base["can_finetune"] = False
        base["why_not"] = self.blockers("lora")
        return base
