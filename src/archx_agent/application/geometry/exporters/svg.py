"""Geometry exporters svg: deterministic, renderer-independent operations."""

from __future__ import annotations

from typing import Any

from archx_agent.application.geometry.mesh import Mesh
from archx_agent.application.geometry.camera import project


def to_svg(
    objects: list[dict[str, Any]],
    *,
    camera: dict[str, Any],
    width: int = 480,
    height: int = 480,
) -> str:
    """A wireframe preview: a real projection, and honest about being only that.

    Edges are drawn once each (a shared edge is not drawn twice), sorted far-to-near so the picture
    reads correctly without a depth buffer. There is no lighting, no hidden-surface removal and no
    antialiasing, and the caption in the file says so rather than letting the picture imply a render.
    """
    eye = camera.get("location") or [4.0, -4.0, 3.0]
    target = camera.get("target") or [0.0, 0.0, 0.0]
    up = camera.get("up") or [0.0, 0.0, 1.0]
    fov = float(camera.get("fov") or 40.0)
    segments: list[tuple[float, float, float, float, float]] = []
    for item in objects:
        mesh: Mesh = item["mesh"]
        seen: set[tuple[int, int]] = set()
        for face in mesh.faces:
            for index, start in enumerate(face):
                end = face[(index + 1) % len(face)]
                edge = (start, end) if start <= end else (end, start)
                if edge in seen:
                    continue
                seen.add(edge)
                first = project(
                    mesh.vertices[edge[0]],
                    eye=eye,
                    target=target,
                    fov_degrees=fov,
                    width=width,
                    height=height,
                    up=up,
                )
                second = project(
                    mesh.vertices[edge[1]],
                    eye=eye,
                    target=target,
                    fov_degrees=fov,
                    width=width,
                    height=height,
                    up=up,
                )
                if not (first["visible"] and second["visible"]):
                    continue
                # A line's depth is the nearer endpoint: that is the one that decides what covers it.
                depth = min(first["depth"], second["depth"])
                segments.append(
                    (depth, first["x"], first["y"], second["x"], second["y"])
                )
    segments.sort(key=lambda item: -item[0])
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        "  <desc>wireframe projection computed by archx-agent M39 - no lighting, no hidden "
        "surfaces, not a render</desc>",
        f'  <rect width="{width}" height="{height}" fill="#101014"/>',
        '  <g stroke="#7fd6a8" stroke-width="1" fill="none">',
    ]
    for _depth, x1, y1, x2, y2 in segments:
        lines.append(
            f'    <line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>'
        )
    lines.append("  </g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"
