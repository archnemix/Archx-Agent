"""SceneService: editing operations."""

from __future__ import annotations

from typing import Any
from archx_agent.application import geometry
from archx_agent.application.scene_validation import validate_document
from archx_agent.helpers.exceptions import (
    NotFoundError,
    ValidationError,
)
from archx_agent.managers.scenes import Scene

from .records import empty_document

class SceneServiceEditingMixin:
    def create(
        self, name: str, *, camera: dict[str, Any] | None = None, task_id: str | None = None
    ) -> dict[str, Any]:
        if task_id:
            self.ws.tasks.get(task_id)
        name = (name or "").strip()
        if not name:
            raise ValidationError("a scene needs a name")
        document = empty_document(name)
        if camera is not None:
            if not isinstance(camera, dict):
                raise ValidationError("camera must be a JSON object")
            document["camera"].update(camera)
        path = self._document_path(name)
        if any(item.name == name or item.path == path for item in self.manager.scenes()):
            raise ValidationError("a scene with this name or file path already exists")
        checksum = self._write_document(document, path)
        scene = self.manager.create(
            name=name, path=path, checksum=checksum, camera=document["camera"],
            metrics=self._totals([]), task_id=task_id,
        )
        result = self.view(scene.id)
        result.update(self._attach(task_id, path, "scene"))
        return result

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
        if not isinstance(primitive, str) or (name is not None and not isinstance(name, str)):
            raise ValidationError("primitive and name must be strings")
        object_name = (name or primitive).strip()
        transform = {} if transform is None else transform
        params = {} if params is None else params
        document["objects"].append({
            "name": object_name, "primitive": primitive, "params": params, "transform": transform,
        })
        # Validate the complete candidate before generating any new mesh or changing disk/rows.
        validate_document(document)
        mesh = geometry.build(primitive, params)
        world = mesh.transformed(geometry.transform_matrix(transform))
        metrics = geometry.metrics(world)
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
