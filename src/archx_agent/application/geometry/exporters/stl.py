"""Geometry exporters stl: deterministic, renderer-independent operations."""

from __future__ import annotations

import struct
from typing import Any

from archx_agent.application.geometry.constants import Point
from archx_agent.application.geometry.exporters.formatting import face_normal


def to_stl(objects: list[dict[str, Any]]) -> bytes:
    """Binary STL: 84 bytes of header and count, then 50 bytes per triangle, no more, no less."""
    triangles: list[tuple[Point, Point, Point]] = []
    for item in objects:
        triangles.extend(item["mesh"].triangles())
    header = b"archx-agent M39 binary STL".ljust(80, b"\x00")
    chunks = [header, struct.pack("<I", len(triangles))]
    for tri in triangles:
        normal = face_normal(*tri)
        chunks.append(
            struct.pack(
                "<12fH",
                normal[0],
                normal[1],
                normal[2],
                tri[0][0],
                tri[0][1],
                tri[0][2],
                tri[1][0],
                tri[1][1],
                tri[1][2],
                tri[2][0],
                tri[2][1],
                tri[2][2],
                0,
            )
        )
    return b"".join(chunks)
