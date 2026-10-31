"""Compose ExtensionManager; implementation parts share one manager instance."""

from __future__ import annotations
from archx_agent.adapters.extension_runtime import ExtensionRuntime
from ..base import BaseManager
from ..tools import ToolManager
from .records import EXTENSION_TABLES

from .configuration import ExtensionManagerConfigurationMixin
from .writes import ExtensionManagerWritesMixin
from .installation import ExtensionManagerInstallationMixin
from .lifecycle import ExtensionManagerLifecycleMixin
from .registry import ExtensionManagerRegistryMixin


class ExtensionManager(
    ExtensionManagerConfigurationMixin,
    ExtensionManagerWritesMixin,
    ExtensionManagerInstallationMixin,
    ExtensionManagerLifecycleMixin,
    ExtensionManagerRegistryMixin,
    BaseManager,
):
    tables = EXTENSION_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        events=None,
        config=None,
        tools: ToolManager | None = None,
        runtime: ExtensionRuntime | None = None,
    ) -> None:
        self.config = config
        self.tools = tools
        self.runtime = runtime or ExtensionRuntime()
        super().__init__(store, coordinator, events=events)
