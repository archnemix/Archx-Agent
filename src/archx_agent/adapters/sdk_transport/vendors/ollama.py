"""Ollama operations for vendor SDK transport."""

from __future__ import annotations

from typing import Any, Iterator

from archx_agent.adapters.model_runtime import ChatResult
from archx_agent.helpers.exceptions import (
    MalformedOutputError,
)
from archx_agent.adapters.sdk_transport.compatibility import _supported


class SdkTransportVendorsOllamaMixin:
    """Vendors Ollama responsibility for SdkTransport."""

    def _ollama_client(self):
        if self._client is None:
            from ollama import Client  # noqa: PLC0415

            kwargs: dict[str, Any] = {"timeout": self.timeout}
            if self.base_url:
                kwargs["host"] = self.base_url
            if self.api_key:
                # Ollama Cloud authenticates with a bearer token; a local daemon ignores it.
                kwargs["headers"] = {"Authorization": f"Bearer {self.api_key}"}
            self._client = Client(**kwargs)
        return self._client

    def _ollama_chat(self, messages, params, model) -> ChatResult:
        """Ollama's own client. Works against a local daemon and against Ollama Cloud."""
        client = self._ollama_client()
        call = client.chat
        candidates: dict[str, Any] = {
            "model": model,
            "messages": [dict(m) for m in messages],
            "options": {
                "temperature": params.temperature,
                "top_p": params.top_p,
                "num_predict": int(params.max_tokens),
                "stop": list(params.stop or ()) or None,
            },
        }
        result = call(**_supported(call, candidates))
        message = getattr(result, "message", None)
        if message is None and isinstance(
            result, dict
        ):  # older clients return plain dicts
            message = result.get("message", {})
        text = (
            getattr(message, "content", None)
            or (message.get("content") if isinstance(message, dict) else "")
            or ""
        ).strip()
        if not text:
            raise MalformedOutputError(
                "the provider returned an empty message", provider=self.key
            )
        return ChatResult(
            text=text,
            model_id=getattr(result, "model", None) or model,
            prompt_tokens=int(getattr(result, "prompt_eval_count", 0) or 0),
            completion_tokens=int(getattr(result, "eval_count", 0) or 0),
            finish_reason="length"
            if getattr(result, "done_reason", "") == "length"
            else "stop",
            raw={"sdk": self.key},
        )

    def _stream_ollama(self, messages, params, model) -> Iterator[str]:
        client = self._ollama_client()
        call = client.chat
        candidates: dict[str, Any] = {
            "model": model,
            "messages": [dict(m) for m in messages],
            "options": {
                "temperature": params.temperature,
                "top_p": params.top_p,
                "num_predict": int(params.max_tokens),
            },
            "stream": True,
        }
        for chunk in call(**_supported(call, candidates)):
            message = getattr(chunk, "message", None)
            if message is None and isinstance(chunk, dict):
                message = chunk.get("message") or {}
            text = getattr(message, "content", None)
            if text is None and isinstance(message, dict):
                text = message.get("content")
            if text:
                yield text
