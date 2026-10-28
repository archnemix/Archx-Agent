"""Official-SDK transports.

Archx already speaks two wire protocols directly (`openai-http` for anything
OpenAI-compatible, `gemini` for Google's REST shape). That is the right default: it needs no
extra dependency and it cannot drift with a vendor's client release.

But "we build the HTTP body ourselves" is a claim, and the cheapest way to check it is to let
the vendor's own client build the same request. This module does exactly that: it drives the
**official Python SDKs** (`openai`, `anthropic`, `google-genai`, `mistralai`) and translates
their objects into the same `ChatResult` every other runtime returns.

Design notes that matter:

* **Optional, never required.** An SDK is imported lazily. If it is absent, `available()`
  returns a precise reason and the runtime refuses instead of pretending; `pytest` skips.
* **No hidden retries.** Every client is constructed with ``max_retries=0``. Retrying is the
  router's decision (it knows which errors are retryable and records the fallback); an SDK
  that silently retries twice would make one refused call look like three.
* **One error taxonomy.** Vendors raise different exception trees; they are mapped by class
  name *and* HTTP status into the same domain errors the HTTP runtimes use, so a 401 from
  OpenAI, Anthropic or Google produces the same sentence and the same `retryable=False`.
* **The key is scrubbed before it can be shown.** Some SDKs put the request (and therefore the
  credential) in the exception's message.
"""

from __future__ import annotations

import inspect
import re
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from archx_agent.adapters.model_runtime import ChatResult, GenerationParams
from archx_agent.helpers.exceptions import (
    AuthDeniedError,
    InvalidRequestError,
    MalformedOutputError,
    ModelNotFoundError,
    NetworkFailureError,
    ProviderError,
    ProviderOutageError,
    QuotaExhaustedError,
    RateLimitedError,
)
from archx_agent.helpers.redaction import redact
from archx_agent.managers.providers import is_loopback_url

#: words that mean "you are out of plan", not "slow down"
_QUOTA_WORDS = ("quota", "billing", "credit", "insufficient", "payment", "plan limit", "exceeded your current")


@dataclass(frozen=True)
class SdkSpec:
    """One vendor's official client, and how to point it at an endpoint."""

    key: str                      # the value used in the catalogue: "openai", "anthropic", …
    label: str
    package: str                  # pip distribution name
    import_name: str              # what `import ...` needs
    provider_template: str        # the provider catalogue template slug
    env_var: str
    default_base_url: str | None
    api_style: str
    streaming: bool
    notes: str = ""
    #: does this client need a credential before it can be used at all? A local Ollama daemon
    #: does not, so a missing key must not mark the model unusable.
    key_required: bool = True


SDKS: dict[str, SdkSpec] = {
    "openai": SdkSpec(
        key="openai",
        label="OpenAI",
        package="openai",
        import_name="openai",
        provider_template="openai",
        env_var="OPENAI_API_KEY",
        default_base_url="https://api.openai.com/v1",
        api_style="openai",
        streaming=True,
    ),
    "anthropic": SdkSpec(
        key="anthropic",
        label="Anthropic",
        package="anthropic",
        import_name="anthropic",
        provider_template="anthropic",
        env_var="ANTHROPIC_API_KEY",
        default_base_url="https://api.anthropic.com",
        api_style="anthropic",
        streaming=True,
    ),
    "google": SdkSpec(
        key="google",
        label="Google Gemini",
        package="google-genai",
        import_name="google.genai",
        provider_template="google",
        env_var="GEMINI_API_KEY",
        default_base_url=None,   # the SDK owns it; an override must be explicit
        api_style="gemini",
        streaming=True,
    ),
    "mistral": SdkSpec(
        key="mistral",
        label="Mistral",
        package="mistralai",
        import_name="mistralai.client",
        provider_template="mistral",
        env_var="MISTRAL_API_KEY",
        default_base_url="https://api.mistral.ai",
        api_style="openai",
        streaming=True,
    ),
    "groq": SdkSpec(
        key="groq",
        label="Groq",
        package="groq",
        import_name="groq",
        provider_template="groq",
        env_var="GROQ_API_KEY",
        default_base_url="https://api.groq.com/openai/v1",
        api_style="openai",
        streaming=True,
    ),
    "together": SdkSpec(
        key="together",
        label="Together",
        package="together",
        import_name="together",
        provider_template="together",
        env_var="TOGETHER_API_KEY",
        default_base_url="https://api.together.xyz/v1",
        api_style="openai",
        streaming=True,
    ),
    "cohere": SdkSpec(
        key="cohere",
        label="Cohere",
        package="cohere",
        import_name="cohere",
        provider_template="cohere",
        env_var="COHERE_API_KEY",
        default_base_url="https://api.cohere.com",
        api_style="custom",
        streaming=True,
    ),
    "ollama": SdkSpec(
        key="ollama",
        label="Ollama",
        package="ollama",
        import_name="ollama",
        provider_template="ollama",
        env_var="OLLAMA_API_KEY",
        # No default: the client's own default is a local daemon on 127.0.0.1:11434, and
        # Ollama's cloud endpoint is opt-in. Guessing one would silently pick a different
        # service than the user expected.
        default_base_url=None,
        api_style="custom",
        streaming=True,
        key_required=False,
    ),
}


def sdk_available(key: str) -> tuple[bool, str]:
    """Is the vendor's client importable here? ``(ok, reason_if_not)``."""
    spec = SDKS.get(key)
    if spec is None:
        return False, f"unknown SDK {key!r} (known: {', '.join(sorted(SDKS))})"
    try:
        __import__(spec.import_name)
    except Exception as exc:  # noqa: BLE001 - any import failure means "not usable here"
        return False, (
            f"the {spec.label} SDK is not installed ({spec.import_name}: "
            f"{type(exc).__name__}); install it with `pip install {spec.package}`"
        )
    return True, "ready"


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------
_STATUS_IN_TEXT = re.compile(r"(?i)(?:\bstatus\b|\bhttp\b|\bcode\b)[^0-9]{0,4}([45]\d\d)|^\s*([45]\d\d)\b")


def _status_of(exc: BaseException) -> int | None:
    """The HTTP status behind a vendor exception, however that vendor reports it.

    Clients disagree here: OpenAI and Anthropic set ``status_code``, `google-genai` raises a
    ``ClientError`` whose text starts with ``401 None.``, and `mistralai` wraps the status in a
    sentence (``API error occurred: Status 401``). Guessing from the class name alone threw away
    the one fact that distinguishes "bad key" from "server is down", so the text is read too.
    """
    for attribute in ("status_code", "status", "http_status", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    response = getattr(exc, "response", None)
    for attribute in ("status_code", "status"):
        code = getattr(response, attribute, None)
        if isinstance(code, int) and 100 <= code <= 599:
            return code
    match = _STATUS_IN_TEXT.search(str(exc) or "")
    if match:
        return int(match.group(1) or match.group(2))
    return None


def classify_sdk_error(exc: BaseException, *, key: str = "", provider: str = "") -> ProviderError:
    """Map a vendor SDK exception onto the domain taxonomy.

    Vendors differ in class names and in whether they carry a status code, so both are
    consulted; when they disagree the name wins (it is the more specific statement).
    """
    name = type(exc).__name__
    status = _status_of(exc)
    message = str(exc) or name
    if key:
        message = message.replace(key, "[REDACTED]")
    message = redact(message)
    lower = f"{name} {message}".lower()
    detail = {"sdk_error": name, "status": status}

    if status in (401, 403) or any(
        word in lower
        for word in ("authentication", "permissiondenied", "unauthorized", "invalid api key", "api key not valid")
    ):
        return AuthDeniedError(f"authentication failed: {message}", provider=provider, **detail)
    if "notfound" in lower or status == 404:
        return ModelNotFoundError(f"model not found: {message}", provider=provider, **detail)
    if "ratelimit" in lower or status == 429:
        # Same trap as the raw Gemini client: a 429 can be a burst limit or a spent plan, and
        # telling a user to buy capacity over a burst limit costs them money.
        if any(word in lower for word in _QUOTA_WORDS):
            return QuotaExhaustedError(f"entitlement problem: {message}", provider=provider, **detail)
        return RateLimitedError(f"rate limited: {message}", provider=provider, **detail)
    if any(word in lower for word in ("internal server", "overloaded", "serviceunavailable", "servererror")) or (status or 0) >= 500:
        return ProviderOutageError(f"provider unavailable: {message}", provider=provider, **detail)
    if any(word in lower for word in ("connection", "timeout", "timed out", "network")):
        return NetworkFailureError(f"could not reach the provider: {message}", provider=provider, **detail)
    if any(word in lower for word in ("badrequest", "invalidrequest", "unprocessable", "invalidargument")) or status == 400:
        return InvalidRequestError(f"the provider rejected the request: {message}", provider=provider, **detail)
    return ProviderError(f"the provider call failed: {message}", provider=provider, **detail)


# --------------------------------------------------------------------------
# transports
# --------------------------------------------------------------------------
@dataclass
class SdkTransport:
    """A thin adapter over one vendor client. One method per thing worth measuring."""

    key: str
    api_key: str
    base_url: str | None = None
    timeout: float = 60.0
    _client: Any = field(default=None, repr=False)

    # -- plumbing ---------------------------------------------------------
    @property
    def spec(self) -> SdkSpec:
        return SDKS[self.key]

    def is_loopback(self) -> bool:
        """Is this client talking to a daemon on this machine?"""
        return is_loopback_url(self.base_url or "")

    def available(self) -> tuple[bool, str]:
        ok, why = sdk_available(self.key)
        if not ok:
            return ok, why
        if self.api_key:
            return True, "ready"
        if self.spec.key_required:
            return False, f"no API key: set {self.spec.env_var} or a secret:// reference"
        if not self.is_loopback():
            # the client would work without a credential, but the endpoint would reject it -
            # saying "no key" now beats a 401 later
            return False, (
                f"no API key: {self.spec.label} at {self.base_url} is remote and needs one "
                f"({self.spec.env_var})"
            )
        return True, f"ready: a local {self.spec.label} needs no key"

    def close(self) -> None:
        client = self._client
        self._client = None
        self.api_key = ""
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - closing must not raise
                pass

    def _fail(self, exc: BaseException) -> ProviderError:
        return classify_sdk_error(exc, key=self.api_key, provider=self.key)

    # -- the calls --------------------------------------------------------
    def chat(
        self,
        messages: Sequence[dict[str, str]],
        params: GenerationParams,
        *,
        model: str,
    ) -> ChatResult:
        started = time.perf_counter()
        try:
            if self.key in ("openai", "mistral", "groq", "together"):
                result = self._openai_shaped(messages, params, model)
            elif self.key == "anthropic":
                result = self._anthropic(messages, params, model)
            elif self.key == "google":
                result = self._google(messages, params, model)
            elif self.key == "cohere":
                result = self._cohere(messages, params, model)
            elif self.key == "ollama":
                result = self._ollama_chat(messages, params, model)
            else:  # pragma: no cover - guarded by SDKS
                raise ProviderError(f"no transport for {self.key!r}")
        except ProviderError:
            raise
        except BaseException as exc:  # noqa: BLE001 - every vendor failure becomes one of ours
            raise self._fail(exc) from exc
        result.latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        return result

    def stream(
        self,
        messages: Sequence[dict[str, str]],
        params: GenerationParams,
        *,
        model: str,
    ) -> Iterator[str]:
        """Yield text as the vendor sends it.

        Each client spells streaming differently (a `stream=True` flag, a separate `*_stream`
        method, or an event type on every chunk), so there is one small parser per style. All
        of them are measured against a loopback server in `tests/test_sdk_m22.py`; a client
        whose events this code got wrong fails there rather than in a user's terminal.
        """
        try:
            if self.key in ("openai", "mistral", "groq", "together"):
                yield from self._stream_openai_shaped(messages, params, model)
            elif self.key == "anthropic":
                yield from self._stream_anthropic(messages, params, model)
            elif self.key == "google":
                yield from self._stream_google(messages, params, model)
            elif self.key == "cohere":
                yield from self._stream_cohere(messages, params, model)
            elif self.key == "ollama":
                yield from self._stream_ollama(messages, params, model)
            else:  # pragma: no cover - guarded by SDKS
                raise ProviderError(f"no streaming transport for {self.key!r}")
        except ProviderError:
            raise
        except BaseException as exc:  # noqa: BLE001 - every vendor failure becomes one of ours
            raise self._fail(exc) from exc

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
        budget = "max_completion_tokens" if _accepts(call, "max_completion_tokens") else "max_tokens"
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

    def _stream_anthropic(self, messages, params, model) -> Iterator[str]:
        client = self._anthropic_client()
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        turns = [
            {"role": "assistant" if m.get("role") == "assistant" else "user", "content": m.get("content", "")}
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
        with client.messages.create(**_supported(client.messages.create, candidates)) as events:
            for event in events:
                if getattr(event, "type", "") != "content_block_delta":
                    continue
                text = getattr(getattr(event, "delta", None), "text", None)
                if text:
                    yield text

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
            contents = [types.Content(role="user", parts=[types.Part(text="".join(system_parts) or "hello")])]
        config = types.GenerateContentConfig(
            temperature=params.temperature,
            top_p=params.top_p,
            max_output_tokens=int(params.max_tokens),
            system_instruction="\n".join(system_parts) or None,
        )
        for chunk in client.models.generate_content_stream(model=model, contents=contents, config=config):
            text = getattr(chunk, "text", None)
            if text:
                yield text

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
            text = getattr(getattr(getattr(event, "delta", None), "message", None), "content", None)
            text = getattr(text, "text", None) if text is not None else None
            if text:
                yield text

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

    def list_models(self) -> list[str]:
        """Ask the vendor what it serves. Some SDKs cannot enumerate; that is reported."""
        try:
            if self.key == "openai":
                return [item.id for item in self._openai().models.list().data]
            if self.key == "mistral":
                from mistralai.client import Mistral  # noqa: PLC0415 - optional dependency

                client = Mistral(api_key=self.api_key, server_url=self.base_url) if self.base_url else Mistral(api_key=self.api_key)
                return [item.id for item in client.models.list().data]
            if self.key == "google":
                client = self._genai()
                return [getattr(item, "name", "") for item in client.models.list()]
            if self.key in ("groq", "together"):
                return [item.id for item in self._openai_compatible_client().models.list().data]
            if self.key == "ollama":
                response = self._ollama_client().list()
                models = getattr(response, "models", None) or response.get("models", [])
                return [getattr(item, "model", None) or item.get("model", "") for item in models]
            if self.key == "cohere":
                return [item.name for item in self._cohere_client().models.list().models]
        except BaseException as exc:  # noqa: BLE001
            raise self._fail(exc) from exc
        return []

    # -- per-vendor request shapes ---------------------------------------
    def _openai(self):
        if self._client is None:
            import openai  # noqa: PLC0415 - optional dependency

            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "max_retries": 0,          # the router decides; see the module docstring
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
            kwargs: dict[str, Any] = {"api_key": self.api_key, "max_retries": 0, "timeout": self.timeout}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            if self.key == "groq":
                from groq import Groq  # noqa: PLC0415

                self._client = Groq(**kwargs)
            else:
                from together import Together  # noqa: PLC0415

                self._client = Together(**kwargs)
        return self._client

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

    def _genai(self):
        if self._client is None:
            from google import genai  # noqa: PLC0415
            from google.genai import types  # noqa: PLC0415

            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["http_options"] = types.HttpOptions(base_url=self.base_url, timeout=int(self.timeout * 1000))
            self._client = genai.Client(**kwargs)
        return self._client

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
        budget = "max_completion_tokens" if _accepts(call, "max_completion_tokens") else "max_tokens"
        candidates[budget] = params.max_tokens
        result = call(**_supported(call, candidates))

        choice = (result.choices or [None])[0]
        if choice is None:
            raise MalformedOutputError("the provider returned no choices", provider=self.key)
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, list):  # some SDK versions return typed parts
            content = "".join(getattr(part, "text", "") for part in content)
        text = (content or "").strip()
        if not text:
            raise MalformedOutputError("the provider returned an empty message", provider=self.key)
        usage = getattr(result, "usage", None)
        return ChatResult(
            text=text,
            model_id=getattr(result, "model", None) or model,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            finish_reason=_finish(getattr(choice, "finish_reason", None)),
            raw={"sdk": self.key, "id": getattr(result, "id", None)},
        )

    def _anthropic(self, messages, params, model) -> ChatResult:
        client = self._anthropic_client()
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        turns = [
            {"role": "assistant" if m.get("role") == "assistant" else "user", "content": m.get("content", "")}
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
        result = client.messages.create(**_supported(client.messages.create, candidates))
        blocks = [getattr(block, "text", "") for block in (getattr(result, "content", None) or [])]
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
            raise MalformedOutputError("the provider returned an empty message", provider=self.key)
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
        if message is None and isinstance(result, dict):  # older clients return plain dicts
            message = result.get("message", {})
        text = (getattr(message, "content", None) or (message.get("content") if isinstance(message, dict) else "") or "").strip()
        if not text:
            raise MalformedOutputError("the provider returned an empty message", provider=self.key)
        return ChatResult(
            text=text,
            model_id=getattr(result, "model", None) or model,
            prompt_tokens=int(getattr(result, "prompt_eval_count", 0) or 0),
            completion_tokens=int(getattr(result, "eval_count", 0) or 0),
            finish_reason="length" if getattr(result, "done_reason", "") == "length" else "stop",
            raw={"sdk": self.key},
        )

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
            contents = [types.Content(role="user", parts=[types.Part(text="".join(system_parts) or "hello")])]
        config = types.GenerateContentConfig(
            temperature=params.temperature,
            top_p=params.top_p,
            max_output_tokens=int(params.max_tokens),
            system_instruction="\n".join(system_parts) or None,
            stop_sequences=list(params.stop or ()) or None,
        )
        result = client.models.generate_content(model=model, contents=contents, config=config)
        text = (getattr(result, "text", "") or "").strip()
        if not text:
            feedback = getattr(result, "prompt_feedback", None)
            blocked = getattr(feedback, "block_reason", None)
            if blocked:
                raise ProviderError(f"the prompt was blocked ({blocked}); nothing was generated", provider=self.key)
            raise MalformedOutputError("the provider returned no text", provider=self.key)
        usage = getattr(result, "usage_metadata", None)
        candidates = getattr(result, "candidates", None) or []
        finish = _finish(getattr(candidates[0], "finish_reason", None)) if candidates else "stop"
        return ChatResult(
            text=text,
            model_id=getattr(result, "model_version", None) or model,
            prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            completion_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
            finish_reason=finish,
            raw={"sdk": self.key, "total_tokens": getattr(usage, "total_token_count", None)},
        )


def _accepts(callable_obj: Any, name: str) -> bool:
    """Does this SDK call take ``name``?

    Vendors move parameters between releases (``anthropic`` 2.x dropped ``temperature`` from
    ``messages.create``; OpenAI grew ``max_completion_tokens`` beside ``max_tokens``). Passing a
    parameter a client does not accept is a TypeError instead of a request, and dropping one it
    wants is a silently different temperature - so ask, and send what is accepted.
    """
    try:
        parameters = inspect.signature(callable_obj).parameters
    except (TypeError, ValueError):  # builtins and C extensions do not expose a signature
        return True
    if name in parameters:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())


def _supported(callable_obj: Any, candidates: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in candidates.items() if _accepts(callable_obj, key)}


def _finish(value: Any) -> str:
    """Normalise a vendor finish/stop reason to Archx's three states."""
    text = str(getattr(value, "value", value) or "").lower()
    if not text or text in {"none", "stop", "end_turn", "stop_sequence", "eos"}:
        return "stop"
    if "max" in text or "length" in text:
        return "length"
    if "safety" in text or "block" in text or "content_filter" in text or "refusal" in text:
        return "safety"
    if "tool" in text or "function" in text:
        return "tool_calls"
    return "stop"


def transport_for(key: str, *, api_key: str, base_url: str | None = None, timeout: float = 60.0) -> SdkTransport:
    if key not in SDKS:
        raise ProviderError(f"unknown SDK {key!r} (known: {', '.join(sorted(SDKS))})")
    return SdkTransport(key=key, api_key=api_key, base_url=base_url, timeout=timeout)


__all__ = [
    "SDKS",
    "SdkSpec",
    "SdkTransport",
    "sdk_available",
    "classify_sdk_error",
    "transport_for",
]
