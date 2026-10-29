"""Three-dimensional geometry, computed here, so a scene is a measurement rather than a description.

The hazard this module exists for is a "3D" feature that stores the *words* ``cube`` and ``sphere``
and calls the result a model. Nothing here trusts a name: a primitive is a vertex list and a face
list, a transform is a 4x4 matrix, and the numbers a scene reports - bounding box, surface area,
volume, watertightness - are recomputed from those vertices every time they are asked for.

Everything is dependency-free and deterministic:

* the mesh generators produce the same vertices in the same order on every machine, so an exported
  file's sha256 is a stable fact;
* **volume** is the signed-tetrahedron sum over the triangulated surface (positive for an outward
  orientation), and **area** is the sum of triangle areas - both are arithmetic anybody can repeat;
* **watertight** means every undirected edge is shared by exactly two faces. A mesh that is only
  *drawn* closed looks fine in a viewer and leaks in a slicer, so the check is on the topology;
* the **SVG preview** is a real perspective projection computed with the same camera the Blender
  script will use, and it is labelled a wireframe because that is what it is - no lighting, no
  hidden surfaces, no renderer.

Blender is not imported anywhere. ``blender_script`` emits a Python program for a Blender that may
exist on the user's machine; this build can generate, hash and verify that file, and cannot run it.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Any, Sequence

Point = tuple[float, float, float]
Matrix = tuple[tuple[float, float, float, float], ...]

#: The primitives this build can generate. A name is accepted only if it is in here: "torus" is a
#: mesh, "a nice lamp" is not.
PRIMITIVES = ("cube", "plane", "uv_sphere", "cylinder", "cone", "torus")

#: Parameters each primitive takes, with their defaults. `scene add` refuses an unknown parameter
#: instead of silently ignoring it, because a typo that produces the default is the worst outcome.
PARAMS: dict[str, dict[str, float]] = {
    "cube": {"size": 2.0},
    "plane": {"size": 2.0},
    "uv_sphere": {"radius": 1.0, "segments": 32, "rings": 16},
    "cylinder": {"radius": 1.0, "depth": 2.0, "segments": 32},
    "cone": {"radius": 1.0, "depth": 2.0, "segments": 32},
    "torus": {"major_radius": 1.0, "minor_radius": 0.25, "major_segments": 32,
              "minor_segments": 16},
}

#: Parameters that must be whole numbers >= 3 (a 2-segment sphere is a line, not a sphere).
SEGMENT_PARAMS = ("segments", "rings", "major_segments", "minor_segments")


# --------------------------------------------------------------------------
# matrices
# --------------------------------------------------------------------------
IDENTITY: Matrix = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


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
        return ((1.0, 0.0, 0.0, 0.0), (0.0, cos, -sin, 0.0),
                (0.0, sin, cos, 0.0), (0.0, 0.0, 0.0, 1.0))
    if axis == "y":
        return ((cos, 0.0, sin, 0.0), (0.0, 1.0, 0.0, 0.0),
                (-sin, 0.0, cos, 0.0), (0.0, 0.0, 0.0, 1.0))
    if axis == "z":
        return ((cos, -sin, 0.0, 0.0), (sin, cos, 0.0, 0.0),
                (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
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


# --------------------------------------------------------------------------
# meshes
# --------------------------------------------------------------------------
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
                points.append((self.vertices[face[0]], self.vertices[face[index]],
                               self.vertices[face[index + 1]]))
        return points


def cube(size: float = 2.0) -> Mesh:
    half = float(size) / 2.0
    vertices = [
        (-half, -half, -half), (half, -half, -half), (half, half, -half), (-half, half, -half),
        (-half, -half, half), (half, -half, half), (half, half, half), (-half, half, half),
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
        vertices=[(-half, -half, 0.0), (half, -half, 0.0), (half, half, 0.0), (-half, half, 0.0)],
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
            faces.append((row + segment, following + segment, following + nxt, row + nxt))
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
    major_radius: float = 1.0, minor_radius: float = 0.25,
    major_segments: int = 32, minor_segments: int = 16,
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
            vertices.append((r * math.cos(theta), r * math.sin(theta), minor * math.sin(phi)))
    faces: list[tuple[int, ...]] = []
    for i in range(major_segments):
        next_i = (i + 1) % major_segments
        for j in range(minor_segments):
            next_j = (j + 1) % minor_segments
            faces.append((
                i * minor_segments + j,
                next_i * minor_segments + j,
                next_i * minor_segments + next_j,
                i * minor_segments + next_j,
            ))
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
            raise ValueError(f"{primitive}.{name} must be a number, not {value!r}") from exc
        if not math.isfinite(number):
            raise ValueError(f"{primitive}.{name} must be finite")
        if name in SEGMENT_PARAMS:
            if int(number) != number:
                raise ValueError(f"{primitive}.{name} must be a whole number, not {number}")
            number = int(number)
            if number > 256:
                raise ValueError(f"{primitive}.{name} must be at most 256")
            if number < 3:
                raise ValueError(f"{primitive}.{name} must be at least 3, not {number}")
        elif number <= 0:
            raise ValueError(f"{primitive}.{name} must be positive, not {number}")
        resolved[name] = number
    return GENERATORS[primitive](**resolved)


# --------------------------------------------------------------------------
# measurements
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# camera and projection
# --------------------------------------------------------------------------
def _normalise(vector: Point) -> Point:
    length = _length(vector)
    if length == 0.0:
        raise ValueError("a zero-length vector has no direction")
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def look_at(eye: Sequence[float], target: Sequence[float],
            up: Sequence[float] = (0.0, 0.0, 1.0)) -> tuple[Point, Point, Point]:
    """A camera's basis: (right, up, forward). Z-up, which is what Blender uses."""
    position = (float(eye[0]), float(eye[1]), float(eye[2]))
    aim = (float(target[0]), float(target[1]), float(target[2]))
    forward = _normalise(_sub(aim, position))
    up_vector = (float(up[0]), float(up[1]), float(up[2]))
    right = _normalise(_cross(forward, up_vector))
    true_up = _cross(right, forward)
    return right, true_up, forward


def project(
    point: Sequence[float], *, eye: Sequence[float], target: Sequence[float],
    fov_degrees: float, width: int, height: int, up: Sequence[float] = (0.0, 0.0, 1.0),
) -> dict[str, float]:
    """Perspective projection to pixels, with the depth kept so a caller can sort by distance."""
    right, true_up, forward = look_at(eye, target, up)
    relative = _sub((float(point[0]), float(point[1]), float(point[2])),
                    (float(eye[0]), float(eye[1]), float(eye[2])))
    depth = _dot(relative, forward)
    if depth <= 1e-9:
        # Behind the camera: reported as such rather than mirrored into view.
        return {"x": 0.0, "y": 0.0, "depth": depth, "visible": False}
    half_height = math.tan(math.radians(float(fov_degrees)) / 2.0) * depth
    half_width = half_height * (float(width) / float(height))
    x = _dot(relative, right) / half_width
    y = _dot(relative, true_up) / half_height
    return {
        "x": (x + 1.0) / 2.0 * float(width),
        "y": (1.0 - y) / 2.0 * float(height),
        "depth": depth,
        "visible": True,
    }


# --------------------------------------------------------------------------
# export formats
# --------------------------------------------------------------------------
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
            indices = " ".join(f"{vertex_base + index}//{normal_base}" for index in face)
            lines.append(f"f {indices}")
            normal_base += 1
        vertex_base += len(mesh.vertices)
    return "\n".join(lines) + "\n"


def to_stl(objects: list[dict[str, Any]]) -> bytes:
    """Binary STL: 84 bytes of header and count, then 50 bytes per triangle, no more, no less."""
    triangles: list[tuple[Point, Point, Point]] = []
    for item in objects:
        triangles.extend(item["mesh"].triangles())
    header = b"archx-agent M39 binary STL".ljust(80, b"\x00")
    chunks = [header, struct.pack("<I", len(triangles))]
    for tri in triangles:
        normal = face_normal(*tri)
        chunks.append(struct.pack(
            "<12fH",
            normal[0], normal[1], normal[2],
            tri[0][0], tri[0][1], tri[0][2],
            tri[1][0], tri[1][1], tri[1][2],
            tri[2][0], tri[2][1], tri[2][2],
            0,
        ))
    return b"".join(chunks)


def to_svg(
    objects: list[dict[str, Any]], *, camera: dict[str, Any], width: int = 480,
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
                first = project(mesh.vertices[edge[0]], eye=eye, target=target, fov_degrees=fov,
                                width=width, height=height, up=up)
                second = project(mesh.vertices[edge[1]], eye=eye, target=target, fov_degrees=fov,
                                 width=width, height=height, up=up)
                if not (first["visible"] and second["visible"]):
                    continue
                # A line's depth is the nearer endpoint: that is the one that decides what covers it.
                depth = min(first["depth"], second["depth"])
                segments.append((depth, first["x"], first["y"], second["x"], second["y"]))
    segments.sort(key=lambda item: -item[0])
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '  <desc>wireframe projection computed by archx-agent M39 - no lighting, no hidden '
        'surfaces, not a render</desc>',
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


def blender_script(
    document: dict[str, Any], *, obj_path: str, render_path: str, engine: str | None = None,
) -> str:
    """A Python program for a Blender that is not this machine.

    It imports the OBJ this build exported (so the geometry is the geometry whose numbers were
    measured here, not something Blender regenerates), places the camera and the light from the
    document, sets the resolution and engine, and renders one frame to ``render_path``. Nothing in
    it needs `bpy` at generation time, which is why the file can be produced, hashed and verified on
    a machine that has no Blender at all.
    """
    camera = document.get("camera") or {}
    light = document.get("light") or {}
    resolution = camera.get("resolution") or [480, 480]
    chosen = engine or document.get("engine") or "BLENDER_EEVEE_NEXT"
    return f'''"""Generated by archx-agent M39: build the scene, set the camera, render one frame.

Run with:  blender --background --factory-startup --python this_file.py

The mesh is imported from the OBJ next to this file, so the geometry is the one whose bounding box,
area and volume this build measured. Everything else - camera, light, engine, resolution - comes
from the scene document, written into this file at generation time.
"""
import bpy

OBJ_PATH = {obj_path!r}
RENDER_PATH = {render_path!r}
CAMERA_LOCATION = {tuple(camera.get("location") or (4.0, -4.0, 3.0))!r}
CAMERA_TARGET = {tuple(camera.get("target") or (0.0, 0.0, 0.0))!r}
FOV_DEGREES = {float(camera.get("fov") or 40.0)!r}
RESOLUTION = {tuple(int(v) for v in resolution)!r}
ENGINE = {chosen!r}
LIGHT_LOCATION = {tuple(light.get("location") or (4.0, -4.0, 3.0))!r}
LIGHT_ENERGY = {float(light.get("energy") or 1000.0)!r}

# An empty file, so a machine with a user's startup scene behaves like a fresh one.
bpy.ops.wm.read_factory_settings(use_empty=True)

if OBJ_PATH.endswith(".obj"):
    bpy.ops.wm.obj_import(filepath=OBJ_PATH)
else:
    raise SystemExit("this script imports .obj only; re-export the scene as obj")

scene = bpy.context.scene
camera_data = bpy.data.cameras.new("ArchxCamera")
camera_data.sensor_fit = "VERTICAL"
camera_data.angle = FOV_DEGREES * 3.141592653589793 / 180.0
camera = bpy.data.objects.new("ArchxCamera", camera_data)
scene.collection.objects.link(camera)
camera.location = CAMERA_LOCATION
direction = (
    CAMERA_TARGET[0] - CAMERA_LOCATION[0],
    CAMERA_TARGET[1] - CAMERA_LOCATION[1],
    CAMERA_TARGET[2] - CAMERA_LOCATION[2],
)
camera.rotation_euler = __import__("mathutils").Vector(direction).to_track_quat("-Z", "Y").to_euler()
scene.camera = camera

light_data = bpy.data.lights.new("ArchxLight", type="AREA")
light_data.energy = LIGHT_ENERGY
light = bpy.data.objects.new("ArchxLight", light_data)
scene.collection.objects.link(light)
light.location = LIGHT_LOCATION

scene.render.engine = ENGINE
scene.render.resolution_x = RESOLUTION[0]
scene.render.resolution_y = RESOLUTION[1]
scene.render.filepath = RENDER_PATH
scene.render.image_settings.file_format = "PNG"
bpy.ops.render.render(write_still=True)
print("archx-agent: rendered", RENDER_PATH)
'''


def blender_argv(executable: str, script_path: str) -> list[str]:
    """The exact command line a render uses: background, factory startup, one script.

    ``--factory-startup`` matters: without it a user's startup file could add objects, change the
    engine or override the resolution, and the render would no longer be the scene that was measured.
    """
    return [executable, "--background", "--factory-startup", "--python", script_path]
