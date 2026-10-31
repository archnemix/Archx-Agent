"""Artifacts operations for training workflows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from archx_agent.managers.training import (
    TrainingJob,
)


class TrainingServiceArtifactsMixin:
    """Artifacts responsibility for TrainingService."""

    def _read_text(self, path: str, task_id: str | None = None) -> str:
        run = self._execute(
            "fs.read", {"path": path}, self._context(f"training read {path}", task_id)
        )
        return str((run.result or {}).get("content") or "")

    def _write_artifact(
        self, job: TrainingJob, artifact: dict[str, Any]
    ) -> dict[str, Any]:
        body = json.dumps(artifact, indent=2, sort_keys=True)
        target = f"{job.id}.model.json"
        written = self._execute(
            "fs.write",
            {"path": target, "content": body, "create_parents": True},
            self._context(f"training artifact {target}", job.task_id),
        )
        output = dict(written.result or {})
        local = self._artifacts_dir() / target
        local.write_text(body, encoding="utf-8")
        return {
            "path": output.get("path") or target,
            "local": str(local),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "bytes": len(body.encode("utf-8")),
        }

    def _version(self, job: TrainingJob, artifact: dict[str, Any]) -> str | None:
        """Record the artifact as a version, so the file a metric came from cannot drift."""
        try:
            record = self.ws.versions.record(
                # `artifact` is an allowed version subject; the id names the run it belongs to.
                "artifact",
                f"{job.id}.model",
                content=Path(artifact["local"]).read_text(encoding="utf-8"),
                note=f"the model {job.method} wrote after the metrics were measured",
            )
        except Exception:  # noqa: BLE001 - versioning must not lose the run
            return None
        version = getattr(record, "version", None)
        return getattr(version, "version", None) or getattr(version, "id", None)
