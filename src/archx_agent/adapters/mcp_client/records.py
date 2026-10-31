"""MCP wire-independent tool/result records and pending response signals."""

from __future__ import annotations
import json
import threading
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "archx-agent"


@dataclass
class McpToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "annotations": self.annotations,
        }


@dataclass
class McpCallResult:
    content: list[dict[str, Any]]
    is_error: bool = False
    structured: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "isError": self.is_error,
            "structured": self.structured,
        }

    @property
    def text(self) -> str:
        parts = []
        for item in self.content:
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(json.dumps(item, sort_keys=True))
        return "\n".join(parts)


class _Pending:
    __slots__ = ("id", "result", "error", "event")

    def __init__(self, request_id: int) -> None:
        self.id = request_id
        self.result: dict[str, Any] | None = None
        self.error: Exception | None = None
        self.event = threading.Event()
