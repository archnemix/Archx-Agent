"""Geometry mesh: deterministic, renderer-independent operations."""

from __future__ import annotations

from dataclasses import dataclass, field

from archx_agent.application.geometry.constants import Matrix, Point
from archx_agent.application.geometry.transforms import transform_point


@dataclass
class Mesh:
    """Vertices and faces. Faces may be quads or n-gons; anything that needs triangles asks."""

    vertices: list[Point] = field(default_factory=list)
    faces: list[tuple[int, ...]] = field(default_factory=list)

    def transformed(self, matrix: Matrix) -> "Mesh":
        return Mesh(
            vertices=[transform_point(matrix, vertex) for vertex in self.vertices],
            faces=list(self.faces),
        )

    def triangles(self) -> list[tuple[Point, Point, Point]]:
        points: list[tuple[Point, Point, Point]] = []
        for face in self.faces:
            for index in range(1, len(face) - 1):
                points.append(
                    (
                        self.vertices[face[0]],
                        self.vertices[face[index]],
                        self.vertices[face[index + 1]],
                    )
                )
        return points
