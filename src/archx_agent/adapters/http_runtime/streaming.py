"""HttpChatRuntime streaming."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Sequence

from archx_agent.adapters.chat_payloads import stream_piece
from archx_agent.adapters.http_runtime.error_payloads import _safe_body
from archx_agent.adapters.model_runtime import GenerationParams
from archx_agent.adapters.reasoning import reasoning_text
from archx_agent.helpers.exceptions import (
    MalformedOutputError,
    NetworkFailureError,
    ProviderError,
)


class HttpChatRuntimeStreamingMixin:
    """Streaming responsibility for HttpChatRuntime."""

    def stream(
        self, messages: Sequence[dict[str, str]], params: GenerationParams
    ) -> Iterator[str]:
        """Compatibility interface: yield answer text only."""
        for kind, text in self.stream_events(messages, params):
            if kind == "content":
                yield text

    def stream_events(
        self, messages: Sequence[dict[str, str]], params: GenerationParams
    ) -> Iterator[tuple[str, str]]:
        """Yield distinct answer/reasoning deltas from an OpenAI-compatible stream."""
        if not self.loaded:
            raise ProviderError(
                "no model loaded; call load() first", provider=self.provider
            )
        body = {
            "model": self.spec.model if self.spec else None,
            "messages": [dict(m) for m in messages],
            "temperature": params.temperature,
            "top_p": params.top_p,
            "max_tokens": params.max_tokens,
            "stream": True,
        }
        if params.stop:
            body["stop"] = list(params.stop)
        if params.seed is not None:
            body["seed"] = params.seed
        url = f"{self.base_url}{self._chat_path()}"
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        headers.update(self.extra_headers)
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                for raw_line in response:
                    try:
                        line = raw_line.decode("utf-8").strip()
                    except UnicodeDecodeError as exc:
                        raise MalformedOutputError(
                            "stream event is not UTF-8", provider=self.provider
                        ) from exc
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError as exc:
                        raise MalformedOutputError(
                            "stream event is not valid JSON", provider=self.provider
                        ) from exc
                    piece = stream_piece(chunk, self.provider)
                    choices = chunk.get("choices")
                    if choices:
                        delta = choices[0].get("delta")
                        if isinstance(delta, dict):
                            reason = reasoning_text(delta, self.provider)
                            if reason:
                                yield "reasoning", reason
                    if piece:
                        yield "content", piece
        except urllib.error.HTTPError as exc:
            raise self._classify_http(exc.code, _safe_body(exc), url) from None
        except (TimeoutError, ConnectionError) as exc:
            raise NetworkFailureError(
                f"stream interrupted calling {url}", provider=self.provider
            ) from exc
        except urllib.error.URLError as exc:
            raise NetworkFailureError(
                f"cannot reach {url}: {exc.reason}", provider=self.provider
            ) from exc
        except OSError as exc:
            raise NetworkFailureError(
                f"stream connection failed calling {url}", provider=self.provider
            ) from exc
