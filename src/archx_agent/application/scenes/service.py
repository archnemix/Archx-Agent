"""Compose SceneService responsibilities and initialize dependencies."""

from __future__ import annotations


from .storage import SceneServiceStorageMixin
from .editing import SceneServiceEditingMixin
from .exports import SceneServiceExportsMixin
from .rendering import SceneServiceRenderingMixin

class SceneService(SceneServiceStorageMixin, SceneServiceEditingMixin, SceneServiceExportsMixin, SceneServiceRenderingMixin):
    'Scenes, from a primitive to a file whose hash can be checked.'

    def __init__(self, ws) -> None:
        self.ws = ws
