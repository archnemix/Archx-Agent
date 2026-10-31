"""Openai compatible operations for vendor SDK transport."""

from __future__ import annotations

from typing import Any, Iterator

from archx_agent.adapters.model_runtime import ChatResult
from archx_agent.helpers.exceptions import (
    MalformedOutputError,
)
from archx_agent.adapters.sdk_transport.compatibility import (
    _accepts,
    _supported,
    _finish,
)
from archx_agent.adapters.sdk_transport.probe_tools import _OPENAI_PROBE_TOOL


class SdkTransportVendorsOpenaiCompatibleMixin:
    """Vendors Openai Compatible responsibility for SdkTransport."""

    def _openai(self):
        if self._client is None:
            import openai  # noqa: PLC0415 - optional dependency

            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "max_retries": 0,  # the router decides; see the module docstring
                "timeout": self.timeout,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = openai.OpenAI(**kwargs)
        return self._client

    def _mistral_client(self):
        if self._client is None:
            from mistralai.client import Mistral  # noqa: PLC0415

            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["server_url"] = self.base_url
            self._client = Mistral(**kwargs)
        return self._client

    def _openai_compatible_client(self):
        """Clients that ship their own package but speak the OpenAI shape."""
        if self._client is None:
            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "max_retries": 0,
                "timeout": self.timeout,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            if self.key == "groq":
                from groq import Groq  # noqa: PLC0415

                self._client = Groq(**kwargs)
            else:
                from together import Together  # noqa: PLC0415

                self._client = Together(**kwargs)
        return self._client

    def _openai_shaped(self, messages, params, model) -> ChatResult:
        if self.key == "mistral":
            client = self._mistral_client()
        elif self.key in ("groq", "together"):
            client = self._openai_compatible_client()
        else:
            client = self._openai()
        stops = list(params.stop or ())
        if self.key == "mistral":
            call = client.chat.complete
        else:
            call = client.chat.completions.create
        candidates: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "temperature": params.temperature,
            "top_p": params.top_p,
            "stop": stops or None,
            "seed": params.seed,
        }
        # OpenAI gained `max_completion_tokens` and deprecates `max_tokens` for newer models;
        # send exactly one of them, preferring the newer name where the client knows it.
        budget = (
            "max_completion_tokens"
            if _accepts(call, "max_completion_tokens")
            else "max_tokens"
        )
        candidates[budget] = params.max_tokens
        result = call(**_supported(call, candidates))

        choice = (result.choices or [None])[0]
        if choice is None:
            raise MalformedOutputError(
                "the provider returned no choices", provider=self.key
            )
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, list):  # some SDK versions return typed parts
            content = "".join(getattr(part, "text", "") for part in content)
        text = (content or "").strip()
        if not text:
            raise MalformedOutputError(
                "the provider returned an empty message", provider=self.key
            )
        usage = getattr(result, "usage", None)
        return ChatResult(
            text=text,
            model_id=getattr(result, "model", None) or model,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            finish_reason=_finish(getattr(choice, "finish_reason", None)),
            raw={"sdk": self.key, "id": getattr(result, "id", None)},
        )

    def _tools_openai_shaped(self, messages, params, model, tools) -> ChatResult:
        if self.key == "mistral":
            client = self._mistral_client()
            call = client.chat.complete
        elif self.key in ("groq", "together"):
            client = self._openai_compatible_client()
            call = client.chat.completions.create
        else:
            client = self._openai()
            call = client.chat.completions.create
        candidates: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "temperature": params.temperature,
            "tools": tools or _OPENAI_PROBE_TOOL,
            "tool_choice": "auto",
        }
        budget = (
            "max_completion_tokens"
            if _accepts(call, "max_completion_tokens")
            else "max_tokens"
        )
        candidates[budget] = params.max_tokens
        result = call(**_supported(call, candidates))
        choice = (result.choices or [None])[0]
        if choice is None:
            raise MalformedOutputError(
                "the provider returned no choices", provider=self.key
            )
        message = getattr(choice, "message", None)
        calls = getattr(message, "tool_calls", None) or []
        if not calls:
            raise MalformedOutputError(
                "the model answered without calling the tool; tool use is not proven",
                provider=self.key,
            )
        serialised = [
            {
                "id": getattr(c, "id", None),
                "name": getattr(getattr(c, "function", None), "name", None),
                "arguments": getattr(getattr(c, "function", None), "arguments", None),
            }
            for c in calls
        ]
        usage = getattr(result, "usage", None)
        return ChatResult(
            text="",
            model_id=getattr(result, "model", None) or model,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            finish_reason=_finish(getattr(choice, "finish_reason", None)),
            raw={"sdk": self.key, "tool_calls": serialised},
        )

    def _stream_openai_shaped(self, messages, params, model) -> Iterator[str]:
        if self.key == "mistral":
            client = self._mistral_client()
            call = client.chat.stream
        elif self.key in ("groq", "together"):
            client = self._openai_compatible_client()
            call = client.chat.completions.create
        else:
            client = self._openai()
            call = client.chat.completions.create
        candidates: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "temperature": params.temperature,
            "top_p": params.top_p,
            "stop": list(params.stop or ()) or None,
            "stream": True,
        }
        budget = (
            "max_completion_tokens"
            if _accepts(call, "max_completion_tokens")
            else "max_tokens"
        )
        candidates[budget] = params.max_tokens
        events = call(**_supported(call, candidates))
        for event in events:
            # mistralai wraps each chunk in `.data`; the OpenAI-shaped clients do not
            chunk = getattr(event, "data", event)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None) if delta is not None else None
            if text:
                yield text
