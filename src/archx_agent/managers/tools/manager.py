"""Composition and shared configuration for tool execution."""

from __future__ import annotations

from typing import Any, Callable

from archx_agent.adapters.local_tools import LocalToolRuntime
from archx_agent.managers.permissions import PermissionManager
from archx_agent.managers.base import BaseManager
from archx_agent.managers.tools.constants import TOOL_TABLES, BUILTIN_SPECS
from archx_agent.managers.tools.records import ToolSpec
from archx_agent.managers.tools.registry import ToolManagerRegistryMixin
from archx_agent.managers.tools.writes import ToolManagerWritesMixin
from archx_agent.managers.tools.execution import ToolManagerExecutionMixin
from archx_agent.managers.tools.history import ToolManagerHistoryMixin
from archx_agent.managers.tools.dispatch import ToolManagerDispatchMixin


class ToolManager(
    ToolManagerRegistryMixin,
    ToolManagerWritesMixin,
    ToolManagerExecutionMixin,
    ToolManagerHistoryMixin,
    ToolManagerDispatchMixin,
    BaseManager,
):
    """Registers built-in tools and executes them under the permission centre."""

    tables = TOOL_TABLES

    def __init__(
        self,
        store,
        coordinator,
        *,
        permissions: PermissionManager,
        events=None,
        config=None,
        runtime: LocalToolRuntime | None = None,
        info_provider: Callable[[], dict[str, Any]] | None = None,
        specs: tuple[ToolSpec, ...] = BUILTIN_SPECS,
    ) -> None:
        self.permissions = permissions
        self.config = config
        self._runtime = runtime
        self._info_provider = info_provider
        # Optional task history (M24). Set by the composition root after both managers
        # exist; a tool call made inside a task is recorded on that task's timeline.
        self.tasks = None
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        for spec in specs:
            self.register_spec(spec)
        super().__init__(store, coordinator, events=events)

    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001
            return default
