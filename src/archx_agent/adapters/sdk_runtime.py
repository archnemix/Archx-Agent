"""A runtime that drives a vendor's **official SDK**.

Why this exists next to ``gemini_runtime`` and ``http_runtime``: those two build the HTTP
request themselves, which is what makes Archx dependency-free but also means "we parse this
vendor's response correctly" is only ever checked against our own reading of the docs. Pointing
the vendor's own client at the same endpoint is the cheapest independent check - and it is what
most users of a paid provider will already have installed.

The runtime is deliberately thin: `SdkTransport` owns the per-vendor request shape and the
error taxonomy, this class owns the Archx contract (load, health, capabilities, secret wiping).

Credential handling is identical to every other network runtime: a ``secret://`` reference is
resolved by the workspace *at construction*, registered with the redactor, and wiped on
``close()``. The literal key is never stored on the model row.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Iterator, Sequence

from archx_agent.adapters.model_runtime import (
    BaseRuntime,
    ChatResult,
    GenerationParams,
    ModelSpec,
    RuntimeHealth,
)
from archx_agent.adapters.sdk_transport import SDKS, sdk_available, transport_for
from archx_agent.helpers.exceptions import AuthDeniedError, ProviderError
from archx_agent.helpers.redaction import register_secret


class SdkChatRuntime(BaseRuntime):
    """One vendor SDK behind the shared runtime contract."""

    runtime_id = "sdk"
    supports_streaming = True
    is_local = False
    _capabilities = frozenset({"chat"})

    def __init__(
        self,
        sdk: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__()
        if sdk not in SDKS:
            raise ProviderError(f"unknown SDK {sdk!r} (known: {', '.join(sorted(SDKS))})")
        self.sdk = sdk
        self.provider = sdk
        self.base_url = (base_url or "").rstrip("/") or None
        host = urllib.parse.urlparse(self.base_url).hostname if self.base_url else ""
        self.is_local = host in ("127.0.0.1", "localhost", "::1")
        self._api_key = (api_key or "").strip()
        if self._api_key:
            register_secret(self._api_key)
        self._transport = transport_for(sdk, api_key=self._api_key, base_url=self.base_url, timeout=timeout)

    # -- contract ---------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        ok, why = sdk_available(self.sdk)
        if not ok:
            return ok, why
        # the transport knows which clients need a credential and which endpoints are local
        return self._transport.available()

    def load(self, spec: ModelSpec) -> None:
        self.spec = spec

    def health(self) -> RuntimeHealth:
        ok, why = self.available()
        return RuntimeHealth(ok=ok, detail=why, loaded=self.loaded, capabilities=tuple(self.capabilities()))

    def chat(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> ChatResult:
        if self.spec is None:
            raise ProviderError("no model loaded")
        ok, why = self.available()
        if not ok:
            raise AuthDeniedError(why, provider=self.sdk)
        model = self.spec.model or self.spec.id
        return self._transport.chat(messages, params, model=model)

    def chat_with_tools(
        self,
        messages: Sequence[dict[str, str]],
        params: GenerationParams,
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResult:
        if self.spec is None:
            raise ProviderError("no model loaded")
        ok, why = self.available()
        if not ok:
            raise AuthDeniedError(why, provider=self.sdk)
        model = self.spec.model or self.spec.id
        return self._transport.chat_with_tools(messages, params, model=model, tools=tools)

    def stream(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> Iterator[str]:
        # Each client streams its own way; `SdkTransport.stream` holds one parser per style and
        # every one of them is measured against a loopback server in tests/test_sdk_m22.py.
        if self.spec is None:
            raise ProviderError("no model loaded")
        ok, why = self.available()
        if not ok:
            raise AuthDeniedError(why, provider=self.sdk)
        model = self.spec.model or self.spec.id
        yield from self._transport.stream(messages, params, model=model)

    def close(self) -> None:
        self._transport.close()
        self._api_key = ""
        self.unload()
