"""Google Gemini runtime: real inference over the ``generateContent`` API.

This is a client for a documented HTTP protocol, not a wrapper around an SDK: the app
already knows how to do HTTP, classify failures and redact secrets, and pulling in
``google-generativeai`` would add a dependency that hides both.

Two rules shaped this file:

* **The key never travels in a URL.** Gemini accepts ``?key=…``, which puts the credential
  into every access log between here and the vendor. It is sent as ``x-goog-api-key``, it is
  registered with the redactor at construction time, and it is wiped on ``close()``.
* **A refusal is classified, never flattened.** A 400 naming a bad key is an
  ``AuthDeniedError``; 429 with a quota message is a ``QuotaExhaustedError``; a prompt the
  vendor's safety filter blocked is a distinct, explainable failure rather than an empty
  string that looks like a model with nothing to say.

The wire shape is Gemini's, not OpenAI's: ``contents`` with ``user``/``model`` roles, a
separate ``systemInstruction``, ``generationConfig`` for the knobs, and ``usageMetadata``
for the token counts.
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
from archx_agent.helpers.redaction import redact, register_secret

from .model_runtime import BaseRuntime, ChatResult, GenerationParams, ModelSpec, RuntimeHealth

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"

# Statuses worth a second try: a rate limit or a provider hiccup is transient, a bad key is
# not. Retrying an auth failure only burns quota and hides the real problem.
_RETRYABLE = (RateLimitedError, ProviderOutageError)


class GeminiChatRuntime(BaseRuntime):
    """``generateContent`` over HTTPS, with the same contract as the other runtimes."""

    runtime_id = "gemini"
    provider = "google"
    supports_streaming = True
    is_local = False
    _capabilities = frozenset({"chat"})

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 120.0,
        api_version: str = "v1beta",
        max_retries: int = 2,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._api_key = (api_key or "").strip()
        if self._api_key:
            # Anything this process prints, traces or exports goes through the redactor.
            register_secret(self._api_key)
        self.timeout = timeout
        self.api_version = api_version.strip("/") or "v1beta"
        self.max_retries = max_retries
        self.extra_headers = dict(extra_headers or {})
        host = urllib.parse.urlparse(self.base_url).hostname or ""
        self.is_local = host in ("127.0.0.1", "localhost", "::1")
        # A loopback endpoint is a test/stub server; a hosted one is not.
        self.provider = "google-loopback" if self.is_local else "google"

    # -- transport --------------------------------------------------------
    def _scrub(self, message: str) -> str:
        """Remove the key from anything that will be shown, traced or exported.

        Vendors do echo the credential back in an error ("API key not valid: AIza…"), and a
        redactor that only knows the global registry would still leave it in *this* message
        before it is ever handed to a log call.
        """
        if self._api_key:
            message = message.replace(self._api_key, "[REDACTED]")
        # then the shared redactor, so the same token appears everywhere and known credential
        # shapes are caught even when they are not this runtime's key
        return redact(message)

    def available(self) -> tuple[bool, str]:
        if not self.base_url:
            return False, "no base_url configured"
        if not self._api_key:
            return False, (
                "no API key resolved; register it as a credential reference "
                "(secret://env/GEMINI_API_KEY) when the model is registered"
            )
        return True, "ready"

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{self.api_version}/{path.lstrip('/')}"

    def _headers(self, *, stream: bool) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        }
        if self._api_key:
            headers["x-goog-api-key"] = self._api_key
        headers.update(self.extra_headers)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = self._url(path)
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = self._headers(stream=False)
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
                if isinstance(error, _RETRYABLE) and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(min(2**attempt * 0.25, 4.0))
                    continue
                raise error from None
            except (socket.timeout, TimeoutError) as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    time.sleep(min(2**attempt * 0.25, 4.0))
                    continue
                raise NetworkFailureError(
                    f"timed out calling {_safe_url(url)}", provider=self.provider
                ) from exc
            except urllib.error.URLError as exc:
                raise NetworkFailureError(
                    f"cannot reach {_safe_url(url)}: {exc.reason}",
                    provider=self.provider,
                    endpoint=_safe_url(url),
                ) from exc
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedOutputError(
                f"endpoint {_safe_url(url)} returned a non-JSON body", provider=self.provider
            ) from exc
        if not isinstance(parsed, dict):
            raise MalformedOutputError(
                f"endpoint {_safe_url(url)} returned {type(parsed).__name__}, expected an object",
                provider=self.provider,
            )
        return parsed

    def _classify_http(self, status: int, payload: dict[str, Any] | str, url: str) -> ProviderError:
        message = self._scrub(_extract_error_message(payload))
        status_text = _extract_status(payload)
        lower = f"{message} {status_text}".lower()
        # Gemini reports both a per-minute rate limit and an exhausted daily quota as 429
        # RESOURCE_EXHAUSTED; only the message distinguishes them, and calling a burst limit
        # "quota exhausted" would tell the user to buy capacity they do not need.
        message_lower = message.lower()
        model = self.spec.model if self.spec else None
        common = {
            "provider": self.provider,
            "model": model or "",
            "status": status,
            "endpoint": _safe_url(url),
        }
        if status in (401, 403) or "api key not valid" in lower or "api_key_invalid" in lower \
                or "unauthenticated" in lower or "permission_denied" in lower:
            return AuthDeniedError(f"authentication failed: {message}", **common)
        if status == 404 or "not found" in lower:
            if "model" in lower:
                return ModelNotFoundError(f"model not found: {message}", **common)
            return InvalidRequestError(f"endpoint not found: {message}", **common)
        if status == 402 or "billing" in lower:
            return EntitlementError(f"entitlement problem: {message}", **common)
        if status == 429 or "resource_exhausted" in lower:
            if any(word in message_lower for word in ("quota", "billing", "credits")):
                return QuotaExhaustedError(f"quota exhausted: {message}", **common)
            return RateLimitedError(f"rate limited: {message}", **common)
        if status in (500, 502, 503, 504) or "unavailable" in lower:
            return ProviderOutageError(f"provider unavailable: {message}", **common)
        if status in (413, 507):
            return ResourceExhaustedError(f"resource limit: {message}", **common)
        if status in (400, 422):
            if "context" in lower and ("length" in lower or "window" in lower or "token" in lower):
                return InvalidRequestError(f"context length exceeded: {message}", **common)
            return InvalidRequestError(f"invalid request: {message}", **common)
        if status == 405:
            return UnsupportedOperationError(
                f"operation not supported by this endpoint: {message}", **common
            )
        return ProviderError(f"HTTP {status}: {message}", **common)

    # -- protocol ---------------------------------------------------------
    def health(self) -> RuntimeHealth:
        try:
            data = self._request("GET", "models", query={"pageSize": "1"})
        except ProviderError as exc:
            return RuntimeHealth(
                ok=False,
                detail=f"{type(exc).__name__}: {exc.message}",
                capabilities=tuple(self._capabilities),
            )
        total = len(data.get("models") or [])
        return RuntimeHealth(
            ok=True,
            detail=f"reachable; {total} model(s) on the first page",
            loaded=self.loaded,
            capabilities=tuple(self._capabilities),
        )

    def list_models(self) -> list[dict[str, Any]]:
        data = self._request("GET", "models")
        models = data.get("models")
        if not isinstance(models, list):
            raise MalformedOutputError("model list response is malformed", provider=self.provider)
        return [entry for entry in models if isinstance(entry, dict)]

    @staticmethod
    def _contents(messages: Sequence[dict[str, str]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Translate chat messages into Gemini's `contents` plus `systemInstruction`.

        The vendor's protocol alternates `user` and `model` turns, so consecutive turns from
        the same side are merged instead of being sent as an invalid transcript.
        """
        system_chunks: list[str] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user").lower()
            text = str(message.get("content") or "")
            if role == "system":
                if text.strip():
                    system_chunks.append(text)
                continue
            gemini_role = "model" if role in ("assistant", "model") else "user"
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"].append({"text": text})
            else:
                contents.append({"role": gemini_role, "parts": [{"text": text}]})
        if not contents:
            # The API rejects an empty `contents`; a lone system prompt still needs a turn.
            contents = [{"role": "user", "parts": [{"text": "\n\n".join(system_chunks) or " "}]}]
            system_chunks = []
        system = {"parts": [{"text": "\n\n".join(system_chunks)}]} if system_chunks else None
        return system, contents

    @staticmethod
    def _generation_config(params: GenerationParams) -> dict[str, Any]:
        config: dict[str, Any] = {
            "temperature": params.temperature,
            "topP": params.top_p,
            "maxOutputTokens": params.max_tokens,
        }
        if params.stop:
            config["stopSequences"] = list(params.stop)[:5]
        return config

    def _reply_text(self, data: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        """Pull the text, the finish reason and the usage out of one response."""
        feedback = data.get("promptFeedback") or {}
        blocked = feedback.get("blockReason")
        candidates = data.get("candidates")
        if blocked and not candidates:
            raise ProviderError(
                f"the prompt was blocked by content policy ({blocked}); nothing was generated",
                provider=self.provider,
                model=self.spec.model if self.spec else "",
                status=400,
            )
        if not isinstance(candidates, list) or not candidates:
            raise MalformedOutputError(
                f"response has no candidates: {json.dumps(data)[:200]}", provider=self.provider
            )
        candidate = candidates[0] or {}
        parts = ((candidate.get("content") or {}).get("parts")) or []
        text = "".join(
            part.get("text") or ""
            for part in parts
            if isinstance(part, dict) and not part.get("thought")
        )
        finish = str(candidate.get("finishReason") or "STOP")
        usage = data.get("usageMetadata") or {}
        if not text.strip():
            # An empty answer with a real finish reason is a refusal, not a silent success.
            raise MalformedOutputError(
                f"the model returned no text (finishReason {finish}"
                + (f", blockReason {blocked}" if blocked else "")
                + ")",
                provider=self.provider,
            )
        if finish == "MAX_TOKENS":
            finish = "length"
        elif finish in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
            finish = finish.lower()
        else:
            finish = "stop"
        return text, finish, usage

    def chat(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> ChatResult:
        if not self.loaded:
            raise ProviderError("no model loaded; call load() first", provider=self.provider)
        if not self._api_key:
            raise AuthDeniedError(
                "no API key is configured for this Gemini model; register a credential "
                "reference (secret://env/GEMINI_API_KEY) with the model",
                provider=self.provider,
                model=self.spec.model if self.spec else "",
            )
        system, contents = self._contents(messages)
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": self._generation_config(params),
        }
        if system is not None:
            body["systemInstruction"] = system
        started = time.perf_counter()
        data = self._request("POST", f"models/{self._model_path()}:generateContent", body)
        latency = round((time.perf_counter() - started) * 1000, 2)
        text, finish, usage = self._reply_text(data)
        return ChatResult(
            text=text,
            model_id=str(data.get("modelVersion") or (self.spec.model if self.spec else "")),
            prompt_tokens=int(usage.get("promptTokenCount") or 0),
            completion_tokens=int(usage.get("candidatesTokenCount") or 0),
            finish_reason=finish,
            latency_ms=latency,
            raw={
                "total_tokens": int(usage.get("totalTokenCount") or 0),
                "blocked": bool((data.get("promptFeedback") or {}).get("blockReason")),
                "safety_ratings": (data.get("candidates") or [{}])[0].get("safetyRatings") or [],
            },
        )

    def stream(self, messages: Sequence[dict[str, str]], params: GenerationParams) -> Iterator[str]:
        """Server-sent events from ``:streamGenerateContent?alt=sse``."""
        if not self.loaded:
            raise ProviderError("no model loaded; call load() first", provider=self.provider)
        if not self._api_key:
            raise AuthDeniedError(
                "no API key is configured for this Gemini model",
                provider=self.provider,
                model=self.spec.model if self.spec else "",
            )
        system, contents = self._contents(messages)
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": self._generation_config(params),
        }
        if system is not None:
            body["systemInstruction"] = system
        url = self._url(f"models/{self._model_path()}:streamGenerateContent") + "?" + urllib.parse.urlencode({"alt": "sse"})
        request = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers=self._headers(stream=True), method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                for raw_line in response:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    candidates = chunk.get("candidates") or []
                    if not candidates:
                        continue
                    parts = ((candidates[0].get("content") or {}).get("parts")) or []
                    for part in parts:
                        if isinstance(part, dict) and not part.get("thought") and part.get("text"):
                            yield part["text"]
        except urllib.error.HTTPError as exc:
            raise self._classify_http(exc.code, _safe_body(exc), url) from None
        except urllib.error.URLError as exc:
            raise NetworkFailureError(
                f"cannot reach {_safe_url(url)}: {exc.reason}", provider=self.provider
            ) from exc

    def _model_path(self) -> str:
        """The model reference, without a leading `models/` the endpoint already implies."""
        name = (self.spec.model if self.spec else "") or ""
        name = name.strip()
        if name.startswith("models/"):
            name = name[len("models/"):]
        if not name:
            raise InvalidRequestError(
                "no model reference configured; register the model with --model gemini-2.0-flash",
                provider=self.provider,
            )
        return urllib.parse.quote(name, safe="")

    def load(self, spec: ModelSpec) -> None:
        self.spec = spec
        spec.model = spec.model or spec.id

    def close(self) -> None:
        self._api_key = ""
        super().close()


def _safe_url(url: str) -> str:
    """A URL safe to put in an error message or a trace: no query, no credentials."""
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


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
            return str(error.get("message") or error.get("status") or error)
        if isinstance(error, str):
            return error
        if payload.get("message"):
            return str(payload["message"])
        return json.dumps(payload)[:300]
    return str(payload)[:300]


def _extract_status(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("status") or error.get("code") or "")
    return ""


__all__ = ["GeminiChatRuntime", "DEFAULT_BASE_URL"]
