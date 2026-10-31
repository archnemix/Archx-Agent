"""ExtensionManager: registry operations."""

from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
from archx_agent.helpers.exceptions import (
    ExtensionError,
    ExtensionTrustError,
    PathEscapesRootError,
)
from archx_agent.helpers.paths import is_within
from archx_agent.helpers.timeutil import iso_now, new_id
from ..tools import ToolSpec
from .records import _safe, Extension


class ExtensionManagerRegistryMixin:
    def _sync_tools(self, extension: Extension) -> list[str]:
        """(Re)register the extension's tools when it is trusted *and* enabled."""
        if self.tools is None:
            return []
        active = (
            extension.trusted
            and extension.enabled
            and bool(self._cfg("extensions.enabled", True))
        )
        registered: list[str] = []
        for tool in extension.manifest.get("tools") or []:
            spec = self._spec_for(extension, tool)
            self._write(
                "extension.tool.upsert",
                {
                    "tool": {
                        "id": new_id("et_"),
                        "extension_id": extension.id,
                        "name": tool["name"],
                        "description": tool["description"],
                        "capability": tool["capability"],
                        "risk": tool["risk"],
                        "schema": {
                            "inputs": tool["inputs"],
                            "required": tool["required"],
                        },
                        "entry": {"type": "process", "command": tool["command"]},
                        "enabled": active,
                        "discovered_at": iso_now(),
                    }
                },
            )
            if active:
                self.tools.declare_spec(spec, self._handler(extension, tool))
                registered.append(spec.name)
        if not active:
            self._unregister(extension, keep_rows=True)
        self.trace(
            "extension",
            "tools.synced",
            payload={
                "extension": extension.name,
                "registered": registered,
                "active": active,
                "reason": None if active else self._not_active_reason(extension),
            },
        )
        return registered

    @staticmethod
    def spec_name(extension_name: str, tool_name: str) -> str:
        return f"ext.{_safe(extension_name)}.{_safe(tool_name)}"

    def _spec_for(self, extension: Extension, tool: Mapping[str, Any]) -> ToolSpec:
        return ToolSpec(
            name=self.spec_name(extension.name, str(tool["name"])),
            summary=str(tool["description"])[:200],
            capability=str(tool["capability"]),
            risk=str(tool["risk"]),
            inputs=dict(tool["inputs"]),
            required=tuple(tool["required"]),
            types=dict(tool["types"]),
            supports_dry_run=bool(tool.get("supports_dry_run")),
            side_effects=f"runs {tool['command'][0]} from extension {extension.name}",
            builtin=False,
            origin=f"extension:{extension.name}",
        )

    def _handler(self, extension: Extension, tool: Mapping[str, Any]):
        argv = list(tool["command"])
        ext_name = extension.name
        tool_name = str(tool["name"])
        root = extension.path

        def call(args: dict[str, Any]) -> dict[str, Any]:
            if not self._cfg("extensions.enabled", True):
                raise ExtensionTrustError(
                    "extensions are disabled (extensions.enabled=false)"
                )
            current = self.extension(ext_name)
            if not current.trusted:
                raise ExtensionTrustError(
                    f"extension {ext_name!r} is not trusted; its tools may not run"
                )
            if not current.enabled:
                raise ExtensionTrustError(
                    f"extension {ext_name!r} is disabled (archx-agent extensions enable {ext_name})"
                )
            resolved: list[str] = [
                argv[0]
            ]  # the program itself (see validate_manifest)
            for part in argv[1:]:
                if Path(part).is_absolute():
                    if not is_within(root, part):
                        raise ExtensionError(
                            f"command path {part!r} is outside the extension"
                        )
                    resolved.append(part)
                    continue
                candidate = (Path(root) / part).resolve()
                if ("/" in part or part.endswith(".py")) and not is_within(
                    root, candidate
                ):
                    raise PathEscapesRootError(
                        "extension command escapes its directory", path=part, root=root
                    )
                resolved.append(part)
            request = {"extension": ext_name, "tool": tool_name, "arguments": args}
            result = self.runtime.run(
                resolved,
                request,
                cwd=root,
                timeout=int(self._cfg("tools.timeout_seconds", 60)),
            )
            self.trace(
                "extension",
                "tool.ran",
                payload={"extension": ext_name, "tool": tool_name, "result": result},
            )
            return result

        return call

    def _unregister(self, extension: Extension, *, keep_rows: bool = False) -> None:
        if self.tools is not None:
            for row in self.tools_of(extension.id):
                try:
                    self.tools.unregister_spec(
                        self.spec_name(extension.name, row["name"])
                    )
                except Exception:  # noqa: BLE001 - already gone
                    continue
        if not keep_rows:
            for row in self.tools_of(extension.id):
                self._write(
                    "extension.tool.delete",
                    {"extension_id": extension.id, "name": row["name"]},
                )

    def restore(self) -> dict[str, int]:
        """Re-register trusted, enabled extensions after a restart (no writes)."""
        if not self._cfg("extensions.enabled", True) or self.tools is None:
            return {"extensions": 0, "tools": 0}
        extensions = 0
        tools = 0
        for extension in self.extensions():
            if not (extension.trusted and extension.enabled):
                continue
            if not Path(extension.path).is_dir():
                self.trace(
                    "extension",
                    "restore_skipped",
                    status="error",
                    error=f"directory missing: {extension.path}",
                    payload={"extension": extension.name},
                )
                continue
            registered = 0
            for tool in extension.manifest.get("tools") or []:
                self.tools.declare_spec(
                    self._spec_for(extension, tool), self._handler(extension, tool)
                )
                registered += 1
            if registered:
                extensions += 1
                tools += registered
        return {"extensions": extensions, "tools": tools}

    def status(self) -> list[dict[str, Any]]:
        out = []
        for extension in self.extensions():
            tools = self.tools_of(extension.id)
            out.append(
                {
                    **extension.to_dict(),
                    "tool_count": len(tools),
                    "registered": sum(1 for t in tools if t.get("enabled")),
                }
            )
        return out
