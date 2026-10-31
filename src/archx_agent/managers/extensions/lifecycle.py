"""ExtensionManager: lifecycle operations."""

from __future__ import annotations
from archx_agent.helpers.timeutil import iso_now
from .records import Extension


class ExtensionManagerLifecycleMixin:
    def trust(self, ref: str, *, trusted: bool = True) -> Extension:
        extension = self.extension(ref)
        self._write(
            "extension.update",
            {
                "id": extension.id,
                "fields": {
                    "trust": "trusted" if trusted else "untrusted",
                    "trusted_by": "user:cli" if trusted else None,
                    "trusted_at": iso_now() if trusted else None,
                },
                "updated_at": iso_now(),
            },
        )
        updated = self.extension(extension.id)
        if trusted:
            self._sync_tools(updated)
        else:
            self._unregister(updated)
        self.trace(
            "extension",
            "trusted" if trusted else "untrusted",
            payload={
                "name": updated.name,
                "tools": [t["name"] for t in self.tools_of(updated.id)],
            },
        )
        return self.extension(extension.id)

    def set_enabled(self, ref: str, *, enabled: bool = True) -> Extension:
        extension = self.extension(ref)
        self._write(
            "extension.update",
            {
                "id": extension.id,
                "fields": {"enabled": enabled},
                "updated_at": iso_now(),
            },
        )
        updated = self.extension(extension.id)
        if enabled:
            self._sync_tools(updated)
        else:
            self._unregister(updated)
        self.trace(
            "extension",
            "enabled" if enabled else "disabled",
            payload={"name": updated.name},
        )
        return self.extension(extension.id)

    def remove(self, ref: str) -> Extension:
        extension = self.extension(ref)
        self._unregister(extension)
        self._write("extension.delete", {"id": extension.id})
        self.trace("extension", "removed", payload={"name": extension.name})
        return extension

    def _not_active_reason(self, extension: Extension) -> str:
        if not self._cfg("extensions.enabled", True):
            return "extensions are disabled (extensions.enabled=false)"
        if not extension.trusted and not extension.enabled:
            return "the extension is untrusted and disabled"
        if not extension.trusted:
            return "the extension is not trusted (archx-agent extensions trust <name>)"
        return "the extension is disabled (archx-agent extensions enable <name>)"
