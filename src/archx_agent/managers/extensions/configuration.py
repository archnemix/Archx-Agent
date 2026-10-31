"""ExtensionManager: configuration operations."""

from __future__ import annotations
import json
from typing import Any
from archx_agent.helpers.exceptions import (
    NotFoundError,
)
from .records import Extension, _extension_from_row


class ExtensionManagerConfigurationMixin:
    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001
            return default

    def _find(self, ref: str) -> Extension | None:
        row = self.store.query_one(
            "SELECT * FROM extensions WHERE id = ? OR name = ?", (ref, ref)
        )
        return _extension_from_row(row) if row else None

    def extension(self, ref: str) -> Extension:
        found = self._find(ref)
        if found is None:
            raise NotFoundError(f"no extension {ref!r}")
        return found

    def extensions(self) -> list[Extension]:
        return [
            _extension_from_row(row)
            for row in self.store.query("SELECT * FROM extensions ORDER BY name")
        ]

    def tools_of(self, extension_id: str) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT * FROM extension_tools WHERE extension_id = ? ORDER BY name",
            (extension_id,),
        )
        for row in rows:
            for key in ("schema", "entry"):
                if row.get(key):
                    try:
                        row[key] = json.loads(row[key])
                    except json.JSONDecodeError:  # pragma: no cover
                        row[key] = {}
                else:
                    row[key] = {}
        return rows
