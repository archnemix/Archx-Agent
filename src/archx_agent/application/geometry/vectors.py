"""Geometry vectors: deterministic, renderer-independent operations."""

from __future__ import annotations

import math

from archx_agent.application.geometry.constants import Point


def _cross(a: Point, b: Point) -> Point:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(a: Point) -> float:
    return math.sqrt(_dot(a, a))


def _normalise(vector: Point) -> Point:
    length = _length(vector)
    if length == 0.0:
        raise ValueError("a zero-length vector has no direction")
    return (vector[0] / length, vector[1] / length, vector[2] / length)
