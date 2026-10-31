"""SceneService: exports operations."""

from __future__ import annotations

from typing import Any
from archx_agent.application import geometry
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)

from .records import SUFFIXES, _sha, _slug

class SceneServiceExportsMixin:
    def export(self, wanted: str, kind: str) -> dict[str, Any]:
        scene = self.scene(wanted)
        if kind not in ("obj", "stl", "svg", "script"):
            raise ValidationError(
                f"this build writes obj, stl, svg and script; {kind!r} is not one of them "
                "(a render needs a Blender, and `scene render` says so)"
            )
        document, _checksum = self._read_document(scene)
        built = self._meshes(document)
        if not built:
            raise ValidationError("the scene has no objects yet, so there is nothing to export")
        stem = f"{self._dir()}/{_slug(scene.name)}"
        if kind == "obj":
            path = stem + SUFFIXES["obj"]
            body = geometry.to_obj(built, name=scene.name)
            written = self._write_text(path, body, "wavefront OBJ")
            return self._record(scene, "obj", written, note="wavefront OBJ, one group per object")
        if kind == "stl":
            path = stem + SUFFIXES["stl"]
            payload = geometry.to_stl(built)
            written = self._write_bytes(path, payload, "binary STL")
            return self._record(
                scene, "stl", written,
                note=f"binary STL, 84 + 50 bytes per triangle ({written['triangles']} triangles)",
            )
        if kind == "svg":
            path = stem + SUFFIXES["svg"]
            camera = document.get("camera") or {}
            resolution = camera.get("resolution") or [480, 480]
            body = geometry.to_svg(
                built, camera=camera, width=int(resolution[0]), height=int(resolution[1])
            )
            written = self._write_text(path, body, "SVG wireframe preview")
            return self._record(
                scene, "svg", written,
                note="a wireframe projection; not a render (no lighting, no hidden surfaces)",
            )
        path = stem + SUFFIXES["script"]
        body = geometry.blender_script(
            document, obj_path=str(self.ws.tools.runtime.resolve(stem + ".obj")),
            render_path=str(self.ws.tools.runtime.resolve(stem + ".png")),
        )
        written = self._write_text(path, body, "Blender script")
        return self._record(
            scene, "script", written,
            note="a Python program for a Blender that this machine may not have",
        )

    def outputs(self, wanted: str) -> list[dict[str, Any]]:
        scene = self.scene(wanted)
        return [output.to_dict() for output in self.manager.outputs(scene.id)]

    def preview(self, wanted: str) -> dict[str, Any]:
        """The SVG, as text, for a page that wants to draw it without a second request."""
        scene = self.scene(wanted)
        document, _checksum = self._read_document(scene)
        built = self._meshes(document)
        camera = document.get("camera") or {}
        resolution = camera.get("resolution") or [480, 480]
        svg = geometry.to_svg(
            built, camera=camera, width=int(resolution[0]), height=int(resolution[1])
        )
        return {
            "scene": scene.name,
            "kind": "svg",
            "svg": svg,
            "bytes": len(svg.encode("utf-8")),
            "sha256": _sha(svg),
            "note": "wireframe projection computed here; this is not a render",
        }

    def verify(self, wanted: str) -> dict[str, Any]:
        """Recompute, re-read every export, and disagree out loud.

        Returns ``ok = False`` when anything moved; the CLI turns that into exit code 3, because
        nothing is broken - the scene changed, and the row still says what it used to say.
        """
        scene = self.scene(wanted)
        problems: list[str] = []
        document, checksum = self._read_document(scene)
        if scene.checksum and scene.checksum != checksum:
            problems.append(
                f"the document hashes to {checksum[:16]} but the row recorded {scene.checksum[:16]}"
            )
        built = self._meshes(document)
        totals = self._totals(built)
        if scene.triangles and int(scene.triangles) != int(totals["triangles"]):
            problems.append(
                f"the document now has {totals['triangles']} triangles, the row recorded "
                f"{scene.triangles}"
            )
        checked: list[dict[str, Any]] = []
        seen_paths = set()
        for output in self.manager.outputs(scene.id):
            if output.path in seen_paths:
                continue
            seen_paths.add(output.path)
            if not output.path:
                continue
            try:
                probe = self._execute(
                    "fs.probe", {"path": output.path}, f"hashing {output.path} for verify"
                ).result or {}
            except (ToolError, PermissionDeniedError, ApprovalRequiredError) as exc:
                problems.append(f"{output.path} could not be read: {exc}")
                checked.append({"path": output.path, "kind": output.kind, "status": "missing"})
                continue
            measured = str(probe.get("sha256") or "")
            same = measured == (output.sha256 or "")
            if not same:
                problems.append(
                    f"{output.path}: measured hash {measured}, recorded hash {output.sha256}"
                )
            checked.append({
                "path": output.path, "kind": output.kind, "sha256": measured,
                "recorded": output.sha256, "status": "verified" if same else "drifted",
                "bytes": probe.get("bytes"),
            })
        return {
            "scene": scene.name,
            "ok": not problems,
            "problems": problems,
            "checksum": checksum,
            "triangles": totals["triangles"],
            "outputs": checked,
        }
