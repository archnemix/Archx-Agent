"""Geometry public API. Creation, measurement, transforms and formats have separate owners.

This package computes meshes and emits Blender scripts; SceneService owns rendering.
"""

from .constants import (
    Point as Point,
    Matrix as Matrix,
    PRIMITIVES as PRIMITIVES,
    PARAMS as PARAMS,
    SEGMENT_PARAMS as SEGMENT_PARAMS,
    IDENTITY as IDENTITY,
)
from .transforms import (
    mat_mul as mat_mul,
    mat_translate as mat_translate,
    mat_scale as mat_scale,
    mat_rotate as mat_rotate,
    transform_matrix as transform_matrix,
    transform_point as transform_point,
)
from .mesh import Mesh as Mesh
from .primitives import (
    cube as cube,
    plane as plane,
    uv_sphere as uv_sphere,
    cylinder as cylinder,
    cone as cone,
    torus as torus,
    GENERATORS as GENERATORS,
    build as build,
)
from .vectors import (
    _cross as _cross,
    _sub as _sub,
    _dot as _dot,
    _length as _length,
    _normalise as _normalise,
)
from .measurement import (
    edge_counts as edge_counts,
    surface_area as surface_area,
    volume as volume,
    bounding_box as bounding_box,
    centroid as centroid,
    metrics as metrics,
)
from .camera import look_at as look_at, project as project
from .exporters.formatting import _fmt as _fmt, face_normal as face_normal
from .exporters.obj import to_obj as to_obj
from .exporters.stl import to_stl as to_stl
from .exporters.svg import to_svg as to_svg
from .exporters.blender import (
    blender_script as blender_script,
    blender_argv as blender_argv,
)
