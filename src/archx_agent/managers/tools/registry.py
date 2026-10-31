"""Registry metadata and availability for tool execution."""

from __future__ import annotations

from typing import Any, Callable

from archx_agent.adapters.local_tools import LocalToolRuntime
from archx_agent.helpers.exceptions import (
    ToolError,
    ToolNotFoundError,
    ToolValidationError,
)
from archx_agent.managers.permissions import CAPABILITIES
from archx_agent.managers.tools.records import ToolSpec


class ToolManagerRegistryMixin:
    """Registry responsibility for ToolManager."""

    def register_spec(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ToolValidationError(f"tool {spec.name!r} is already registered")
        if spec.capability is not None and spec.capability not in CAPABILITIES:
            raise ToolValidationError(
                f"tool {spec.name!r} needs unknown capability {spec.capability!r}"
            )
        self._specs[spec.name] = spec

    def register_handler(
        self, name: str, handler: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        """Attach an executable to a registered spec (used by MCP and extensions).

        The spec - and therefore the capability - must already exist. A handler can be
        replaced on re-sync (a server may change its tool list); a *spec* cannot be
        silently redefined by a remote party, which is why :meth:`register_spec` stays
        strict.
        """
        if name not in self._specs:
            raise ToolValidationError(f"handler for unregistered tool {name!r}")
        self._handlers[name] = handler

    def unregister_spec(self, name: str) -> None:
        """Remove a tool that is no longer advertised (server removed / extension disabled)."""
        spec = self._specs.pop(name, None)
        if spec is None:
            raise ToolNotFoundError(f"no tool {name!r}")
        if spec.builtin:
            raise ToolValidationError(
                f"{name!r} is a built-in tool and cannot be unregistered"
            )
        self._handlers.pop(name, None)

    def declare_spec(
        self, spec: ToolSpec, handler: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        """Register a spec and its handler together, replacing a previous version."""
        if spec.name in self._specs:
            self.unregister_spec(spec.name)
        self.register_spec(spec)
        self.register_handler(spec.name, handler)

    def specs(self) -> list[ToolSpec]:
        return [self._specs[name] for name in sorted(self._specs)]

    def spec(self, name: str) -> ToolSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise ToolNotFoundError(
                f"no tool {name!r} (known: {', '.join(sorted(self._specs))})"
            )
        return spec

    def registry(self) -> list[dict[str, Any]]:
        """Every tool with its risk and whether a grant currently covers it."""
        out = []
        for spec in self.specs():
            entry = spec.to_dict()
            if spec.capability:
                grants = self.permissions.grants(capability=spec.capability)
                entry["active_grants"] = len(grants)
            else:
                entry["active_grants"] = None
            out.append(entry)
        return out

    def roots(self) -> list[str]:
        """The directories this workspace's tools are confined to."""
        if self._runtime is None:
            return []
        return [str(root) for root in self._runtime.resolved_roots]

    @property
    def runtime(self) -> LocalToolRuntime:
        if self._runtime is None:
            raise ToolError("no tool runtime is configured for this workspace")
        return self._runtime
