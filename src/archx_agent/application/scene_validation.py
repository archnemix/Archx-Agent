"""Validate persisted scene documents before geometry allocation or tool writes.

JSON syntax alone is not a scene schema. In particular, NaN, a scalar camera, a
parallel up-vector or millions of primitive instances must not reach the renderer.
Limits apply to the whole document, not just each individual generator.
"""
from __future__ import annotations

import math
from typing import Any

from archx_agent.application import geometry
from archx_agent.helpers.exceptions import ValidationError

MAX_OBJECTS = 128
MAX_VERTICES = 200_000
MAX_TRIANGLES = 400_000
MAX_MAGNITUDE = 1_000_000


def _mapping(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValidationError(f"{label} must be a finite number") from exc
    if not math.isfinite(number) or abs(number) > MAX_MAGNITUDE:
        raise ValidationError(f"{label} must be finite with magnitude at most {MAX_MAGNITUDE}")
    if positive and number <= 0:
        raise ValidationError(f"{label} must be positive")
    return number


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValidationError(f"{label} takes three finite numbers")
    return [_number(v, label) for v in value]


def _name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValidationError(f"{label} must be a nonempty name of at most 128 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValidationError(f"{label} cannot contain control characters")
    return value


def validate_document(document: Any) -> None:
    doc = _mapping(document, "scene document")
    if doc.get("format") != "archx-scene/1":
        raise ValidationError("scene format must be archx-scene/1")
    _name(doc.get("name"), "scene name")
    if doc.get("units") != "meters":
        raise ValidationError("scene units must be meters")
    if doc.get("engine") not in ("BLENDER_EEVEE_NEXT", "CYCLES", "BLENDER_WORKBENCH"):
        raise ValidationError("unknown scene render engine")
    camera = _mapping(doc.get("camera"), "camera")
    eye = _vector(camera.get("location"), "camera.location")
    target = _vector(camera.get("target"), "camera.target")
    up = _vector(camera.get("up"), "camera.up")
    try:
        geometry.look_at(eye, target, up)
    except ValueError as exc:
        raise ValidationError("camera must have distinct location/target and a nonparallel up vector") from exc
    fov = _number(camera.get("fov"), "camera.fov")
    if not 1 <= fov <= 179:
        raise ValidationError("camera.fov must be between 1 and 179 degrees")
    resolution = camera.get("resolution")
    if not isinstance(resolution, (list, tuple)) or len(resolution) != 2 or any(
        type(v) is not int or not 64 <= v <= 4096 for v in resolution
    ):
        raise ValidationError("camera.resolution takes two integer dimensions from 64 to 4096")
    light = _mapping(doc.get("light"), "light")
    _vector(light.get("location"), "light.location")
    _number(light.get("energy"), "light.energy", positive=True)
    objects = doc.get("objects")
    if not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
        raise ValidationError(f"objects must be a list of at most {MAX_OBJECTS} objects")
    names = set()
    vertex_total = triangle_total = 0
    for item in objects:
        obj = _mapping(item, "scene object")
        name = _name(obj.get("name"), "object name")
        if name in names:
            raise ValidationError(f"duplicate object name: {name}")
        names.add(name)
        primitive = obj.get("primitive")
        if not isinstance(primitive, str) or primitive not in geometry.PARAMS:
            raise ValidationError("unknown scene primitive")
        params = _mapping(obj.get("params", {}), "object.params")
        defaults = geometry.PARAMS[primitive]
        if set(params) - set(defaults):
            raise ValidationError(f"unknown {primitive} parameter")
        values = dict(defaults, **params)
        for key, value in values.items():
            number = _number(value, f"{primitive}.{key}", positive=True)
            if key in geometry.SEGMENT_PARAMS and (not number.is_integer() or not 3 <= number <= 256):
                raise ValidationError(f"{primitive}.{key} must be an integer from 3 to 256")
        transform = _mapping(obj.get("transform", {}), "object.transform")
        if set(transform) - {"location", "rotation", "scale"}:
            raise ValidationError("unknown transform field")
        for key, value in transform.items():
            _vector(value, "transform." + key)
        # Conservative preallocation budget; deliberately does not generate meshes to count them.
        if primitive in ("cube", "plane"):
            vertices, triangles = (8, 12) if primitive == "cube" else (4, 2)
        elif primitive == "uv_sphere":
            vertices = int(values["segments"]) * (int(values["rings"]) - 1) + 2
            triangles = 2 * int(values["segments"]) * (int(values["rings"]) - 1)
        elif primitive == "torus":
            vertices = int(values["major_segments"]) * int(values["minor_segments"])
            triangles = 2 * vertices
        else:
            vertices, triangles = 2 * int(values["segments"]), 4 * int(values["segments"])
        vertex_total += vertices
        triangle_total += triangles
        if vertex_total > MAX_VERTICES or triangle_total > MAX_TRIANGLES:
            raise ValidationError("scene exceeds the aggregate geometry budget")
