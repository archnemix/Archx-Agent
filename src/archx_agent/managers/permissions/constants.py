"""Vocabulary and defaults for permission policy."""

from __future__ import annotations

from archx_agent.managers.permissions.records import Capability


PERMISSION_TABLES = ("permission_grants", "approval_requests")

DURATIONS = ("once", "task", "conversation", "project", "persistent")

CAPABILITIES: dict[str, Capability] = {
    "fs.read": Capability(
        "fs.read", "read and list files inside the tool roots", "low", "reads"
    ),
    "fs.write": Capability(
        "fs.write", "create or modify files inside the tool roots", "medium", "writes"
    ),
    "fs.delete": Capability(
        "fs.delete", "delete files inside the tool roots", "high", "deletes"
    ),
    "shell.run": Capability("shell.run", "run a local process", "high", "executes"),
    "mcp.call": Capability(
        "mcp.call", "invoke a tool on a configured MCP server", "medium", "network"
    ),
    "process.exec": Capability(
        "process.exec",
        "run a program shipped by a trusted extension",
        "high",
        "executes",
    ),
    # Declared in M22, implemented in M28: `net.fetch` reads one http(s) document and
    # refuses private addresses unless the user deliberately allows them.
    "net.fetch": Capability(
        "net.fetch",
        "fetch an http(s) URL (private addresses refused by default)",
        "medium",
        "network",
    ),
}

RISK_LEVELS = ("low", "medium", "high")

APPROVAL_STATUSES = ("pending", "approved", "denied", "expired")
