"""Cohere operations for vendor SDK transport."""

from __future__ import annotations

from typing import Any, Iterator

from archx_agent.adapters.model_runtime import ChatResult
from archx_agent.helpers.exceptions import (
    MalformedOutputError,
)
from archx_agent.adapters.sdk_transport.compatibility import _supported, _finish


class SdkTransportVendorsCohereMixin:
    """Vendors Cohere responsibility for SdkTransport."""

    def _cohere_client(self):
        if self._client is None:
            import cohere  # noqa: PLC0415

            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "max_retries": 0,
                "timeout": self.timeout,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = cohere.ClientV2(**kwargs)
        return self._client

    def _cohere(self, messages, params, model) -> ChatResult:
        """Cohere's v2 chat: `message.content` blocks, `usage.tokens`, a `finish_reason`."""
        client = self._cohere_client()
        call = client.chat
        candidates: dict[str, Any] = {
            "model": model,
            "messages": [dict(m) for m in messages],
            "temperature": params.temperature,
            "p": params.top_p,
            "max_tokens": int(params.max_tokens),
            "stop_sequences": list(params.stop or ()) or None,
        }
        result = call(**_supported(call, candidates))
        message = getattr(result, "message", None)
        blocks = getattr(message, "content", None) or []
        parts = []
        for block in blocks:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        text = "\n".join(parts).strip()
        if not text:
            raise MalformedOutputError(
                "the provider returned an empty message", provider=self.key
            )
        usage = getattr(result, "usage", None)
        tokens = getattr(usage, "tokens", None)
        return ChatResult(
            text=text,
            model_id=model,
            prompt_tokens=int(getattr(tokens, "input_tokens", 0) or 0),
            completion_tokens=int(getattr(tokens, "output_tokens", 0) or 0),
            finish_reason=_finish(getattr(result, "finish_reason", None)),
            raw={"sdk": self.key},
        )

    def _stream_cohere(self, messages, params, model) -> Iterator[str]:
        client = self._cohere_client()
        call = client.chat_stream
        candidates: dict[str, Any] = {
            "model": model,
            "messages": [dict(m) for m in messages],
            "temperature": params.temperature,
            "p": params.top_p,
            "max_tokens": int(params.max_tokens),
        }
        for event in call(**_supported(call, candidates)):
            if getattr(event, "type", "") != "content-delta":
                continue
            text = getattr(
                getattr(getattr(event, "delta", None), "message", None), "content", None
            )
            text = getattr(text, "text", None) if text is not None else None
            if text:
                yield text
