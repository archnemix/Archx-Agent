"""HttpChatRuntime completions."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from archx_agent.adapters.chat_payloads import (
    first_message,
    normalized_tool_calls,
    usage_counts,
)
from archx_agent.adapters.model_runtime import ChatResult, GenerationParams
from archx_agent.adapters.reasoning import reasoning_text
from archx_agent.helpers.exceptions import (
    MalformedOutputError,
    ProviderError,
)


class HttpChatRuntimeCompletionsMixin:
    """Completions responsibility for HttpChatRuntime."""

    PROBE_TOOL = {
        "type": "function",
        "function": {
            "name": "record_value",
            "description": "Record one integer value.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
        },
    }

    def chat(
        self, messages: Sequence[dict[str, str]], params: GenerationParams
    ) -> ChatResult:
        if not self.loaded:
            raise ProviderError(
                "no model loaded; call load() first", provider=self.provider
            )
        body: dict[str, Any] = {
            "model": self.spec.model if self.spec else None,
            "messages": [
                {"role": m["role"], "content": m["content"]} for m in messages
            ],
            "temperature": params.temperature,
            "top_p": params.top_p,
            "max_tokens": params.max_tokens,
            "stream": False,
        }
        if params.stop:
            body["stop"] = list(params.stop)
        if params.seed is not None:
            body["seed"] = params.seed
        started = time.perf_counter()
        data = self._request("POST", self._chat_path(), body)
        latency = round((time.perf_counter() - started) * 1000, 2)
        choice, message = first_message(data, self.provider)
        text = message.get("content")
        if not isinstance(text, str):
            raise MalformedOutputError(
                "response message has no text content", provider=self.provider
            )
        prompt_tokens, completion_tokens = usage_counts(data, self.provider)
        return ChatResult(
            text=text,
            model_id=str(data.get("model") or (self.spec.model if self.spec else "")),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=str(choice.get("finish_reason") or "stop"),
            latency_ms=latency,
            raw={"id": data.get("id"), "reasoning": reasoning_text(message, self.provider)},
        )

    def chat_with_tools(
        self,
        messages: Sequence[dict[str, str]],
        params: GenerationParams,
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResult:
        """One turn with a tool offered, parsed into ``raw["tool_calls"]``.

        Separate from :meth:`chat` on purpose: a model that answers *without* calling the tool
        has not demonstrated tool use, and the probe must be able to see the difference.
        """
        if not self.loaded:
            raise ProviderError(
                "no model loaded; call load() first", provider=self.provider
            )
        body: dict[str, Any] = {
            "model": self.spec.model if self.spec else None,
            "messages": [
                {"role": m["role"], "content": m["content"]} for m in messages
            ],
            "temperature": params.temperature,
            "top_p": params.top_p,
            "max_tokens": params.max_tokens,
            "tools": tools or [self.PROBE_TOOL],
            "tool_choice": "auto",
            "stream": False,
        }
        if params.stop:
            body["stop"] = list(params.stop)
        if params.seed is not None:
            body["seed"] = params.seed
        started = time.perf_counter()
        data = self._request("POST", self._chat_path(), body)
        latency = round((time.perf_counter() - started) * 1000, 2)
        choice, message = first_message(data, self.provider)
        calls = normalized_tool_calls(message, self.provider)
        text = message.get("content") or ""
        prompt_tokens, completion_tokens = usage_counts(data, self.provider)
        return ChatResult(
            text=text if isinstance(text, str) else "",
            model_id=str(data.get("model") or (self.spec.model if self.spec else "")),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=str(choice.get("finish_reason") or "tool_calls"),
            latency_ms=latency,
            # one shape everywhere: {"id", "name", "arguments"} - the OpenAI wire form nests the
            # name under "function", and the router should not have to know that
            raw={
                "id": data.get("id"),
                "tool_calls": calls,
            },
        )
