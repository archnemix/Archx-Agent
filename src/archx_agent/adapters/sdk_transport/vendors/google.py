"""Google operations for vendor SDK transport."""

from __future__ import annotations

from typing import Any, Iterator

from archx_agent.adapters.model_runtime import ChatResult
from archx_agent.helpers.exceptions import (
    MalformedOutputError,
    ProviderError,
)
from archx_agent.adapters.sdk_transport.compatibility import _finish


class SdkTransportVendorsGoogleMixin:
    """Vendors Google responsibility for SdkTransport."""

    def _genai(self):
        if self._client is None:
            from google import genai  # noqa: PLC0415
            from google.genai import types  # noqa: PLC0415

            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["http_options"] = types.HttpOptions(
                    base_url=self.base_url, timeout=int(self.timeout * 1000)
                )
            self._client = genai.Client(**kwargs)
        return self._client

    def _google(self, messages, params, model) -> ChatResult:
        from google.genai import types  # noqa: PLC0415

        client = self._genai()
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        contents = [
            types.Content(
                role="model" if m.get("role") == "assistant" else "user",
                parts=[types.Part(text=m.get("content", ""))],
            )
            for m in messages
            if m.get("role") != "system"
        ]
        if not contents:
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part(text="".join(system_parts) or "hello")],
                )
            ]
        config = types.GenerateContentConfig(
            temperature=params.temperature,
            top_p=params.top_p,
            max_output_tokens=int(params.max_tokens),
            system_instruction="\n".join(system_parts) or None,
            stop_sequences=list(params.stop or ()) or None,
        )
        result = client.models.generate_content(
            model=model, contents=contents, config=config
        )
        text = (getattr(result, "text", "") or "").strip()
        if not text:
            feedback = getattr(result, "prompt_feedback", None)
            blocked = getattr(feedback, "block_reason", None)
            if blocked:
                raise ProviderError(
                    f"the prompt was blocked ({blocked}); nothing was generated",
                    provider=self.key,
                )
            raise MalformedOutputError(
                "the provider returned no text", provider=self.key
            )
        usage = getattr(result, "usage_metadata", None)
        candidates = getattr(result, "candidates", None) or []
        finish = (
            _finish(getattr(candidates[0], "finish_reason", None))
            if candidates
            else "stop"
        )
        return ChatResult(
            text=text,
            model_id=getattr(result, "model_version", None) or model,
            prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            completion_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
            finish_reason=finish,
            raw={
                "sdk": self.key,
                "total_tokens": getattr(usage, "total_token_count", None),
            },
        )

    def _stream_google(self, messages, params, model) -> Iterator[str]:
        from google.genai import types  # noqa: PLC0415

        client = self._genai()
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        contents = [
            types.Content(
                role="model" if m.get("role") == "assistant" else "user",
                parts=[types.Part(text=m.get("content", ""))],
            )
            for m in messages
            if m.get("role") != "system"
        ]
        if not contents:
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part(text="".join(system_parts) or "hello")],
                )
            ]
        config = types.GenerateContentConfig(
            temperature=params.temperature,
            top_p=params.top_p,
            max_output_tokens=int(params.max_tokens),
            system_instruction="\n".join(system_parts) or None,
        )
        for chunk in client.models.generate_content_stream(
            model=model, contents=contents, config=config
        ):
            text = getattr(chunk, "text", None)
            if text:
                yield text
