"""Transport composition and public requests for vendor SDK transport."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

from archx_agent.adapters.model_runtime import ChatResult, GenerationParams
from archx_agent.helpers.exceptions import (
    ProviderError,
)
from archx_agent.helpers.urls import is_loopback_url
from archx_agent.adapters.sdk_transport.registry import SdkSpec, SDKS, sdk_available
from archx_agent.adapters.sdk_transport.errors import classify_sdk_error
from archx_agent.adapters.sdk_transport.vendors.openai_compatible import (
    SdkTransportVendorsOpenaiCompatibleMixin,
)
from archx_agent.adapters.sdk_transport.vendors.anthropic import (
    SdkTransportVendorsAnthropicMixin,
)
from archx_agent.adapters.sdk_transport.vendors.google import (
    SdkTransportVendorsGoogleMixin,
)
from archx_agent.adapters.sdk_transport.vendors.cohere import (
    SdkTransportVendorsCohereMixin,
)
from archx_agent.adapters.sdk_transport.vendors.ollama import (
    SdkTransportVendorsOllamaMixin,
)


@dataclass
class SdkTransport(
    SdkTransportVendorsOpenaiCompatibleMixin,
    SdkTransportVendorsAnthropicMixin,
    SdkTransportVendorsGoogleMixin,
    SdkTransportVendorsCohereMixin,
    SdkTransportVendorsOllamaMixin,
):
    """A thin adapter over one vendor client. One method per thing worth measuring."""

    key: str

    api_key: str

    base_url: str | None = None

    timeout: float = 60.0

    _client: Any = field(default=None, repr=False)

    @property
    def spec(self) -> SdkSpec:
        return SDKS[self.key]

    def is_loopback(self) -> bool:
        """Is this client talking to a daemon on this machine?"""
        return is_loopback_url(self.base_url or "")

    def available(self) -> tuple[bool, str]:
        ok, why = sdk_available(self.key)
        if not ok:
            return ok, why
        if self.api_key:
            return True, "ready"
        if self.spec.key_required:
            return (
                False,
                f"no API key: set {self.spec.env_var} or a secret:// reference",
            )
        if not self.is_loopback():
            # the client would work without a credential, but the endpoint would reject it -
            # saying "no key" now beats a 401 later
            return False, (
                f"no API key: {self.spec.label} at {self.base_url} is remote and needs one "
                f"({self.spec.env_var})"
            )
        return True, f"ready: a local {self.spec.label} needs no key"

    def close(self) -> None:
        client = self._client
        self._client = None
        self.api_key = ""
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - closing must not raise
                pass

    def _fail(self, exc: BaseException) -> ProviderError:
        return classify_sdk_error(exc, key=self.api_key, provider=self.key)

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        params: GenerationParams,
        *,
        model: str,
    ) -> ChatResult:
        started = time.perf_counter()
        try:
            if self.key in ("openai", "mistral", "groq", "together"):
                result = self._openai_shaped(messages, params, model)
            elif self.key == "anthropic":
                result = self._anthropic(messages, params, model)
            elif self.key == "google":
                result = self._google(messages, params, model)
            elif self.key == "cohere":
                result = self._cohere(messages, params, model)
            elif self.key == "ollama":
                result = self._ollama_chat(messages, params, model)
            else:  # pragma: no cover - guarded by SDKS
                raise ProviderError(f"no transport for {self.key!r}")
        except ProviderError:
            raise
        except BaseException as exc:  # noqa: BLE001 - every vendor failure becomes one of ours
            raise self._fail(exc) from exc
        result.latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        return result

    def stream(
        self,
        messages: Sequence[dict[str, str]],
        params: GenerationParams,
        *,
        model: str,
    ) -> Iterator[str]:
        """Yield text as the vendor sends it.

        Each client spells streaming differently (a `stream=True` flag, a separate `*_stream`
        method, or an event type on every chunk), so there is one small parser per style. All
        of them are measured against a loopback server in `tests/test_sdk_m22.py`; a client
        whose events this code got wrong fails there rather than in a user's terminal.
        """
        try:
            if self.key in ("openai", "mistral", "groq", "together"):
                yield from self._stream_openai_shaped(messages, params, model)
            elif self.key == "anthropic":
                yield from self._stream_anthropic(messages, params, model)
            elif self.key == "google":
                yield from self._stream_google(messages, params, model)
            elif self.key == "cohere":
                yield from self._stream_cohere(messages, params, model)
            elif self.key == "ollama":
                yield from self._stream_ollama(messages, params, model)
            else:  # pragma: no cover - guarded by SDKS
                raise ProviderError(f"no streaming transport for {self.key!r}")
        except ProviderError:
            raise
        except BaseException as exc:  # noqa: BLE001 - every vendor failure becomes one of ours
            raise self._fail(exc) from exc

    def chat_with_tools(
        self,
        messages: Sequence[dict[str, str]],
        params: GenerationParams,
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResult:
        """One turn with a tool offered, parsed into ``raw["tool_calls"]``.

        Only the clients whose tool calling is implemented here accept this; anything else says
        so instead of pretending, because a probe that cannot fail proves nothing.
        """
        if self.key in ("openai", "mistral", "groq", "together"):
            return self._tools_openai_shaped(messages, params, model, tools)
        if self.key == "anthropic":
            return self._tools_anthropic(messages, params, model, tools)
        raise ProviderError(
            f"tool calling is not implemented for the {self.spec.label} client; "
            "the probe will not claim it",
            provider=self.key,
        )

    def list_models(self) -> list[str]:
        """Ask the vendor what it serves. Some SDKs cannot enumerate; that is reported."""
        try:
            if self.key == "openai":
                return [item.id for item in self._openai().models.list().data]
            if self.key == "mistral":
                from mistralai.client import Mistral  # noqa: PLC0415 - optional dependency

                client = (
                    Mistral(api_key=self.api_key, server_url=self.base_url)
                    if self.base_url
                    else Mistral(api_key=self.api_key)
                )
                return [item.id for item in client.models.list().data]
            if self.key == "google":
                client = self._genai()
                return [getattr(item, "name", "") for item in client.models.list()]
            if self.key in ("groq", "together"):
                return [
                    item.id
                    for item in self._openai_compatible_client().models.list().data
                ]
            if self.key == "ollama":
                response = self._ollama_client().list()
                models = getattr(response, "models", None) or response.get("models", [])
                return [
                    getattr(item, "model", None) or item.get("model", "")
                    for item in models
                ]
            if self.key == "cohere":
                return [
                    item.name for item in self._cohere_client().models.list().models
                ]
        except BaseException as exc:  # noqa: BLE001
            raise self._fail(exc) from exc
        return []
