"""SceneService: storage operations."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from archx_agent.application.scene_validation import validate_document
from archx_agent.helpers.exceptions import (
    ArchxError,
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.managers.scenes import Scene
from archx_agent.managers.tools import ToolContext

from .records import _sha, _slug

class SceneServiceStorageMixin:
    @property
    def manager(self):
        return self.ws.scenes

    def _execute(self, name: str, arguments: dict[str, Any], purpose: str):
        run = self.ws.tools.execute(
            name, arguments, context=ToolContext(purpose=purpose), requester="scenes"
        )
        if run.status == "denied":
            approval = getattr(run, "approval_id", None)
            if approval:
                raise ApprovalRequiredError(
                    f"{name} needs approval: approve {approval} or grant the capability",
                    approval_id=approval,
                )
            raise PermissionDeniedError(run.error or f"{name} was refused")
        if run.status == "failed":
            raise ToolError(run.error or f"{name} failed")
        return run

    def _attach(self, task_id: str | None, path: str, kind: str) -> dict[str, Any]:
        """Task artifacts are bookkeeping, not authority to read another path.

        The file must still be in a tool root. Failure to attach is reported without losing the
        already-written output ledger row. Never finish an existing task on behalf of its owner.
        """
        if not task_id:
            return {}
        try:
            resolved = self.ws.tools.runtime.resolve(path)
            artifact = self.ws.tasks.attach_artifact(
                task_id, str(resolved), kind=kind, name=resolved.name,
            )
            return {"task_id": task_id, "artifact_id": artifact.id}
        except (ArchxError, OSError) as exc:
            return {"task_id": task_id, "artifact_error": str(exc)}

    def _render_event(self, task_id: str | None, data: dict[str, Any]) -> dict[str, Any]:
        if task_id:
            data["task_id"] = task_id
            try:
                self.ws.tasks.log(task_id, "scene.render", detail=str(data.get("note") or data["status"]))
            except (ArchxError, OSError) as exc:
                data["task_log_error"] = str(exc)
        return data

    def _dir(self) -> str:
        return "scenes"

    def _document_path(self, name: str) -> str:
        return f"{self._dir()}/{_slug(name)}.json"

    def _write_document(self, document: dict[str, Any], path: str) -> str:
        validate_document(document)
        body = json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"
        self._execute(
            "fs.write", {"path": path, "content": body, "create_parents": True},
            f"writing scene {document.get('name')}",
        )
        return _sha(body)

    def _read_document(self, scene: Scene) -> tuple[dict[str, Any], str]:
        read = self._execute("fs.read", {"path": scene.path}, f"reading scene {scene.name}").result
        if (read or {}).get("truncated"):
            raise ValidationError(
                f"{scene.path} is larger than the reader's limit, so it cannot be measured whole"
            )
        text = str((read or {}).get("content") or "")
        try:
            document = json.loads(text)
        except ValueError as exc:
            raise ValidationError(f"{scene.path} is not valid scene JSON: {exc}") from exc
        validate_document(document)
        probe = self._execute("fs.probe", {"path": scene.path}, "hashing scene document").result or {}
        return document, str(probe.get("sha256") or "")

    def _write_text(self, path: str, body: str, what: str) -> dict[str, Any]:
        self._execute(
            "fs.write", {"path": path, "content": body, "create_parents": True}, f"writing {what}"
        )
        return {"path": path, "sha256": _sha(body), "bytes": len(body.encode("utf-8"))}

    def _write_bytes(self, path: str, payload: bytes, what: str) -> dict[str, Any]:
        """Binary output goes through ``fs.write_bytes``, never through a text encode.

        An STL written as text (``errors="replace"`` or a latin-1 round-trip) is a different file with
        the same name; the triangle count is recoverable but the bytes are not.
        """
        try:
            self._execute(
                "fs.write_bytes",
                {"path": path, "content_base64": __import__("base64").b64encode(payload).decode()},
                f"writing {what}",
            )
        except ToolError as exc:
            raise ToolError(
                f"{what} needs `fs.write_bytes`, which is not available here: {exc}"
            ) from exc
        triangles = max(0, (len(payload) - 84) // 50)
        return {
            "path": path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "triangles": triangles,
        }

    def _record(self, scene: Scene, kind: str, written: dict[str, Any],
                *, note: str | None = None) -> dict[str, Any]:
        output = self.manager.record_output(
            scene_id=scene.id, kind=kind, status="written", path=written["path"],
            sha256=written["sha256"], bytes=written["bytes"], note=note,
        )
        data = output.to_dict()
        data["note"] = data["note"] or note
        data["scene"] = scene.name
        data.update(self._attach(scene.task_id, written["path"], "scene." + kind))
        return data
