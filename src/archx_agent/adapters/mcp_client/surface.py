"""MCP initialization, paginated discovery and tool/resource result interpretation."""

from __future__ import annotations
import json
import time
from typing import Any, Mapping
from archx_agent.helpers.exceptions import (
    MCPProtocolError,
    MCPToolError,
    MCPTimeoutError,
)
from .records import CLIENT_NAME, PROTOCOL_VERSION, McpCallResult, McpToolInfo


class McpSurfaceMixin:
    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": "1"},
            },
        )
        version = result.get("protocolVersion")
        info, capabilities = (
            result.get("serverInfo", {}),
            result.get("capabilities", {}),
        )
        if (
            not isinstance(version, str)
            or not version
            or not isinstance(info, dict)
            or not isinstance(capabilities, dict)
        ):
            raise MCPProtocolError(f"{self.name}: malformed initialize result")
        self.protocol_version = version
        self.server_info = info
        self.capabilities = capabilities
        self.notify("notifications/initialized")
        return result

    def _list(self, method: str, key: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursors: set[str] = set()
        params: dict[str, Any] = {}
        size = 0
        deadline = time.monotonic() + self.timeout
        for _ in range(100):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPTimeoutError(f"{self.name}: discovery deadline expired")
            result = self.request(method, params, timeout=remaining)
            page = result.get(key, [])
            if not isinstance(page, list) or any(
                not isinstance(item, dict) for item in page
            ):
                raise MCPProtocolError(f"{self.name}: {key} must be a list of objects")
            try:
                size += len(json.dumps(page).encode("utf-8"))
            except (ValueError, RecursionError, UnicodeError) as exc:
                raise MCPProtocolError(f"{self.name}: invalid discovery data") from exc
            if size > self.max_message_bytes or len(items) + len(page) > 10_000:
                raise MCPProtocolError(
                    f"{self.name}: {key} discovery exceeds aggregate budget"
                )
            items.extend(page)
            cursor = result.get("nextCursor")
            if cursor is None:
                return items
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise MCPProtocolError(
                    f"{self.name}: invalid or repeated discovery cursor"
                )
            cursors.add(cursor)
            params = {"cursor": cursor}
        raise MCPProtocolError(f"{self.name}: discovery exceeds 100 pages")

    def list_tools(self) -> list[McpToolInfo]:
        tools = []
        names = set()
        for raw in self._list("tools/list", "tools"):
            name = raw.get("name")
            schema, annotations = raw.get("inputSchema", {}), raw.get("annotations", {})
            if (
                not isinstance(name, str)
                or not name
                or name in names
                or not isinstance(schema, dict)
                or not isinstance(annotations, dict)
            ):
                raise MCPProtocolError(
                    f"{self.name}: malformed or duplicate tool definition"
                )
            names.add(name)
            tools.append(
                McpToolInfo(
                    name=name,
                    description=str(raw.get("description") or ""),
                    input_schema=schema,
                    annotations=annotations,
                )
            )
        return tools

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> McpCallResult:
        result = self.request(
            "tools/call",
            {"name": name, "arguments": dict(arguments or {})},
            timeout=timeout,
        )
        content = result.get("content", [])
        if not isinstance(content, list) or any(
            not isinstance(item, dict) for item in content
        ):
            raise MCPProtocolError(
                f"{self.name}: tool content must be a list of objects"
            )
        if "isError" in result and not isinstance(result["isError"], bool):
            raise MCPProtocolError(f"{self.name}: isError must be a boolean")
        if "structuredContent" in result and not isinstance(
            result["structuredContent"], dict
        ):
            raise MCPProtocolError(f"{self.name}: structuredContent must be an object")
        call = McpCallResult(
            content=content,
            is_error=bool(result.get("isError")),
            structured=result.get("structuredContent")
            if isinstance(result.get("structuredContent"), dict)
            else None,
        )
        if call.is_error:
            raise MCPToolError(
                f"{self.name}: tool {name} reported an error: {call.text[:300]}"
            )
        return call

    def list_resources(self) -> list[dict[str, Any]]:
        return self._list("resources/list", "resources")

    def read_resource(self, uri: str) -> dict[str, Any]:
        return self.request("resources/read", {"uri": uri})

    def list_prompts(self) -> list[dict[str, Any]]:
        return self._list("prompts/list", "prompts")
