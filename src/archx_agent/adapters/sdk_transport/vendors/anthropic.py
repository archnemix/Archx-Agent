"""Anthropic operations for vendor SDK transport."""

from __future__ import annotations

from typing import Any, Iterator

from archx_agent.adapters.model_runtime import ChatResult
from archx_agent.helpers.exceptions import (
    MalformedOutputError,
)
from archx_agent.adapters.sdk_transport.compatibility import _supported, _finish


class SdkTransportVendorsAnthropicMixin:
    """Vendors Anthropic responsibility for SdkTransport."""

    def _anthropic_client(self):
        if self._client is None:
            import anthropic  # noqa: PLC0415

            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "max_retries": 0,
                "timeout": self.timeout,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def _anthropic(self, messages, params, model) -> ChatResult:
        client = self._anthropic_client()
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        turns = [
            {
                "role": "assistant" if m.get("role") == "assistant" else "user",
                "content": m.get("content", ""),
            }
            for m in messages
            if m.get("role") != "system"
        ]
        if not turns:
            turns = [{"role": "user", "content": "".join(system_parts) or "hello"}]
        candidates: dict[str, Any] = {
            "model": model,
            "max_tokens": max(int(params.max_tokens), 1),
            "messages": turns,
            "temperature": params.temperature,
            "top_p": params.top_p,
            "system": "\n".join(system_parts) or None,
            "stop_sequences": list(params.stop or ()) or None,
        }
        result = client.messages.create(
            **_supported(client.messages.create, candidates)
        )
        blocks = [
            getattr(block, "text", "")
            for block in (getattr(result, "content", None) or [])
        ]
        text = "\n".join(part for part in blocks if part).strip()
        if not text:
            raise MalformedOutputError(
                f"the provider returned no text (stop_reason={getattr(result, 'stop_reason', '?')})",
                provider=self.key,
            )
        usage = getattr(result, "usage", None)
        return ChatResult(
            text=text,
            model_id=getattr(result, "model", None) or model,
            prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            finish_reason=_finish(getattr(result, "stop_reason", None)),
            raw={"sdk": self.key, "id": getattr(result, "id", None)},
        )

    def _tools_anthropic(self, messages, params, model, tools) -> ChatResult:
        client = self._anthropic_client()
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        turns = [
            {
                "role": "assistant" if m.get("role") == "assistant" else "user",
                "content": m.get("content", ""),
            }
            for m in messages
            if m.get("role") != "system"
        ] or [{"role": "user", "content": "".join(system_parts) or "hello"}]
        # Anthropic's tool shape is flat: name, description, input_schema
        offered = tools or [
            {
                "name": "record_value",
                "description": "Record one integer value.",
                "input_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
            }
        ]
        candidates: dict[str, Any] = {
            "model": model,
            "max_tokens": max(int(params.max_tokens), 1),
            "messages": turns,
            "system": "\n".join(system_parts) or None,
            "tools": offered,
        }
        result = client.messages.create(
            **_supported(client.messages.create, candidates)
        )
        calls = [
            {
                "id": getattr(block, "id", None),
                "name": getattr(block, "name", None),
                "arguments": getattr(block, "input", None),
            }
            for block in (getattr(result, "content", None) or [])
            if getattr(block, "type", "") == "tool_use"
        ]
        if not calls:
            raise MalformedOutputError(
                "the model answered without calling the tool; tool use is not proven",
                provider=self.key,
            )
        usage = getattr(result, "usage", None)
        return ChatResult(
            text="",
            model_id=getattr(result, "model", None) or model,
            prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            finish_reason=_finish(getattr(result, "stop_reason", None)),
            raw={"sdk": self.key, "tool_calls": calls},
        )

    def _stream_anthropic(self, messages, params, model) -> Iterator[str]:
        client = self._anthropic_client()
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        turns = [
            {
                "role": "assistant" if m.get("role") == "assistant" else "user",
                "content": m.get("content", ""),
            }
            for m in messages
            if m.get("role") != "system"
        ]
        if not turns:
            turns = [{"role": "user", "content": "".join(system_parts) or "hello"}]
        candidates: dict[str, Any] = {
            "model": model,
            "max_tokens": max(int(params.max_tokens), 1),
            "messages": turns,
            "temperature": params.temperature,
            "top_p": params.top_p,
            "system": "\n".join(system_parts) or None,
            "stream": True,
        }
        with client.messages.create(
            **_supported(client.messages.create, candidates)
        ) as events:
            for event in events:
                if getattr(event, "type", "") != "content_block_delta":
                    continue
                text = getattr(getattr(event, "delta", None), "text", None)
                if text:
                    yield text
