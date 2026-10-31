"""Validate OpenAI-shaped completion payloads shared by HTTP and native adapters.

Untrusted model output must produce domain errors, not incidental AttributeError or
ValueError exceptions. These helpers do not execute tools or infer capabilities.
"""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import MalformedOutputError, ProviderError


def first_message(data: Any, provider: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(data, dict):
        raise MalformedOutputError(
            "completion response must be an object", provider=provider
        )
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise MalformedOutputError("response has no valid choices", provider=provider)
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise MalformedOutputError(
            "response message must be an object", provider=provider
        )
    return choices[0], message


def usage_counts(data: dict[str, Any], provider: str) -> tuple[int, int]:
    usage = data.get("usage")
    if usage is None:
        return 0, 0
    if not isinstance(usage, dict):
        raise MalformedOutputError(
            "response usage must be an object", provider=provider
        )
    counts = []
    for key in ("prompt_tokens", "completion_tokens"):
        value = usage.get(key)
        if value is None:
            value = 0
        # Preserve compatibility with integer strings, not floats or JSON booleans.
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise MalformedOutputError(f"invalid {key} count", provider=provider)
        try:
            count = int(value)
        except ValueError as exc:
            raise MalformedOutputError(
                f"invalid {key} count", provider=provider
            ) from exc
        if count < 0:
            raise MalformedOutputError(f"invalid {key} count", provider=provider)
        counts.append(count)
    return counts[0], counts[1]


def normalized_tool_calls(
    message: dict[str, Any], provider: str
) -> list[dict[str, Any]]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        raise MalformedOutputError(
            "the model answered without calling the tool; tool use is not proven",
            provider=provider,
        )
    result = []
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
            raise MalformedOutputError(
                "malformed function tool call", provider=provider
            )
        function = call["function"]
        name, arguments = function.get("name"), function.get("arguments")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(arguments, str)
        ):
            raise MalformedOutputError(
                "tool call needs a name and encoded arguments", provider=provider
            )
        result.append({"id": call.get("id"), "name": name, "arguments": arguments})
    return result


def stream_piece(chunk: Any, provider: str) -> str | None:
    if not isinstance(chunk, dict):
        raise MalformedOutputError("stream event must be an object", provider=provider)
    if chunk.get("error") is not None:
        raise ProviderError(
            "provider reported an error inside the stream", provider=provider
        )
    choices = chunk.get("choices")
    if choices is None or choices == []:
        return None  # usage-only events and empty metadata carry no text
    if not isinstance(choices, list) or not isinstance(choices[0], dict):
        raise MalformedOutputError("stream choices are malformed", provider=provider)
    delta = choices[0].get("delta")
    if delta is None:
        return None
    if not isinstance(delta, dict):
        raise MalformedOutputError("stream delta must be an object", provider=provider)
    piece = delta.get("content")
    if piece is not None and not isinstance(piece, str):
        raise MalformedOutputError("stream content must be text", provider=provider)
    return piece
