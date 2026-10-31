"""Geometry constants: deterministic, renderer-independent operations."""

from __future__ import annotations


Point = tuple[float, float, float]

Matrix = tuple[tuple[float, float, float, float], ...]

PRIMITIVES = ("cube", "plane", "uv_sphere", "cylinder", "cone", "torus")

PARAMS: dict[str, dict[str, float]] = {
    "cube": {"size": 2.0},
    "plane": {"size": 2.0},
    "uv_sphere": {"radius": 1.0, "segments": 32, "rings": 16},
    "cylinder": {"radius": 1.0, "depth": 2.0, "segments": 32},
    "cone": {"radius": 1.0, "depth": 2.0, "segments": 32},
    "torus": {
        "major_radius": 1.0,
        "minor_radius": 0.25,
        "major_segments": 32,
        "minor_segments": 16,
    },
}

SEGMENT_PARAMS = ("segments", "rings", "major_segments", "minor_segments")

IDENTITY: Matrix = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)
