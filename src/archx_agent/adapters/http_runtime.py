"""OpenAI-compatible HTTP runtime (llama_cpp.server, Ollama, vLLM, LM Studio).

This is a *real* client: it speaks the documented HTTP protocol and classifies
failures precisely. It is used for both local servers (``is_local=True`` when the
host is loopback) and remote providers.

Failure classification matters: a 429 (rate limit / quota) must never be
reported as "model does not exist", and a 401 must never be retried.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator, Sequence

from archx_agent.helpers.exceptions import (
    AuthDeniedError,
    EntitlementError,
    InvalidRequestError,
    MalformedOutputError,
    ModelNotFoundError,
    NetworkFailureError,
    ProviderError,
    ProviderOutageError,
    QuotaExhaustedError,
    RateLimitedError,
    ResourceExhaustedError,
    UnsupportedOperationError,
)
from archx_agent.helpers.redaction import register_secret

from .model_runtime import BaseRuntime, ChatResult, GenerationParams, ModelSpec, RuntimeHealth


class HttpChatRuntime(BaseRuntime):
    """Chat completions over an OpenAI-compatible endpoint."""

    runtime_id = "openai-http"
    provider = "openai-compatible"
    supports_streaming = True
    _capabilities = frozenset({"chat"})

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 120.0,
        is_local: bool | None = None,
        provider: str | None = None,
        runtime_id: str | None = None,
        extra_headers: dict[str, str] | None = None,
        max_retries: int = 2,
    ) -> None:
        super().__init__()
        if not base_url:
            raise InvalidRequestError("base_url is required")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        if api_key:
            register_secret(api_key)
        self.timeout = timeout
        self.provider = provider or self.provider
        self.runtime_id = runtime_id or self.runtime_id
        self.extra_headers = dict(extra_headers or {})
        self.max_retries = max_retries
        host = urllib.parse.urlparse(self.base_url).hostname or ""
        self.is_local = is_local if is_local is not None else host in ("127.0.0.1", "localhost", "::1")

    # -- transport --------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        if not self.base_url:
            return False, "no base_url configured"
        return True, "ready"

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        headers.update(self.extra_headers)
        attempt = 0
        while True:
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - user-configured endpoint
                    raw = response.read()
                    break
            except urllib.error.HTTPError as exc:
                payload = _safe_body(exc)
                error = self._classify_http(exc.code, payload, url)
                if isinstance(error, (RateLimitedError, ProviderOutageError)) and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(min(2**attempt * 0.25, 4.0))
                    continue
                raise error from None
            except (socket.timeout, TimeoutError) as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    time.sleep(min(2**attempt * 0.25, 4.0))
                    continue
                raise NetworkFailureError(f"timed out calling {url}", provider=self.provider) from exc
            except urllib.error.URLError as exc:
                raise NetworkFailureError(
                    f"cannot reach {url}: {exc.reason}", provider=self.provider, endpoint=url
                ) from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedOutputError(
                f"endpoint {url} returned a non-JSON body", provider=self.provider
            ) from exc

    def _classify_http(self, status: int, payload: dict[str, Any] | str, url: str) -> ProviderError:
        message = _extract_error_message(payload) or f"HTTP {status}"
        lower = str(message).lower()
        model = self.spec.model if self.spec else None
        common = {"provider": self.provider, "model": model or "", "status": status, "endpoint": url}
        if status in (401, 403):
            return AuthDeniedError(f"authentication failed: {message}", **common)
        if status == 404:
            if "model" in lower:
                return ModelNotFoundError(f"model not found: {message}", **common)
            return InvalidRequestError(f"endpoint not found: {message}", **common)
        if status == 402 or "insufficient" in lower or "billing" in lower:
            return EntitlementError(f"entitlement problem: {message}", **common)
        if status == 429:
            if any(word in lower for word in ("quota", "exceeded your current", "billing")):
                return QuotaExhaustedError(f"quota exhausted: {message}", **common)
            return RateLimitedError(f"rate limited: {message}", **common)
        if status in (500, 502, 503, 504):
            return ProviderOutageError(f"provider unavailable: {message}", **common)
        if status in (413, 507):
            return ResourceExhaustedError(f"resource limit: {message}", **common)
        if status == 422 or status == 400:
            if "context" in lower and ("length" in lower or "window" in lower):
                return InvalidRequestError(f"context length exceeded: {message}", **common)
            return InvalidRequestError(f"invalid request: {message}", **common)
        if status == 405:
            return UnsupportedOperationError(f"operation not supported by this endpoint: {message}", **common)
        return ProviderError(f"HTTP {status}: {message}", **common)

    def _chat_path(self) -> str:
        return "/v1/chat/completions" if not self.base_url.endswith("/v1") else "/chat/completions"

    # -- protocol ---------------------------------------------------------
    def health(self) -> RuntimeHealth:
        try:
            data = self._request("GET", "/v1/models" if not self.base_url.endswith("/v1") else "/models")
        except ProviderError as exc:
            return RuntimeHealth(ok=False, detail=f"{type(exc).__name__}: {exc.message}", capabilities=tuple(self._capabilities))
        models = []
        if isinstance(data, dict):
            models = [entry.get("id") for entry in data.get("data", []) if isinstance(entry, dict)]
        return RuntimeHealth(
            ok=True,
            detail=f"reachable; {len(models)} model(s) advertised",
            loaded=self.loaded,
            capabilities=tuple(self._capabilities),
        )

    def list_models(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/v1/models" if not self.base_url.endswith("/v1") else "/models")
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise MalformedOutputError("model list response is malformed", provider=self.provider)
        return [entry for entry in data["data"] if isinstance(entry, dict)]

    def chat(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> ChatResult:
        if not self.loaded:
            raise ProviderError("no model loaded; call load() first", provider=self.provider)
        body: dict[str, Any] = {
            "model": self.spec.model if self.spec else None,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
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
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            raise MalformedOutputError(
                f"response has no choices: {str(data)[:200]}", provider=self.provider
            )
        message = choices[0].get("message") or {}
        text = message.get("content")
        if not isinstance(text, str):
            raise MalformedOutputError("response message has no text content", provider=self.provider)
        usage = data.get("usage") or {}
        return ChatResult(
            text=text,
            model_id=str(data.get("model") or (self.spec.model if self.spec else "")),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            finish_reason=str(choices[0].get("finish_reason") or "stop"),
            latency_ms=latency,
            raw={"id": data.get("id")},
        )

    def stream(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> Iterator[str]:
        """Server-sent events. Falls back to a single chunk if streaming is off."""
        if not self.loaded:
            raise ProviderError("no model loaded; call load() first", provider=self.provider)
        body = {
            "model": self.spec.model if self.spec else None,
            "messages": [dict(m) for m in messages],
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
            "stream": True,
        }
        url = f"{self.base_url}{self._chat_path()}"
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        headers.update(self.extra_headers)
        request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                for raw_line in response:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield piece
        except urllib.error.HTTPError as exc:
            raise self._classify_http(exc.code, _safe_body(exc), url) from None
        except urllib.error.URLError as exc:
            raise NetworkFailureError(f"cannot reach {url}: {exc.reason}", provider=self.provider) from exc

    def load(self, spec: ModelSpec) -> None:
        self.spec = spec
        spec.model = spec.model or spec.id

    def close(self) -> None:
        self._api_key = ""
        super().close()


def _safe_body(exc: urllib.error.HTTPError) -> dict[str, Any] | str:
    try:
        raw = exc.read()
    except Exception:  # noqa: BLE001
        return ""
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return raw.decode("utf-8", "replace")[:1000]


def _extract_error_message(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or error)
        if isinstance(error, str):
            return error
        if payload.get("message"):
            return str(payload["message"])
        return json.dumps(payload)[:300]
    return str(payload)[:300]


__all__ = ["HttpChatRuntime"]
