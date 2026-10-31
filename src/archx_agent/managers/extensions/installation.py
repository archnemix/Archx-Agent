"""ExtensionManager: installation operations."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from archx_agent.helpers.exceptions import (
    ConflictError,
    ExtensionError,
    NotFoundError,
)
from archx_agent.helpers.timeutil import iso_now, new_id
from .records import MANIFEST_NAME, Extension
from .manifest import validate_manifest


class ExtensionManagerInstallationMixin:
    def install(
        self, path: str | Path, *, trust: bool = False, enable: bool = False
    ) -> Extension:
        root = Path(path).expanduser().resolve()
        manifest_path = root / MANIFEST_NAME
        if not root.is_dir():
            raise NotFoundError(f"no such directory: {root}")
        if not manifest_path.is_file():
            raise NotFoundError(f"{MANIFEST_NAME} is missing in {root}")
        raw_bytes = manifest_path.read_bytes()
        try:
            manifest = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ExtensionError(f"{MANIFEST_NAME} is not valid JSON: {exc}") from exc
        normalised = validate_manifest(manifest, path=str(root))
        digest = hashlib.sha256(raw_bytes).hexdigest()
        existing = self._find(normalised["name"])
        now = iso_now()
        if existing is not None:
            if existing.manifest_hash == digest:
                raise ConflictError(
                    f"extension {normalised['name']!r} is already installed with this exact "
                    f"manifest (id {existing.id})"
                )
            self._write(
                "extension.update",
                {
                    "id": existing.id,
                    "fields": {
                        "version": normalised["version"],
                        "path": str(root),
                        "manifest": normalised,
                        "manifest_hash": digest,
                        "trust": "untrusted",
                        "trusted_by": None,
                        "trusted_at": None,
                        "notes": "reinstalled: trust was reset because the manifest changed",
                    },
                    "updated_at": now,
                },
            )
            updated = self.extension(existing.id)
            self._unregister(updated)
            self._sync_tools(updated)
            self.trace(
                "extension",
                "reinstalled",
                payload={"name": updated.name, "hash": digest},
            )
            return self.extension(existing.id)
        extension = Extension(
            id=new_id("ex_"),
            name=normalised["name"],
            version=normalised["version"],
            path=str(root),
            manifest=normalised,
            trust="trusted" if trust else "untrusted",
            enabled=enable,
            installed_at=now,
            updated_at=now,
            manifest_hash=digest,
            trusted_by="user:cli" if trust else None,
            trusted_at=now if trust else None,
        )
        self._write(
            "extension.install",
            {
                "extension": {
                    "id": extension.id,
                    "name": extension.name,
                    "version": extension.version,
                    "path": extension.path,
                    "manifest": normalised,
                    "trust": extension.trust,
                    "enabled": extension.enabled,
                    "installed_at": now,
                    "updated_at": now,
                    "manifest_hash": digest,
                    "trusted_by": extension.trusted_by,
                    "trusted_at": extension.trusted_at,
                }
            },
        )
        stored = self.extension(extension.id)
        self._sync_tools(stored)
        self.trace(
            "extension",
            "installed",
            payload={
                "name": stored.name,
                "version": stored.version,
                "hash": digest,
                "tools": [t["name"] for t in normalised["tools"]],
                "trust": stored.trust,
                "enabled": stored.enabled,
            },
        )
        return self.extension(extension.id)
