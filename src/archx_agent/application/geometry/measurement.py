"""Geometry measurement: deterministic, renderer-independent operations."""

from __future__ import annotations

from typing import Any

from archx_agent.application.geometry.mesh import Mesh
from archx_agent.application.geometry.vectors import _cross, _dot, _length, _sub


def edge_counts(mesh: Mesh) -> dict[tuple[int, int], int]:
    """How many faces share each undirected edge. Watertight is "all of them are 2"."""
    counts: dict[tuple[int, int], int] = {}
    for face in mesh.faces:
        for index, start in enumerate(face):
            end = face[(index + 1) % len(face)]
            edge = (start, end) if start <= end else (end, start)
            counts[edge] = counts.get(edge, 0) + 1
    return counts


def surface_area(mesh: Mesh) -> float:
    total = 0.0
    for a, b, c in mesh.triangles():
        total += _length(_cross(_sub(b, a), _sub(c, a))) / 2.0
    return total


def volume(mesh: Mesh) -> float:
    """Signed volume by the divergence theorem: sum of dot(a, cross(b, c)) / 6 over triangles.

    The sign follows the winding, so an inverted mesh reports a negative volume instead of quietly
    reporting the same number as a correct one - and ``abs`` is taken only where the *size* is asked
    for, with the sign kept separately.
    """
    total = 0.0
    for a, b, c in mesh.triangles():
        total += _dot(a, _cross(b, c)) / 6.0
    return total


def bounding_box(mesh: Mesh) -> dict[str, list[float]]:
    if not mesh.vertices:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0], "size": [0.0, 0.0, 0.0]}
    low = [min(vertex[i] for vertex in mesh.vertices) for i in range(3)]
    high = [max(vertex[i] for vertex in mesh.vertices) for i in range(3)]
    return {
        "min": [round(value, 9) for value in low],
        "max": [round(value, 9) for value in high],
        "size": [round(high[i] - low[i], 9) for i in range(3)],
    }


def centroid(mesh: Mesh) -> list[float]:
    """The mean of the vertices. Named so nobody mistakes it for the centre of mass."""
    if not mesh.vertices:
        return [0.0, 0.0, 0.0]
    count = float(len(mesh.vertices))
    return [
        round(sum(vertex[i] for vertex in mesh.vertices) / count, 9) for i in range(3)
    ]


def metrics(mesh: Mesh) -> dict[str, Any]:
    """Everything this build will claim about a mesh, all of it recomputable from the vertices."""
    counts = edge_counts(mesh)
    open_edges = sum(1 for shared in counts.values() if shared != 2)
    signed = volume(mesh)
    return {
        "vertices": len(mesh.vertices),
        "faces": len(mesh.faces),
        "triangles": len(mesh.triangles()),
        "edges": len(counts),
        "open_edges": open_edges,
        "watertight": open_edges == 0 and bool(mesh.faces),
        "bounding_box": bounding_box(mesh),
        "surface_area": round(surface_area(mesh), 9),
        "volume": round(signed, 9),
        "volume_abs": round(abs(signed), 9),
        "centroid": centroid(mesh),
    }
