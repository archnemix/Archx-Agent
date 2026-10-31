"""MCP server identifiers and registry-to-wire schema conversion."""

from __future__ import annotations
from typing import Any

SERVER_NAME = "archx-agent"

DEFAULT_SUBJECT = "mcp-server"


def _json_schema_for(spec) -> dict[str, Any]:
    types = spec.types or {name: "str" for name in spec.inputs}
    json_types = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
    }
    properties = {
        name: {
            "type": json_types.get(types.get(name, "str"), "object"),
            "description": description,
        }
        for name, description in spec.inputs.items()
    }
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if spec.required:
        schema["required"] = list(spec.required)
    return schema
