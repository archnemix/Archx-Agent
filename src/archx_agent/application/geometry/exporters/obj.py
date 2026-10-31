"""Geometry exporters obj: deterministic, renderer-independent operations."""

from __future__ import annotations

from typing import Any

from archx_agent.application.geometry.mesh import Mesh
from archx_agent.application.geometry.exporters.formatting import _fmt, face_normal


def to_obj(objects: list[dict[str, Any]], *, name: str = "scene") -> str:
    """Wavefront OBJ: the format a viewer, a slicer and Blender all read without a plugin.

    Vertex normals are written per face (``f v//vn``), which is what makes the file shade correctly
    in a viewer that knows nothing about this program.
    """
    lines = [
        "# archx-agent scene export (M39)",
        f"# objects: {len(objects)}",
        f"o {name}",
    ]
    vertex_base = 1
    normal_base = 1
    for item in objects:
        mesh: Mesh = item["mesh"]
        lines.append(f"g {item.get('name') or 'object'}")
        for vertex in mesh.vertices:
            lines.append(f"v {_fmt(vertex[0])} {_fmt(vertex[1])} {_fmt(vertex[2])}")
        for face in mesh.faces:
            normal = face_normal(*(mesh.vertices[i] for i in face[:3]))
            lines.append(f"vn {_fmt(normal[0])} {_fmt(normal[1])} {_fmt(normal[2])}")
        for face in mesh.faces:
            indices = " ".join(
                f"{vertex_base + index}//{normal_base}" for index in face
            )
            lines.append(f"f {indices}")
            normal_base += 1
        vertex_base += len(mesh.vertices)
    return "\n".join(lines) + "\n"
