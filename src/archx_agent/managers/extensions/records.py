"""ExtensionManager records, constants and pure metadata conversion."""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Any

EXTENSION_TABLES = ("extensions", "extension_tools")

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")

MANIFEST_NAME = "extension.json"

SUPPORTED_ENTRY = ("process",)


def _safe(value: str) -> str:
    return _SAFE.sub("_", (value or "").strip()).strip("._") or "tool"


@dataclass
class Extension:
    id: str
    name: str
    version: str
    path: str
    manifest: dict[str, Any]
    trust: str
    enabled: bool
    installed_at: str
    updated_at: str
    manifest_hash: str | None = None
    trusted_by: str | None = None
    trusted_at: str | None = None
    notes: str | None = None
    last_error: str | None = None

    @property
    def trusted(self) -> bool:
        return self.trust == "trusted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "path": self.path,
            "trust": self.trust,
            "trusted": self.trusted,
            "enabled": self.enabled,
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
            "manifest_hash": self.manifest_hash,
            "trusted_by": self.trusted_by,
            "trusted_at": self.trusted_at,
            "notes": self.notes,
            "last_error": self.last_error,
            "tools": [
                t.get("name")
                for t in (self.manifest.get("tools") or [])
                if isinstance(t, dict)
            ],
        }


def _extension_from_row(row: dict[str, Any]) -> Extension:
    try:
        manifest = json.loads(row["manifest"]) if row.get("manifest") else {}
    except json.JSONDecodeError:  # pragma: no cover - corrupted row
        manifest = {}
    return Extension(
        id=row["id"],
        name=row["name"],
        version=row["version"],
        path=row.get("path") or "",
        manifest=manifest,
        trust=row.get("trust") or "untrusted",
        enabled=bool(row.get("enabled")),
        installed_at=row["installed_at"],
        updated_at=row["updated_at"],
        manifest_hash=row.get("manifest_hash"),
        trusted_by=row.get("trusted_by"),
        trusted_at=row.get("trusted_at"),
        notes=row.get("notes"),
        last_error=row.get("last_error"),
    )
