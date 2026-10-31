"""Geometry transforms: deterministic, renderer-independent operations."""

from __future__ import annotations

import math
from typing import Any, Sequence

from archx_agent.application.geometry.constants import Matrix, Point


def mat_mul(a: Matrix, b: Matrix) -> Matrix:
    return tuple(
        tuple(sum(a[row][k] * b[k][col] for k in range(4)) for col in range(4))
        for row in range(4)
    )


def mat_translate(x: float, y: float, z: float) -> Matrix:
    return (
        (1.0, 0.0, 0.0, x),
        (0.0, 1.0, 0.0, y),
        (0.0, 0.0, 1.0, z),
        (0.0, 0.0, 0.0, 1.0),
    )


def mat_scale(x: float, y: float, z: float) -> Matrix:
    return (
        (x, 0.0, 0.0, 0.0),
        (0.0, y, 0.0, 0.0),
        (0.0, 0.0, z, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def mat_rotate(axis: str, degrees: float) -> Matrix:
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    if axis == "x":
        return (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, cos, -sin, 0.0),
            (0.0, sin, cos, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    if axis == "y":
        return (
            (cos, 0.0, sin, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (-sin, 0.0, cos, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    if axis == "z":
        return (
            (cos, -sin, 0.0, 0.0),
            (sin, cos, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    raise ValueError(f"unknown rotation axis {axis!r} (use x, y or z)")


def transform_matrix(transform: dict[str, Any] | None) -> Matrix:
    """Scale, then rotation (X, then Y, then Z), then translation.

    Multiplying the scale matrix on the left would scale the *translation* too, and a cube at (2, 0, 0)
    scaled by 2 would jump to (4, 0, 0). The order is written down here because a scene's numbers
    are only reproducible if the convention is fixed.
    """
    transform = transform or {}
    location = [float(v) for v in (transform.get("location") or (0.0, 0.0, 0.0))]
    rotation = [float(v) for v in (transform.get("rotation") or (0.0, 0.0, 0.0))]
    scale = [float(v) for v in (transform.get("scale") or (1.0, 1.0, 1.0))]
    matrix = mat_translate(location[0], location[1], location[2])
    matrix = mat_mul(matrix, mat_rotate("z", rotation[2]))
    matrix = mat_mul(matrix, mat_rotate("y", rotation[1]))
    matrix = mat_mul(matrix, mat_rotate("x", rotation[0]))
    return mat_mul(matrix, mat_scale(scale[0], scale[1], scale[2]))


def transform_point(matrix: Matrix, point: Sequence[float]) -> Point:
    x, y, z = float(point[0]), float(point[1]), float(point[2])
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3],
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3],
    )
