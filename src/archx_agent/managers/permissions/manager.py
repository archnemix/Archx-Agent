"""Composition and shared configuration for permission policy."""

from __future__ import annotations

from typing import Any

from archx_agent.managers.base import BaseManager
from archx_agent.managers.permissions.constants import PERMISSION_TABLES, CAPABILITIES
from archx_agent.managers.permissions.writes import PermissionManagerWritesMixin
from archx_agent.managers.permissions.grants import PermissionManagerGrantsMixin
from archx_agent.managers.permissions.decisions import PermissionManagerDecisionsMixin
from archx_agent.managers.permissions.approvals import PermissionManagerApprovalsMixin


class PermissionManager(
    PermissionManagerWritesMixin,
    PermissionManagerGrantsMixin,
    PermissionManagerDecisionsMixin,
    PermissionManagerApprovalsMixin,
    BaseManager,
):
    """Grants, approvals and the check every protected operation calls."""

    tables = PERMISSION_TABLES

    def __init__(self, store, coordinator, *, events=None, config=None) -> None:
        self.config = config
        super().__init__(store, coordinator, events=events)

    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001 - a missing key must not break a check
            return default

    @staticmethod
    def capabilities() -> list[dict[str, Any]]:
        return [c.to_dict() for c in CAPABILITIES.values()]
