"""Scenes: geometry computed here, files written here, a render only where a renderer exists.

The milestone's hazard is a "3D workflow" that stores the word ``cube`` and shows a picture of one.
So the pipeline is arranged so that every claim has a file behind it:

``scene create`` / ``scene add``
    builds the document (objects, transforms, camera) and immediately measures it: vertex count,
    triangles, surface area, volume, bounding box, watertight or not - computed from the vertices by
    :mod:`archx_agent.application.geometry`, stored per object *and* as totals.

``scene export``
    writes OBJ, binary STL or the SVG preview, and records the sha256 of the bytes it wrote. The SVG
    is a perspective projection computed here and labelled a wireframe, because a picture that implies
    a render is the easiest lie in this whole area.

``scene verify``
    re-reads the document and every export from disk, recomputes the geometry, and **disagrees out
    loud** when a hash or a number moved. Exit code 3: nothing is broken, the scene changed.

``scene render``
    is a *command*, so it goes through M38's execution service: the Blender script is generated here,
    the argv is ``blender --background --factory-startup --python <script>``, and the run is a row in
    ``execution_runs`` like any other. With no Blender on the machine the run is ``refused`` with
    every reason named - which is the honest outcome, because the alternative is a PNG that was never
    rendered.
"""

from __future__ import annotations

import hashlib
import uuid
import json
import math
import shlex
from typing import Any

from archx_agent.application import geometry
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.managers.scenes import Scene
from archx_agent.managers.tools import ToolContext

#: The suffix each export kind gets. A file's name says what it is.
SUFFIXES = {"obj": ".obj", "stl": ".stl", "svg": ".svg", "script": "_blender.py", "render": ".png"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(name: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_"
                   for character in name.strip().lower()) or "scene"


def empty_document(name: str) -> dict[str, Any]:
    """A scene with no objects and a camera that can already see the origin."""
    return {
        "name": name,
        "format": "archx-scene/1",
        "units": "meters",
        "engine": "BLENDER_EEVEE_NEXT",
        "camera": {
            "location": [4.0, -4.0, 3.0],
            "target": [0.0, 0.0, 0.0],
            "up": [0.0, 0.0, 1.0],
            "fov": 40.0,
            "resolution": [480, 480],
        },
        "light": {"location": [4.0, -4.0, 3.0], "energy": 1000.0},
        "objects": [],
    }


class SceneService:
    """Scenes, from a primitive to a file whose hash can be checked."""

    def __init__(self, ws) -> None:
        self.ws = ws

    # -- plumbing ---------------------------------------------------------
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

    def _dir(self) -> str:
        return "scenes"

    def _document_path(self, name: str) -> str:
        return f"{self._dir()}/{_slug(name)}.json"

    # -- read / write the document ---------------------------------------
    def _write_document(self, document: dict[str, Any], path: str) -> str:
        body = json.dumps(document, indent=2, sort_keys=True) + "\n"
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
        probe = self._execute("fs.probe", {"path": scene.path}, "hashing scene document").result or {}
        return document, str(probe.get("sha256") or "")

    def _meshes(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        """Every object as a mesh in world space, with its own metrics."""
        built: list[dict[str, Any]] = []
        for item in document.get("objects") or []:
            mesh = geometry.build(item.get("primitive") or "", item.get("params") or {})
            matrix = geometry.transform_matrix(item.get("transform"))
            world = mesh.transformed(matrix)
            built.append({
                "name": item.get("name"),
                "primitive": item.get("primitive"),
                "params": dict(item.get("params") or {}),
                "transform": dict(item.get("transform") or {}),
                "mesh": world,
                "metrics": geometry.metrics(world),
            })
        return built

    def _totals(self, built: list[dict[str, Any]]) -> dict[str, Any]:
        """The scene's own numbers: sums, and a bounding box around every vertex."""
        if not built:
            return {
                "objects": 0, "vertices": 0, "triangles": 0, "surface_area": 0.0,
                "volume": 0.0, "bounding_box": {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0],
                                                "size": [0.0, 0.0, 0.0]},
                "watertight": False,
            }
        low = [min(item["metrics"]["bounding_box"]["min"][i] for item in built) for i in range(3)]
        high = [max(item["metrics"]["bounding_box"]["max"][i] for item in built) for i in range(3)]
        return {
            "objects": len(built),
            "vertices": sum(item["metrics"]["vertices"] for item in built),
            "triangles": sum(item["metrics"]["triangles"] for item in built),
            "surface_area": round(sum(item["metrics"]["surface_area"] for item in built), 9),
            # This is a sum of signed mesh volumes, not a boolean union: overlaps count twice.
            "volume": round(sum(item["metrics"]["volume"] for item in built), 9),
            "bounding_box": {
                "min": low,
                "max": high,
                "size": [round(high[i] - low[i], 9) for i in range(3)],
            },
            "watertight": all(item["metrics"]["watertight"] for item in built),
        }

    # -- scenes -----------------------------------------------------------
    def create(
        self, name: str, *, camera: dict[str, Any] | None = None, task_id: str | None = None
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValidationError("a scene needs a name")
        document = empty_document(name)
        if camera:
            document["camera"].update(camera)
        path = self._document_path(name)
        if any(item.name == name or item.path == path for item in self.manager.scenes()):
            raise ValidationError("a scene with this name or file path already exists")
        checksum = self._write_document(document, path)
        scene = self.manager.create(
            name=name, path=path, checksum=checksum, camera=document["camera"],
            metrics=self._totals([]), task_id=task_id,
        )
        return self.view(scene.id)

    def list(self) -> list[dict[str, Any]]:
        return [scene.to_dict() for scene in self.manager.scenes()]

    def scene(self, wanted: str) -> Scene:
        return self.manager.scene(wanted)

    def view(self, wanted: str) -> dict[str, Any]:
        scene = self.scene(wanted)
        document, checksum = self._read_document(scene)
        built = self._meshes(document)
        data = scene.to_dict()
        data["checksum_now"] = checksum
        data["drifted"] = bool(scene.checksum and scene.checksum != checksum)
        data["document"] = document
        data["objects_detail"] = [
            {
                "name": item["name"],
                "primitive": item["primitive"],
                "params": item["params"],
                "transform": item["transform"],
                **item["metrics"],
            }
            for item in built
        ]
        data["measured"] = self._totals(built)
        data["outputs"] = [output.to_dict() for output in self.manager.outputs(scene.id)]
        return data

    def add(
        self, wanted: str, primitive: str, *, name: str | None = None,
        params: dict[str, Any] | None = None, transform: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        scene = self.scene(wanted)
        document, _checksum = self._read_document(scene)
        try:
            mesh = geometry.build(primitive, params or {})
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        object_name = (name or primitive).strip()
        if any((item.get("name") or "") == object_name for item in document.get("objects") or []):
            raise ValidationError(
                f"this scene already has an object called {object_name!r}; names are how an object "
                "is referred to"
            )
        transform = dict(transform or {})
        if set(transform) - {"location", "rotation", "scale"}:
            raise ValidationError("unknown transform field")
        for key in ("location", "rotation", "scale"):
            value = transform.get(key)
            if value is not None:
                try:
                    values = [float(v) for v in value]
                except (TypeError, ValueError) as exc:
                    raise ValidationError(f"transform.{key} takes three finite numbers") from exc
                if len(values) != 3 or not all(math.isfinite(v) for v in values):
                    raise ValidationError(f"transform.{key} takes three finite numbers")
                transform[key] = values
        world = mesh.transformed(geometry.transform_matrix(transform))
        metrics = geometry.metrics(world)
        document.setdefault("objects", []).append({
            "name": object_name,
            "primitive": primitive,
            "params": {key: float(value) if isinstance(value, float) else value
                       for key, value in (params or {}).items()},
            "transform": transform,
        })
        checksum = self._write_document(document, scene.path)
        self.manager.add_object(
            scene_id=scene.id, name=object_name, primitive=primitive,
            params=params or {}, transform=transform, metrics=metrics,
        )
        totals = self._totals(self._meshes(document))
        self.manager.remember_metrics(scene.id, totals, checksum=checksum)
        self.manager.update(scene.id, status="built", camera=document.get("camera") or {})
        return self.view(scene.id)

    def remove(self, wanted: str, name: str) -> dict[str, Any]:
        scene = self.scene(wanted)
        document, _checksum = self._read_document(scene)
        objects = [item for item in document.get("objects") or [] if item.get("name") != name]
        if len(objects) == len(document.get("objects") or []):
            raise NotFoundError(f"no object called {name!r} in this scene")
        document["objects"] = objects
        checksum = self._write_document(document, scene.path)
        self.manager.remove_object(scene.id, name)
        totals = self._totals(self._meshes(document))
        self.manager.remember_metrics(scene.id, totals, checksum=checksum)
        return self.view(scene.id)

    def measure(self, wanted: str) -> dict[str, Any]:
        """Recompute everything from the document on disk. No cached number is trusted."""
        scene = self.scene(wanted)
        document, checksum = self._read_document(scene)
        built = self._meshes(document)
        totals = self._totals(built)
        self.manager.remember_metrics(scene.id, totals, checksum=checksum)
        return {
            "scene": scene.name,
            "checksum": checksum,
            "objects": [
                {"name": item["name"], "primitive": item["primitive"], **item["metrics"]}
                for item in built
            ],
            **totals,
        }

    # -- exports ----------------------------------------------------------
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
        return data

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

    # -- verification -----------------------------------------------------
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

    # -- rendering --------------------------------------------------------
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
            return data

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
        return data

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
