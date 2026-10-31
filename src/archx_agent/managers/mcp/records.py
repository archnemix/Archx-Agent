"""McpManager records, constants and pure metadata conversion."""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

MCP_TABLES = ("mcp_servers", "mcp_tools")

TRANSPORTS = ("stdio", "http")

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def sanitize_tool_name(value: str) -> str:
    cleaned = _SAFE.sub("_", (value or "").strip())
    return cleaned.strip("._") or "tool"


@dataclass
class McpServer:
    id: str
    name: str
    transport: str
    enabled: bool
    trusted: bool
    created_at: str
    updated_at: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    protocol_version: str | None = None
    last_connected_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None
    tools_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "transport": self.transport,
            "enabled": self.enabled,
            "trusted": self.trusted,
            "command": self.command,
            "args": self.args,
            "url": self.url,
            "env": sorted(self.env),
            "headers": sorted(self.headers),
            "protocol_version": self.protocol_version,
            "last_connected_at": self.last_connected_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "tools_count": self.tools_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _server_from_row(row: dict[str, Any]) -> McpServer:
    def _obj(raw: Any) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:  # pragma: no cover - corrupted row
            return {}
        return value if isinstance(value, dict) else {}

    return McpServer(
        id=row["id"],
        name=row["name"],
        transport=row["transport"],
        enabled=bool(row["enabled"]),
        trusted=bool(row["trusted"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        command=row.get("command"),
        args=list(json.loads(row["args"])) if row.get("args") else [],
        url=row.get("url"),
        env=_obj(row.get("env")),
        headers=_obj(row.get("headers")),
        protocol_version=row.get("protocol_version"),
        last_connected_at=row.get("last_connected_at"),
        last_status=row.get("last_status"),
        last_error=row.get("last_error"),
        last_error_at=row.get("last_error_at"),
        tools_count=int(row.get("tools_count") or 0),
    )


def _types_from_schema(
    schema: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str], tuple[str, ...]]:
    """Translate a JSON Schema subset into the registry's input descriptions."""
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        properties = {}
    inputs: dict[str, str] = {}
    types: dict[str, str] = {}
    for name, spec in properties.items():
        spec = spec if isinstance(spec, dict) else {}
        raw_type = spec.get("type")
        if isinstance(raw_type, list):
            raw_type = next((t for t in raw_type if t != "null"), None)
        mapped = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "object": "json",
            "array": "json",
        }.get(str(raw_type), "json")
        inputs[str(name)] = str(
            spec.get("description") or f"{name} ({raw_type or 'any'})"
        )
        types[str(name)] = mapped
    required = schema.get("required") if isinstance(schema, dict) else None
    required_names = (
        tuple(str(x) for x in required) if isinstance(required, list) else ()
    )
    return inputs, types, required_names
