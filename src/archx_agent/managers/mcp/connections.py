"""McpManager: connections operations."""

from __future__ import annotations
import os
from archx_agent.adapters.mcp_client import (
    McpHttpClient,
    McpStdioClient,
)
from .records import McpServer


class McpManagerConnectionsMixin:
    def _client(self, server: McpServer):
        existing = self._clients.get(server.id)
        if existing is not None:
            if getattr(existing, "alive", lambda: False)():
                return existing
            self._close(server.id)
        if server.transport == "stdio":
            env = dict(os.environ)
            env.update(server.env)
            client = McpStdioClient(
                [server.command or "", *server.args],
                name=server.name,
                env=env,
                timeout=self.client_timeout,
            )
        else:
            client = McpHttpClient(
                server.url or "",
                name=server.name,
                headers=server.headers,
                timeout=self.client_timeout,
            )
        self._clients[server.id] = client
        return client

    def _close(self, server_id: str) -> None:
        client = self._clients.pop(server_id, None)
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - closing must not raise
                pass

    def close(self) -> None:
        for server_id in list(self._clients):
            self._close(server_id)
