"""Geometry exporters formatting: deterministic, renderer-independent operations."""

from __future__ import annotations

from archx_agent.application.geometry.constants import Point
from archx_agent.application.geometry.vectors import _cross, _length, _sub


def _fmt(value: float) -> str:
    """Six decimals, no negative zero: a stable string, so a file's hash is a stable fact."""
    text = f"{value:.6f}"
    return "0.000000" if text == "-0.000000" else text


def face_normal(a: Point, b: Point, c: Point) -> Point:
    normal = _cross(_sub(b, a), _sub(c, a))
    length = _length(normal)
    if length == 0.0:
        return (0.0, 0.0, 0.0)
    return (normal[0] / length, normal[1] / length, normal[2] / length)
