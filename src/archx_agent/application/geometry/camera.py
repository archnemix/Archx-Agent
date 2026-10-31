"""Geometry camera: deterministic, renderer-independent operations."""

from __future__ import annotations

import math
from typing import Sequence

from archx_agent.application.geometry.constants import Point
from archx_agent.application.geometry.vectors import _cross, _dot, _normalise, _sub


def look_at(
    eye: Sequence[float], target: Sequence[float], up: Sequence[float] = (0.0, 0.0, 1.0)
) -> tuple[Point, Point, Point]:
    """A camera's basis: (right, up, forward). Z-up, which is what Blender uses."""
    position = (float(eye[0]), float(eye[1]), float(eye[2]))
    aim = (float(target[0]), float(target[1]), float(target[2]))
    forward = _normalise(_sub(aim, position))
    up_vector = (float(up[0]), float(up[1]), float(up[2]))
    right = _normalise(_cross(forward, up_vector))
    true_up = _cross(right, forward)
    return right, true_up, forward


def project(
    point: Sequence[float],
    *,
    eye: Sequence[float],
    target: Sequence[float],
    fov_degrees: float,
    width: int,
    height: int,
    up: Sequence[float] = (0.0, 0.0, 1.0),
) -> dict[str, float]:
    """Perspective projection to pixels, with the depth kept so a caller can sort by distance."""
    right, true_up, forward = look_at(eye, target, up)
    relative = _sub(
        (float(point[0]), float(point[1]), float(point[2])),
        (float(eye[0]), float(eye[1]), float(eye[2])),
    )
    depth = _dot(relative, forward)
    if depth <= 1e-9:
        # Behind the camera: reported as such rather than mirrored into view.
        return {"x": 0.0, "y": 0.0, "depth": depth, "visible": False}
    half_height = math.tan(math.radians(float(fov_degrees)) / 2.0) * depth
    half_width = half_height * (float(width) / float(height))
    x = _dot(relative, right) / half_width
    y = _dot(relative, true_up) / half_height
    return {
        "x": (x + 1.0) / 2.0 * float(width),
        "y": (1.0 - y) / 2.0 * float(height),
        "depth": depth,
        "visible": True,
    }
