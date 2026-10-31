"""Artifacts operations for task history."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import NotFoundError
from archx_agent.helpers.jsonio import sha256_file
from archx_agent.helpers.result import Result
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.tasks.records import Artifact, _artifact_from_row


class TaskManagerArtifactsMixin:
    """Artifacts responsibility for TaskManager."""

    def attach_artifact(
        self,
        task_id: str,
        path: str,
        *,
        kind: str = "file",
        name: str | None = None,
        record_version: bool = True,
    ) -> Artifact:
        task = self.get(task_id)
        file_path = Path(path).expanduser()
        if not file_path.exists() or not file_path.is_file():
            raise NotFoundError(f"artifact file not found: {path}")
        size = file_path.stat().st_size
        checksum = sha256_file(file_path)
        rel_path = None
        if self.home:
            try:
                rel_path = str(
                    file_path.resolve().relative_to(Path(self.home).resolve())
                )
            except ValueError:
                rel_path = None
        metadata: dict[str, Any] = {}
        if record_version and self.versions is not None:
            try:
                write = self.versions.record(
                    "artifact",
                    str(file_path.resolve()),
                    path=file_path,
                    note=f"attached to task {task.id}",
                    created_by="task",
                )
                metadata["version_id"] = write.version.id
                metadata["version"] = write.version.version
                metadata["version_created"] = write.created
            except Exception as exc:  # noqa: BLE001 - versioning must not lose the artifact
                metadata["version_error"] = getattr(exc, "message", None) or str(exc)
        artifact = Artifact(
            id=new_id("ar_"),
            task_id=task.id,
            project_id=task.project_id,
            kind=(kind or "file").strip()[:40],
            name=(name or file_path.name)[:200],
            path=str(file_path.resolve()),
            rel_path=rel_path,
            checksum=checksum,
            size=size,
            mime=mimetypes.guess_type(str(file_path))[0],
            created_at=iso_now(),
            metadata=metadata,
        )
        self._write("task.artifact", {"artifact": artifact.to_dict()})
        self.log(
            task.id,
            "artifact",
            detail=f"{artifact.kind}: {artifact.name} ({size} bytes)",
        )
        self.trace(
            "artifact",
            "artifact.attached",
            status="ok",
            task_id=task.id,
            conversation_id=task.conversation_id,
            project_id=task.project_id,
            payload={
                "artifact_id": artifact.id,
                "path": artifact.path,
                "sha256": checksum,
            },
        )
        return artifact

    def artifacts(
        self, task_id: str | None = None, *, limit: int = 100
    ) -> list[Artifact]:
        if task_id:
            rows = self.store.query(
                "SELECT * FROM artifacts WHERE task_id = ? ORDER BY created_at, id LIMIT ?",
                (task_id, int(limit)),
            )
        else:
            rows = self.store.query(
                "SELECT * FROM artifacts ORDER BY created_at DESC, id LIMIT ?",
                (int(limit),),
            )
        return [_artifact_from_row(row) for row in rows]

    def artifact(self, artifact_id: str) -> Result[Artifact]:
        row = self.store.query_one(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        )
        if row is None:
            return Result.err(NotFoundError(f"no artifact {artifact_id}"))
        return Result.ok(_artifact_from_row(row))
