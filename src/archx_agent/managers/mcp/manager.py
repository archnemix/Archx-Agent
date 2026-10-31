"""Compose McpManager; implementation parts share one manager instance."""

from __future__ import annotations
from typing import Any
from ..base import BaseManager
from ..tools import ToolManager
from .records import MCP_TABLES

from .configuration import McpManagerConfigurationMixin
from .writes import McpManagerWritesMixin
from .connections import McpManagerConnectionsMixin
from .discovery import McpManagerDiscoveryMixin
from .registry import McpManagerRegistryMixin
from .calls import McpManagerCallsMixin


class McpManager(
    McpManagerConfigurationMixin,
    McpManagerWritesMixin,
    McpManagerConnectionsMixin,
    McpManagerDiscoveryMixin,
    McpManagerRegistryMixin,
    McpManagerCallsMixin,
    BaseManager,
):
    """Server records, discovery, and the registration seam into the tool registry."""

    tables = MCP_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        events=None,
        config=None,
        tools: ToolManager | None = None,
    ) -> None:
        self.config = config
        self.tools = tools
        self._clients: dict[str, Any] = {}
        super().__init__(store, coordinator, events=events)
