"""Workflow execution and outcome recording for training workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.training import (
    FINETUNE_METHODS,
    METHODS,
    TrainingJob,
)
from archx_agent.application.training.algorithms import train_records


class TrainingServiceRunnerMixin:
    """Runner responsibility for TrainingService."""

    def run(
        self,
        *,
        method: str,
        dataset: str,
        seed: int = 0,
        order: int = 3,
        smoothing: float = 0.1,
        label_source: str = "directory",
        notes: str = "",
        task_id: str | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        if method not in METHODS:
            raise ValidationError(
                f"unknown method {method!r} (this build knows {', '.join(METHODS)})"
            )
        where = (
            target or str(self.ws.config.get("training.target", "local") or "local")
        ).strip()
        if where not in ("local", "remote"):
            raise ValidationError(
                f"unknown training target {where!r}: a run happens on `local` (this CPU) or "
                "`remote` (an M37 worker); a sandbox is for commands, not for a trainer"
            )
        config = {
            "order": int(order),
            "smoothing": float(smoothing),
            "label_source": label_source,
            "seed": int(seed),
        }
        job = self.manager.create(
            method=method,
            dataset_id=dataset,
            config=config,
            seed=seed,
            base_model=None,
            notes=notes,
            task_id=task_id,
            target=where,
        )
        if method in FINETUNE_METHODS:
            return self._refuse(job, method)

        preflight = self.preflight(method=method, dataset=dataset)
        if not preflight["runnable"]:
            return self._refuse(job, method, preflight=preflight)
        self.manager.update(
            job.id, status="running", preflight=preflight, started_at=iso_now()
        )

        if where == "remote":
            return self._run_remote(
                job, dataset, method, config, preflight=preflight, task_id=task_id
            )

        try:
            result = self._train(job, dataset, method, config, task_id=task_id)
        except (ToolError, PermissionDeniedError, ApprovalRequiredError) as exc:
            self.manager.update(
                job.id, status="failed", error=str(exc), completed_at=iso_now()
            )
            raise
        except Exception as exc:  # noqa: BLE001 - a run that breaks is a row, not a traceback
            self.manager.update(
                job.id, status="failed", error=str(exc), completed_at=iso_now()
            )
            raise

        for split, values in result["metrics"].items():
            self.manager.record_metrics(job.id, values, split=split)
        artifact = self._write_artifact(job, result["artifact"])
        version_id = self._version(job, artifact)
        finished = self.manager.update(
            job.id,
            status="completed",
            metrics=result["metrics"],
            completed_at=iso_now(),
            artifact_path=artifact["path"],
            artifact_sha256=artifact["sha256"],
            version_id=version_id,
            preflight=preflight,
        )
        return self.view(finished.id)

    def _run_remote(
        self,
        job: TrainingJob,
        dataset: str,
        method: str,
        config: dict[str, Any],
        *,
        preflight: dict[str, Any],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Train on a worker, and record the result as this run - because it *is* this run.

        `--target remote` is the user asking, in one command, for the corpus to leave and the numbers
        to come back, so the bundle is approved as ``user:train-run`` rather than making them approve
        what they just asked for. What is never skipped is the check: the artifact is hashed here
        before a metric from it is written into the ledger.
        """
        try:
            exported = self.ws.remotes.export(
                dataset,
                method=method,
                order=int(config["order"]),
                smoothing=float(config["smoothing"]),
                seed=int(config["seed"]),
                label_source=str(config.get("label_source") or "record"),
            )
        except (
            ValidationError,
            ToolError,
            PermissionDeniedError,
            ApprovalRequiredError,
        ) as exc:
            return self._refuse(job, method, preflight=preflight, extra=str(exc))
        self.ws.remotes.approve(exported["id"], by="train-run")
        self.manager.update(job.id, status="running", remote_job_id=exported["id"])
        sent = self.ws.remotes.dispatch(exported["id"])
        if sent["status"] != "dispatched":
            return self._refuse(
                job,
                method,
                preflight=preflight,
                extra=f"the dispatch did not happen: {'; '.join(sent.get('reasons') or [])}",
            )
        collected = self.ws.remotes.collect(exported["id"])
        if collected["status"] != "verified":
            failed = self.manager.update(
                job.id,
                status="failed",
                completed_at=iso_now(),
                error=f"the remote result did not verify: {collected.get('verify_note')}",
                preflight=preflight,
            )
            return self.view(failed.id)

        metrics = dict((collected.get("outputs") or {}).get("metrics") or {})
        for split, values in metrics.items():
            self.manager.record_metrics(job.id, values, split=split)
        finished = self.manager.update(
            job.id,
            status="completed",
            metrics=metrics,
            completed_at=iso_now(),
            artifact_path=collected.get("artifact_path"),
            artifact_sha256=collected.get("received_sha256"),
            preflight=preflight,
            notes=f"trained on {collected.get('machine') or collected.get('endpoint')}"
            f" via {exported['id']}",
        )
        return self.view(finished.id)

    def _refuse(
        self,
        job: TrainingJob,
        method: str,
        *,
        preflight: dict[str, Any] | None = None,
        extra: str | None = None,
    ) -> dict[str, Any]:
        reasons = list(preflight["reasons"] if preflight else self.blockers(method))
        if extra:
            reasons.append(extra)
        refused = self.manager.update(
            job.id,
            status="refused",
            preflight=preflight
            or {"method": method, "runnable": False, "reasons": reasons},
            refusal="; ".join(reasons),
            completed_at=iso_now(),
            metrics={},
        )
        payload = self.view(refused.id)
        payload["reasons"] = reasons
        payload["status"] = "refused"
        return payload

    def _train(
        self,
        job: TrainingJob,
        dataset: str,
        method: str,
        config: dict[str, Any],
        *,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        view = self.ws.data.view(dataset)
        records = self.ws.data.records(view["id"], status="kept", limit=100_000)
        entries = [
            {
                "path": record["path"],
                "split": record["split"] or "train",
                "label": self._label(record, config.get("label_source") or "record"),
                "text": self._read_text(record["path"], task_id),
            }
            for record in records
        ]
        trained = train_records(entries, method, config)
        trained["artifact"]["trained_on"] = view["id"]
        trained["artifact"]["seed"] = int(config["seed"])
        return trained

    @staticmethod
    def _label(record: dict[str, Any], source: str) -> str | None:
        """Where a label came from, said out loud rather than inferred quietly."""
        if record.get("label"):
            return str(record["label"])
        if source == "directory":
            parent = str(Path(record["path"]).parent).replace("\\", "/")
            return parent.split("/")[-1] or None
        return None
