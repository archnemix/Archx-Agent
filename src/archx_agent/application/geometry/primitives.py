"""Geometry primitives: deterministic, renderer-independent operations."""

from __future__ import annotations

import math
from typing import Any

from archx_agent.application.geometry.constants import (
    PARAMS,
    PRIMITIVES,
    Point,
    SEGMENT_PARAMS,
)
from archx_agent.application.geometry.mesh import Mesh


def cube(size: float = 2.0) -> Mesh:
    half = float(size) / 2.0
    vertices = [
        (-half, -half, -half),
        (half, -half, -half),
        (half, half, -half),
        (-half, half, -half),
        (-half, -half, half),
        (half, -half, half),
        (half, half, half),
        (-half, half, half),
    ]
    faces = [
        (0, 3, 2, 1),  # -Z
        (4, 5, 6, 7),  # +Z
        (0, 1, 5, 4),  # -Y
        (1, 2, 6, 5),  # +X
        (2, 3, 7, 6),  # +Y
        (3, 0, 4, 7),  # -X
    ]
    return Mesh(vertices=vertices, faces=faces)


def plane(size: float = 2.0) -> Mesh:
    half = float(size) / 2.0
    return Mesh(
        vertices=[
            (-half, -half, 0.0),
            (half, -half, 0.0),
            (half, half, 0.0),
            (-half, half, 0.0),
        ],
        faces=[(0, 1, 2, 3)],
    )


def uv_sphere(radius: float = 1.0, segments: int = 32, rings: int = 16) -> Mesh:
    radius = float(radius)
    segments, rings = int(segments), int(rings)
    if segments < 3 or rings < 2:
        raise ValueError("a uv_sphere needs at least 3 segments and 2 rings")
    vertices: list[Point] = [(0.0, 0.0, radius)]
    for ring in range(1, rings):
        phi = math.pi * ring / rings
        z = radius * math.cos(phi)
        r = radius * math.sin(phi)
        for segment in range(segments):
            theta = 2.0 * math.pi * segment / segments
            vertices.append((r * math.cos(theta), r * math.sin(theta), z))
    vertices.append((0.0, 0.0, -radius))
    bottom = len(vertices) - 1

    faces: list[tuple[int, ...]] = []
    for segment in range(segments):
        nxt = (segment + 1) % segments
        faces.append((0, 1 + segment, 1 + nxt))
    for ring in range(rings - 2):
        row = 1 + ring * segments
        following = row + segments
        for segment in range(segments):
            nxt = (segment + 1) % segments
            faces.append(
                (row + segment, following + segment, following + nxt, row + nxt)
            )
    last = 1 + (rings - 2) * segments
    for segment in range(segments):
        nxt = (segment + 1) % segments
        faces.append((last + segment, bottom, last + nxt))
    return Mesh(vertices=vertices, faces=faces)


def cylinder(radius: float = 1.0, depth: float = 2.0, segments: int = 32) -> Mesh:
    radius, depth, segments = float(radius), float(depth), int(segments)
    if segments < 3:
        raise ValueError("a cylinder needs at least 3 segments")
    half = depth / 2.0
    vertices: list[Point] = []
    for segment in range(segments):
        theta = 2.0 * math.pi * segment / segments
        vertices.append((radius * math.cos(theta), radius * math.sin(theta), -half))
    for segment in range(segments):
        theta = 2.0 * math.pi * segment / segments
        vertices.append((radius * math.cos(theta), radius * math.sin(theta), half))
    faces: list[tuple[int, ...]] = []
    for segment in range(segments):
        nxt = (segment + 1) % segments
        faces.append((segment, nxt, segments + nxt, segments + segment))
    faces.append(tuple(reversed(range(segments))))
    faces.append(tuple(range(segments, 2 * segments)))
    return Mesh(vertices=vertices, faces=faces)


def cone(radius: float = 1.0, depth: float = 2.0, segments: int = 32) -> Mesh:
    radius, depth, segments = float(radius), float(depth), int(segments)
    if segments < 3:
        raise ValueError("a cone needs at least 3 segments")
    half = depth / 2.0
    vertices: list[Point] = []
    for segment in range(segments):
        theta = 2.0 * math.pi * segment / segments
        vertices.append((radius * math.cos(theta), radius * math.sin(theta), -half))
    apex = len(vertices)
    vertices.append((0.0, 0.0, half))
    faces: list[tuple[int, ...]] = []
    for segment in range(segments):
        nxt = (segment + 1) % segments
        faces.append((segment, nxt, apex))
    faces.append(tuple(reversed(range(segments))))
    return Mesh(vertices=vertices, faces=faces)


def torus(
    major_radius: float = 1.0,
    minor_radius: float = 0.25,
    major_segments: int = 32,
    minor_segments: int = 16,
) -> Mesh:
    major, minor = float(major_radius), float(minor_radius)
    major_segments, minor_segments = int(major_segments), int(minor_segments)
    if major_segments < 3 or minor_segments < 3:
        raise ValueError("a torus needs at least 3 segments in each direction")
    vertices: list[Point] = []
    for i in range(major_segments):
        theta = 2.0 * math.pi * i / major_segments
        for j in range(minor_segments):
            phi = 2.0 * math.pi * j / minor_segments
            r = major + minor * math.cos(phi)
            vertices.append(
                (r * math.cos(theta), r * math.sin(theta), minor * math.sin(phi))
            )
    faces: list[tuple[int, ...]] = []
    for i in range(major_segments):
        next_i = (i + 1) % major_segments
        for j in range(minor_segments):
            next_j = (j + 1) % minor_segments
            faces.append(
                (
                    i * minor_segments + j,
                    next_i * minor_segments + j,
                    next_i * minor_segments + next_j,
                    i * minor_segments + next_j,
                )
            )
    return Mesh(vertices=vertices, faces=faces)


GENERATORS = {
    "cube": cube,
    "plane": plane,
    "uv_sphere": uv_sphere,
    "cylinder": cylinder,
    "cone": cone,
    "torus": torus,
}


def build(primitive: str, params: dict[str, Any] | None = None) -> Mesh:
    """One primitive, with its parameters validated rather than coerced."""
    if primitive not in GENERATORS:
        raise ValueError(
            f"unknown primitive {primitive!r} (this build can generate {', '.join(PRIMITIVES)})"
        )
    given = dict(params or {})
    allowed = PARAMS[primitive]
    unknown = sorted(set(given) - set(allowed))
    if unknown:
        raise ValueError(
            f"{primitive} has no parameter {', '.join(unknown)} "
            f"(it takes {', '.join(sorted(allowed))})"
        )
    resolved: dict[str, float] = {}
    for name, default in allowed.items():
        value = given.get(name, default)
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{primitive}.{name} must be a number, not {value!r}"
            ) from exc
        if not math.isfinite(number):
            raise ValueError(f"{primitive}.{name} must be finite")
        if name in SEGMENT_PARAMS:
            if int(number) != number:
                raise ValueError(
                    f"{primitive}.{name} must be a whole number, not {number}"
                )
            number = int(number)
            if number > 256:
                raise ValueError(f"{primitive}.{name} must be at most 256")
            if number < 3:
                raise ValueError(f"{primitive}.{name} must be at least 3, not {number}")
        elif number <= 0:
            raise ValueError(f"{primitive}.{name} must be positive, not {number}")
        resolved[name] = number
    return GENERATORS[primitive](**resolved)
