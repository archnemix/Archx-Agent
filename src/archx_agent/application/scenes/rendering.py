"""SceneService: rendering operations."""

from __future__ import annotations

import uuid
import shlex
from typing import Any
from archx_agent.application import geometry
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolError,
)
from archx_agent.managers.scenes import Scene

from .records import _slug

class SceneServiceRenderingMixin:
    def render_blockers(self, scene: Scene, document: dict[str, Any]) -> list[str]:
        """Everything that would have to be true before a render is a render.

        Each reason is a sentence with the command that fixes it, and *all* of them are reported:
        turning on one switch and being told about the next is how a user learns to stop reading.
        """
        reasons: list[str] = []
        executable = str(self.ws.config.get("blender.executable", "") or "")
        if not executable:
            reasons.append(
                "no Blender binary is configured: `archx-agent config set blender.executable "
                "/path/to/blender` (this build does not ship one, and a render without it would be "
                "a picture of a command)"
            )
        else:
            from pathlib import Path

            if not Path(executable).expanduser().exists() and not __import__("shutil").which(executable):
                reasons.append(
                    f"the configured Blender binary does not exist: {executable}"
                )
        if not document.get("objects"):
            reasons.append("the scene has no objects, so a render would be a picture of nothing")
        if not bool(self.ws.config.get("execution.enabled", False)):
            reasons.append(
                "execution is off, and a render is a command: "
                "`archx-agent config set execution.enabled true`"
            )
        return reasons

    def render(
        self, wanted: str, *, target: str | None = None, task_id: str | None = None
    ) -> dict[str, Any]:
        """Generate the script, then run Blender through M38's execution service - or refuse."""
        scene = self.scene(wanted)
        task_id = task_id or scene.task_id
        if task_id:
            self.ws.tasks.get(task_id)
        document, _checksum = self._read_document(scene)
        reasons = self.render_blockers(scene, document)
        if target not in (None, "local"):
            reasons.append("scene render currently supports only the local target; remote binary transfer is not implemented")
        if reasons:
            output = self.manager.record_output(
                scene_id=scene.id, kind="render", status="refused", note="; ".join(reasons)
            )
            data = output.to_dict()
            data["reasons"] = reasons
            return self._render_event(task_id, data)

        # The script and the OBJ are written first: a render whose input does not exist is a command
        # that fails for a reason nobody can see.
        obj = self.export(wanted, "obj")
        # A unique destination prevents an old PNG from masquerading as this run's output.
        stem = f"{self._dir()}/{_slug(scene.name)}_{uuid.uuid4().hex}"
        render_path = stem + ".png"
        script = self._record(scene, "script", self._write_text(
            stem + "_blender.py",
            geometry.blender_script(document,
                obj_path=str(self.ws.tools.runtime.resolve(obj["path"])),
                render_path=str(self.ws.tools.runtime.resolve(render_path))),
            "Blender render script"))
        executable = str(self.ws.config.get("blender.executable", "") or "")
        argv = geometry.blender_argv(executable, str(self.ws.tools.runtime.resolve(script["path"])))
        run = self.ws.exec_env.run(
            shlex.join(argv), target="local", cwd=str(self.ws.tools.roots()[0]), timeout=600, task_id=task_id
        )
        status = "failed"
        digest = None
        size = None
        note = run.get("sentence")
        if run.get("status") == "ok":
            try:
                probe = self._execute("fs.probe", {"path": render_path}, "checking rendered PNG").result or {}
                if not str(probe.get("head_hex") or "").startswith("89 50 4e 47 0d 0a 1a 0a"):
                    raise ToolError("Blender exited zero but did not produce a PNG")
                digest, size = probe.get("sha256"), probe.get("bytes")
                status = "written"
            except (ToolError, PermissionDeniedError, ApprovalRequiredError) as exc:
                note = str(exc)
        elif run.get("status") == "refused":
            status = "refused"
        output = self.manager.record_output(
            scene_id=scene.id, kind="render", status=status,
            path=render_path if status == "written" else None,
            sha256=digest, bytes=size, note=note, execution_run_id=run.get("id"),
        )
        data = output.to_dict()
        data["run"] = run
        data["argv"] = argv
        data["script"] = script["path"]
        data["obj"] = obj["path"]
        if status == "written":
            data.update(self._attach(task_id, render_path, "scene.render"))
        return self._render_event(task_id, data)

    def renders(self, wanted: str | None = None) -> list[dict[str, Any]]:
        if wanted:
            scene = self.scene(wanted)
            outputs = self.manager.outputs(scene.id, kind="render")
        else:
            outputs = [item for item in self.manager.all_outputs() if item.kind == "render"]
        return [output.to_dict() for output in outputs]

    def stats(self) -> dict[str, Any]:
        data = self.manager.stats()
        executable = str(self.ws.config.get("blender.executable", "") or "")
        data["blender_configured"] = bool(executable)
        data["execution_enabled"] = bool(self.ws.config.get("execution.enabled", False))
        data["primitives"] = list(geometry.PRIMITIVES)
        return data
