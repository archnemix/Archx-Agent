"""ModelManager manager."""

from __future__ import annotations


from archx_agent.managers.base import BaseManager
from archx_agent.managers.models.constants import MODEL_TABLES
from archx_agent.managers.models.writes import ModelManagerWritesMixin
from archx_agent.managers.models.discovery import ModelManagerDiscoveryMixin
from archx_agent.managers.models.registration import ModelManagerRegistrationMixin
from archx_agent.managers.models.queries import ModelManagerQueriesMixin
from archx_agent.managers.models.metadata import ModelManagerMetadataMixin
from archx_agent.managers.models.capabilities import ModelManagerCapabilitiesMixin


class ModelManager(
    ModelManagerWritesMixin,
    ModelManagerDiscoveryMixin,
    ModelManagerRegistrationMixin,
    ModelManagerQueriesMixin,
    ModelManagerMetadataMixin,
    ModelManagerCapabilitiesMixin,
    BaseManager,
):
    """Manager responsibility for ModelManager."""

    tables = MODEL_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        events=None,
        models_root: str | None = None,
        hash_files: bool = False,
    ) -> None:
        self.models_root = models_root
        self.hash_files = hash_files
        super().__init__(store, coordinator, events=events)
