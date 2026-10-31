"""SceneService records, constants and pure validation helpers."""

from __future__ import annotations

import hashlib
from typing import Any

SUFFIXES = {"obj": ".obj", "stl": ".stl", "svg": ".svg", "script": "_blender.py", "render": ".png"}

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _slug(name: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_"
                   for character in name.strip().lower()) or "scene"

def empty_document(name: str) -> dict[str, Any]:
    """A scene with no objects and a camera that can already see the origin."""
    return {
        "name": name,
        "format": "archx-scene/1",
        "units": "meters",
        "engine": "BLENDER_EEVEE_NEXT",
        "camera": {
            "location": [4.0, -4.0, 3.0],
            "target": [0.0, 0.0, 0.0],
            "up": [0.0, 0.0, 1.0],
            "fov": 40.0,
            "resolution": [480, 480],
        },
        "light": {"location": [4.0, -4.0, 3.0], "energy": 1000.0},
        "objects": [],
    }
