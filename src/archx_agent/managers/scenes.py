"""Rows for a scene: the document, the objects in it, and everything it produced.

A scene in this build is a **document with geometry in it**, not a picture of one. The document is
JSON on disk (objects, each a primitive with parameters and a transform, plus a camera and a light);
every number stored beside it - vertex count, triangle count, surface area, volume, bounding box,
watertight or not - was computed from those vertices by :mod:`archx_agent.application.geometry`.

Three tables:

``scenes``
    the document's path, the hash of the bytes that were written, and the totals. The hash is what
    makes "the scene has not changed since it was measured" a claim somebody can check.

``scene_objects``
    one row per object, with its own numbers. A scene-level "watertight: false" tells you something
    is wrong; this table tells you *which* object, and how many edges are open.

``scene_outputs``
    every file the scene produced - ``obj``, ``stl``, ``svg``, the generated Blender ``script`` and,
    when a Blender exists, ``render`` - with the hash of what was written and, for a render, the
    execution run that produced it (M38's ledger, because a render is a command that runs somewhere).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

SCENE_TABLES = ("scenes", "scene_objects", "scene_outputs")

#: What a scene can produce. `render` is only ever written by a run that a Blender actually started.
OUTPUT_KINDS = ("obj", "stl", "svg", "script", "render")
OUTPUT_STATUSES = ("written", "verified", "refused", "failed", "missing")


@dataclass
class Scene:
    id: str
    name: str
    path: str
    status: str
    created_at: str
    updated_at: str
    checksum: str | None = None
    objects: int = 0
    vertices: int = 0
    triangles: int = 0
    surface_area: float | None = None
    volume: float | None = None
    bounding_box: dict[str, Any] = field(default_factory=dict)
    camera: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "status": self.status,
            "checksum": self.checksum,
            "objects": self.objects,
            "vertices": self.vertices,
            "triangles": self.triangles,
            "surface_area": self.surface_area,
            "volume": self.volume,
            "bounding_box": dict(self.bounding_box),
            "camera": dict(self.camera),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "task_id": self.task_id,
        }


@dataclass
class SceneObject:
    id: str
    scene_id: str
    name: str
    primitive: str
    created_at: str
    params: dict[str, Any] = field(default_factory=dict)
    transform: dict[str, Any] = field(default_factory=dict)
    vertices: int = 0
    faces: int = 0
    triangles: int = 0
    surface_area: float | None = None
    volume: float | None = None
    watertight: bool = False
    open_edges: int = 0
    bounding_box: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scene_id": self.scene_id,
            "name": self.name,
            "primitive": self.primitive,
            "params": dict(self.params),
            "transform": dict(self.transform),
            "vertices": self.vertices,
            "faces": self.faces,
            "triangles": self.triangles,
            "surface_area": self.surface_area,
            "volume": self.volume,
            "watertight": bool(self.watertight),
            "open_edges": self.open_edges,
            "bounding_box": dict(self.bounding_box),
            "created_at": self.created_at,
        }


@dataclass
class SceneOutput:
    id: str
    scene_id: str
    kind: str
    status: str
    created_at: str
    path: str | None = None
    sha256: str | None = None
    bytes: int | None = None
    note: str | None = None
    execution_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scene_id": self.scene_id,
            "kind": self.kind,
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "status": self.status,
            "note": self.note,
            "execution_run_id": self.execution_run_id,
            "created_at": self.created_at,
        }


def _scene_from_row(row: Mapping[str, Any]) -> Scene:
    return Scene(
        id=row["id"],
        name=row["name"],
        path=row["path"],
        status=row["status"],
        checksum=row.get("checksum"),
        objects=int(row.get("objects") or 0),
        vertices=int(row.get("vertices") or 0),
        triangles=int(row.get("triangles") or 0),
        surface_area=row.get("surface_area"),
        volume=row.get("volume"),
        bounding_box=json.loads(row.get("bounding_box") or "{}"),
        camera=json.loads(row.get("camera") or "{}"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        task_id=row.get("task_id"),
    )


def _object_from_row(row: Mapping[str, Any]) -> SceneObject:
    return SceneObject(
        id=row["id"],
        scene_id=row["scene_id"],
        name=row["name"],
        primitive=row["primitive"],
        params=json.loads(row.get("params") or "{}"),
        transform=json.loads(row.get("transform") or "{}"),
        vertices=int(row.get("vertices") or 0),
        faces=int(row.get("faces") or 0),
        triangles=int(row.get("triangles") or 0),
        surface_area=row.get("surface_area"),
        volume=row.get("volume"),
        watertight=bool(row.get("watertight")),
        open_edges=int(row.get("open_edges") or 0),
        bounding_box=json.loads(row.get("bounding_box") or "{}"),
        created_at=row["created_at"],
    )


def _output_from_row(row: Mapping[str, Any]) -> SceneOutput:
    return SceneOutput(
        id=row["id"],
        scene_id=row["scene_id"],
        kind=row["kind"],
        path=row.get("path"),
        sha256=row.get("sha256"),
        bytes=row.get("bytes"),
        status=row["status"],
        note=row.get("note"),
        execution_run_id=row.get("execution_run_id"),
        created_at=row["created_at"],
    )


class SceneManager(BaseManager):
    """Scenes, the objects in them, and the files they produced."""

    tables = SCENE_TABLES

    def register_handlers(self) -> None:
        self.coordinator.register("scene.create", self._apply_scene)
        self.coordinator.register("scene.update", self._apply_scene_update)
        self.coordinator.register("scene.object", self._apply_object)
        self.coordinator.register("scene.object_remove", self._apply_object_remove)
        self.coordinator.register("scene.output", self._apply_output)
        self.coordinator.register("scene.output_update", self._apply_output_update)

    _SCENE_COLUMNS = ("id", "name", "path", "status", "checksum", "objects", "vertices",
                      "triangles", "surface_area", "volume", "bounding_box", "camera",
                      "created_at", "updated_at", "task_id")
    _OBJECT_COLUMNS = ("id", "scene_id", "name", "primitive", "params", "transform", "vertices",
                       "faces", "triangles", "surface_area", "volume", "watertight", "open_edges",
                       "bounding_box", "created_at")
    _OUTPUT_COLUMNS = ("id", "scene_id", "kind", "path", "sha256", "bytes", "status", "note",
                       "execution_run_id", "created_at")

    _JSON_COLUMNS = ("bounding_box", "camera", "params", "transform")
    _BOOL_COLUMNS = ("watertight",)

    def _values(self, columns: tuple[str, ...], item: Mapping[str, Any]) -> tuple[Any, ...]:
        values = []
        for name in columns:
            value = item.get(name)
            if name in self._JSON_COLUMNS:
                value = json_text(value or {})
            elif name in self._BOOL_COLUMNS:
                value = int(bool(value))
            values.append(value)
        return tuple(values)

    def _apply_scene(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        scene = payload["scene"]
        placeholders = ",".join("?" for _ in self._SCENE_COLUMNS)
        tx.execute(
            f"INSERT INTO scenes({','.join(self._SCENE_COLUMNS)}) VALUES ({placeholders})",
            self._values(self._SCENE_COLUMNS, scene),
        )
        return {"id": scene["id"]}

    def _apply_scene_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        scene = payload["scene"]
        assignments = ", ".join(f"{name} = ?" for name in self._SCENE_COLUMNS if name != "id")
        tx.execute(
            f"UPDATE scenes SET {assignments} WHERE id = ?",
            self._values(tuple(n for n in self._SCENE_COLUMNS if n != "id"), scene)
            + (scene["id"],),
        )
        return {"id": scene["id"]}

    def _apply_object(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        item = payload["object"]
        placeholders = ",".join("?" for _ in self._OBJECT_COLUMNS)
        tx.execute(
            f"INSERT INTO scene_objects({','.join(self._OBJECT_COLUMNS)})"
            f" VALUES ({placeholders})",
            self._values(self._OBJECT_COLUMNS, item),
        )
        return {"id": item["id"]}

    def _apply_object_remove(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute("DELETE FROM scene_objects WHERE id = ?", (payload["object_id"],))
        return {"id": payload["object_id"]}

    def _apply_output(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        item = payload["output"]
        placeholders = ",".join("?" for _ in self._OUTPUT_COLUMNS)
        tx.execute(
            f"INSERT INTO scene_outputs({','.join(self._OUTPUT_COLUMNS)})"
            f" VALUES ({placeholders})",
            tuple(item.get(name) for name in self._OUTPUT_COLUMNS),
        )
        return {"id": item["id"]}

    def _apply_output_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        item = payload["output"]
        assignments = ", ".join(f"{name} = ?" for name in self._OUTPUT_COLUMNS if name != "id")
        tx.execute(
            f"UPDATE scene_outputs SET {assignments} WHERE id = ?",
            tuple(item.get(name) for name in self._OUTPUT_COLUMNS if name != "id")
            + (item["id"],),
        )
        return {"id": item["id"]}

    # -- scenes -----------------------------------------------------------
    def create(
        self, *, name: str, path: str, status: str = "draft", checksum: str | None = None,
        metrics: dict[str, Any] | None = None, camera: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> Scene:
        existing = self.store.query_one("SELECT id FROM scenes WHERE name = ?", (name,))
        if existing is not None:
            raise ValidationError(
                f"a scene called {name!r} already exists ({existing['id']}): a name has to name one"
            )
        metrics = metrics or {}
        now = iso_now()
        scene = Scene(
            id=new_id("sc_"), name=name, path=path, status=status, checksum=checksum,
            objects=int(metrics.get("objects") or 0),
            vertices=int(metrics.get("vertices") or 0),
            triangles=int(metrics.get("triangles") or 0),
            surface_area=metrics.get("surface_area"),
            volume=metrics.get("volume"),
            bounding_box=dict(metrics.get("bounding_box") or {}),
            camera=dict(camera or {}),
            created_at=now, updated_at=now, task_id=task_id,
        )
        self._write("scene.create", {"scene": scene.to_dict()})
        self.trace("scene", "scene.created", status="ok", payload={"scene_id": scene.id})
        return scene

    def scene(self, wanted: str) -> Scene:
        row = self.store.query_one(
            "SELECT * FROM scenes WHERE id = ? OR name = ? ORDER BY rowid DESC LIMIT 1",
            (wanted, wanted),
        )
        if row is None:
            raise NotFoundError(f"no such scene: {wanted}")
        return _scene_from_row(row)

    def scenes(self) -> list[Scene]:
        return [
            _scene_from_row(row)
            for row in self.store.query("SELECT * FROM scenes ORDER BY rowid DESC")
        ]

    def update(self, scene_id: str, **changes: Any) -> Scene:
        scene = self.scene(scene_id)
        for name, value in changes.items():
            if not hasattr(scene, name):
                raise ValidationError(f"a scene has no {name!r}")
            setattr(scene, name, value)
        scene.updated_at = iso_now()
        self._write("scene.update", {"scene": scene.to_dict()})
        return scene

    def remember_metrics(self, scene_id: str, metrics: dict[str, Any],
                         checksum: str | None = None) -> Scene:
        """Write the totals that were just computed from the document."""
        return self.update(
            scene_id,
            objects=int(metrics.get("objects") or 0),
            vertices=int(metrics.get("vertices") or 0),
            triangles=int(metrics.get("triangles") or 0),
            surface_area=metrics.get("surface_area"),
            volume=metrics.get("volume"),
            bounding_box=dict(metrics.get("bounding_box") or {}),
            **({"checksum": checksum} if checksum else {}),
        )

    # -- objects ----------------------------------------------------------
    def add_object(
        self, *, scene_id: str, name: str, primitive: str, params: dict[str, Any],
        transform: dict[str, Any], metrics: dict[str, Any],
    ) -> SceneObject:
        self.scene(scene_id)
        clash = self.store.query_one(
            "SELECT id FROM scene_objects WHERE scene_id = ? AND name = ?", (scene_id, name)
        )
        if clash is not None:
            raise ValidationError(
                f"this scene already has an object called {name!r}; names are how an object is "
                "referred to, so they have to be unique inside a scene"
            )
        item = SceneObject(
            id=new_id("so_"), scene_id=scene_id, name=name, primitive=primitive,
            params=dict(params), transform=dict(transform),
            vertices=int(metrics.get("vertices") or 0),
            faces=int(metrics.get("faces") or 0),
            triangles=int(metrics.get("triangles") or 0),
            surface_area=metrics.get("surface_area"),
            volume=metrics.get("volume_abs"),
            watertight=bool(metrics.get("watertight")),
            open_edges=int(metrics.get("open_edges") or 0),
            bounding_box=dict(metrics.get("bounding_box") or {}),
            created_at=iso_now(),
        )
        self._write("scene.object", {"object": item.to_dict()})
        return item

    def objects(self, scene_id: str) -> list[SceneObject]:
        return [
            _object_from_row(row)
            for row in self.store.query(
                "SELECT * FROM scene_objects WHERE scene_id = ? ORDER BY rowid", (scene_id,)
            )
        ]

    def remove_object(self, scene_id: str, name: str) -> SceneObject:
        found = [item for item in self.objects(scene_id) if item.name == name]
        if not found:
            raise NotFoundError(f"no object called {name!r} in this scene")
        self._write("scene.object_remove", {"object_id": found[0].id})
        return found[0]

    # -- outputs ----------------------------------------------------------
    def record_output(
        self, *, scene_id: str, kind: str, status: str = "written", path: str | None = None,
        sha256: str | None = None, bytes: int | None = None, note: str | None = None,
        execution_run_id: str | None = None,
    ) -> SceneOutput:
        if kind not in OUTPUT_KINDS:
            raise ValidationError(f"a scene cannot produce {kind!r} (it knows {', '.join(OUTPUT_KINDS)})")
        item = SceneOutput(
            id=new_id("sx_"), scene_id=scene_id, kind=kind, status=status, path=path,
            sha256=sha256, bytes=bytes, note=note, execution_run_id=execution_run_id,
            created_at=iso_now(),
        )
        self._write("scene.output", {"output": item.to_dict()})
        return item

    def update_output(self, output_id: str, **changes: Any) -> SceneOutput:
        found = [item for item in self.all_outputs() if item.id == output_id]
        if not found:
            raise NotFoundError(f"no such scene output: {output_id}")
        item = found[0]
        for name, value in changes.items():
            if not hasattr(item, name):
                raise ValidationError(f"a scene output has no {name!r}")
            setattr(item, name, value)
        self._write("scene.output_update", {"output": item.to_dict()})
        return item

    def all_outputs(self) -> list[SceneOutput]:
        return [
            _output_from_row(row) for row in self.store.query("SELECT * FROM scene_outputs")
        ]

    def outputs(self, scene_id: str, *, kind: str | None = None) -> list[SceneOutput]:
        sql = "SELECT * FROM scene_outputs WHERE scene_id = ?"
        values: list[Any] = [scene_id]
        if kind:
            sql += " AND kind = ?"
            values.append(kind)
        sql += " ORDER BY rowid DESC"
        return [_output_from_row(row) for row in self.store.query(sql, tuple(values))]

    def stats(self) -> dict[str, Any]:
        totals = self.store.query_one(
            "SELECT COUNT(*) AS scenes, COALESCE(SUM(objects), 0) AS objects,"
            " COALESCE(SUM(vertices), 0) AS vertices, COALESCE(SUM(triangles), 0) AS triangles"
            " FROM scenes"
        ) or {}
        outputs = {
            row["kind"]: row["n"]
            for row in self.store.query(
                "SELECT kind, COUNT(*) AS n FROM scene_outputs GROUP BY kind ORDER BY kind"
            )
        }
        return {
            "scenes": int(totals.get("scenes") or 0),
            "objects": int(totals.get("objects") or 0),
            "vertices": int(totals.get("vertices") or 0),
            "triangles": int(totals.get("triangles") or 0),
            "outputs": outputs,
            "renders": int(self.store.query_one(
                "SELECT COUNT(*) AS n FROM scene_outputs WHERE kind = 'render'"
            )["n"]),
        }
