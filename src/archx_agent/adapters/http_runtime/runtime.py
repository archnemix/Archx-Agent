"""Compose HTTP transport, payload handling, and runtime lifecycle."""

from __future__ import annotations

from archx_agent.helpers.urls import is_loopback_url

from typing import Any

from archx_agent.helpers.exceptions import (
    ArchxError,
    InvalidRequestError,
    MalformedOutputError,
)
from archx_agent.helpers.redaction import register_secret
from archx_agent.adapters.model_runtime import BaseRuntime, ModelSpec, RuntimeHealth
from archx_agent.adapters.http_runtime.transport import HttpChatRuntimeTransportMixin
from archx_agent.adapters.http_runtime.errors import HttpChatRuntimeErrorsMixin
from archx_agent.adapters.http_runtime.completions import (
    HttpChatRuntimeCompletionsMixin,
)
from archx_agent.adapters.http_runtime.streaming import HttpChatRuntimeStreamingMixin


class HttpChatRuntime(
    HttpChatRuntimeTransportMixin,
    HttpChatRuntimeErrorsMixin,
    HttpChatRuntimeCompletionsMixin,
    HttpChatRuntimeStreamingMixin,
    BaseRuntime,
):
    """Chat completions over an OpenAI-compatible endpoint."""

    runtime_id = "openai-http"

    provider = "openai-compatible"

    supports_streaming = True

    _capabilities = frozenset({"chat"})

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 120.0,
        is_local: bool | None = None,
        provider: str | None = None,
        runtime_id: str | None = None,
        extra_headers: dict[str, str] | None = None,
        max_retries: int = 2,
    ) -> None:
        super().__init__()
        if not base_url:
            raise InvalidRequestError("base_url is required")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        if api_key:
            register_secret(api_key)
        self.timeout = timeout
        self.provider = provider or self.provider
        self.runtime_id = runtime_id or self.runtime_id
        self.extra_headers = dict(extra_headers or {})
        self.max_retries = max_retries
        self.is_local = (
            is_local if is_local is not None else is_loopback_url(self.base_url)
        )

    def available(self) -> tuple[bool, str]:
        if not self.base_url:
            return False, "no base_url configured"
        return True, "ready"

    def _chat_path(self) -> str:
        return (
            "/v1/chat/completions"
            if not self.base_url.endswith("/v1")
            else "/chat/completions"
        )

    def health(self) -> RuntimeHealth:
        try:
            data = self._request(
                "GET", "/v1/models" if not self.base_url.endswith("/v1") else "/models"
            )
        except ArchxError as exc:
            return RuntimeHealth(
                ok=False,
                detail=f"{type(exc).__name__}: {exc.message}",
                capabilities=tuple(self._capabilities),
            )
        models = []
        if not isinstance(data.get("data", []), list):
            return RuntimeHealth(
                ok=False, detail="MalformedOutputError: models data must be a list"
            )
        if isinstance(data, dict):
            models = [
                entry.get("id")
                for entry in data.get("data", [])
                if isinstance(entry, dict)
            ]
        return RuntimeHealth(
            ok=True,
            detail=f"reachable; {len(models)} model(s) advertised",
            loaded=self.loaded,
            capabilities=tuple(self._capabilities),
        )

    def list_models(self) -> list[dict[str, Any]]:
        data = self._request(
            "GET", "/v1/models" if not self.base_url.endswith("/v1") else "/models"
        )
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise MalformedOutputError(
                "model list response is malformed", provider=self.provider
            )
        return [entry for entry in data["data"] if isinstance(entry, dict)]

    def load(self, spec: ModelSpec) -> None:
        self.spec = spec
        spec.model = spec.model or spec.id

    def close(self) -> None:
        self._api_key = ""
        super().close()
