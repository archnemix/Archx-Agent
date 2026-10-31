"""ReproductionManager: tools operations."""

from __future__ import annotations
from typing import Any
from .records import Issue


class ReproductionManagerToolsMixin:
    def _tool_states(self, task) -> tuple[list[dict[str, Any]], list[Issue]]:
        issues: list[Issue] = []
        states: list[dict[str, Any]] = []
        if not task.tools:
            return states, issues
        for name in task.tools:
            state: dict[str, Any] = {"name": name}
            spec = None
            if self.tools is not None:
                try:
                    spec = self.tools.spec(name)
                except Exception:  # noqa: BLE001 - ToolNotFoundError and friends
                    spec = None
            if spec is None:
                state.update({"registered": False})
                states.append(state)
                issues.append(
                    Issue(
                        "blocker",
                        "tool_missing",
                        f"the tool {name} is no longer registered; the task cannot repeat that step",
                    )
                )
                continue
            state.update(
                {
                    "registered": True,
                    "capability": spec.capability,
                    "risk": spec.risk,
                    "origin": spec.origin,
                    "side_effects": spec.side_effects,
                }
            )
            if spec.capability:
                grants = []
                if self.tools is not None:
                    grants = [
                        g
                        for g in self.tools.permissions.grants(
                            capability=spec.capability, subject=name
                        )
                        if g.active
                    ]
                state["active_grants"] = len(grants)
                if not grants:
                    issues.append(
                        Issue(
                            "caveat",
                            "tool_ungranted",
                            f"{name} has no active grant for {spec.capability}; a replay needs approval again",
                        )
                    )
            if spec.origin.startswith("mcp:"):
                server = spec.origin.split(":", 1)[1]
                status = None
                if self.mcp is not None:
                    try:
                        record = self.mcp.server(server)
                        status = {"trusted": record.trusted, "enabled": record.enabled}
                    except Exception:  # noqa: BLE001
                        status = None
                state["server"] = {"name": server, **(status or {})}
                if not status or not (status["trusted"] and status["enabled"]):
                    issues.append(
                        Issue(
                            "blocker",
                            "mcp_server_inactive",
                            f"the MCP server {server!r} is no longer trusted and enabled, so {name} is gone",
                        )
                    )
            elif spec.origin.startswith("extension:"):
                extension = spec.origin.split(":", 1)[1]
                ext_state = None
                if self.extensions is not None:
                    try:
                        record = self.extensions.extension(extension)
                        ext_state = {"trust": record.trust, "enabled": record.enabled}
                    except Exception:  # noqa: BLE001
                        ext_state = None
                state["extension"] = {"name": extension, **(ext_state or {})}
                if not ext_state or not (
                    ext_state["trust"] == "trusted" and ext_state["enabled"]
                ):
                    issues.append(
                        Issue(
                            "blocker",
                            "extension_inactive",
                            f"the extension {extension!r} is no longer trusted and enabled, so {name} is gone",
                        )
                    )
            if spec.name == "fs.write" or spec.name == "shell.run":
                issues.append(
                    Issue(
                        "caveat",
                        "tool_side_effects",
                        f"replaying {name} repeats its side effects ({spec.side_effects})",
                    )
                )
            states.append(state)
        return states, issues

    def _run_caveats(self, task_id: str) -> list[Issue]:
        issues: list[Issue] = []
        for run in self.tasks.tool_runs(task_id):
            if run.get("dry_run"):
                continue
            if run.get("status") == "denied":
                issues.append(
                    Issue(
                        "caveat",
                        "denied_run",
                        f"the task includes a denied {run['tool_name']} call; a replay stops at the same refusal",
                    )
                )
            permission_id = run.get("permission_id")
            if permission_id and self.tools is not None:
                grant = self.tools.permissions.get(permission_id)
                if grant.is_ok and grant.value.duration == "once":
                    issues.append(
                        Issue(
                            "caveat",
                            "grant_consumed",
                            f"the grant for {run['tool_name']} was single-use and has been used",
                        )
                    )
        return issues
