"""The official-SDK path: four vendors' own clients, driven against a real socket.

Archx already builds these requests by hand (`http_runtime`, `gemini_runtime`). This suite
exists because that is a claim about *other people's* protocols, and the cheapest independent
check is to let the vendor's client build the request and parse the response. So every test
here goes through `openai`, `anthropic`, `google-genai` or `mistralai` - never through our own
HTTP code - against a local server that speaks the documented shapes.

What would quietly go wrong, and is therefore what the tests check:

* a parameter the installed SDK version does not accept, which is a TypeError instead of a
  request (anthropic 2.x dropped `temperature` from `messages.create`);
* two token-budget names sent at once (`max_tokens` *and* `max_completion_tokens`);
* an SDK that retries twice on its own, turning one refused call into three;
* the credential leaking into a URL, an exception message or the model row;
* a 429 for a spent plan reported as "slow down", or the reverse;
* the new runtime quietly sitting outside the M20 consent gate.

The SDKs are optional dependencies. Each test that needs one skips with a precise message if it
is not installed, so the suite still runs on a machine with no vendor clients.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from archx_agent.adapters.model_runtime import GenerationParams
from archx_agent.adapters.sdk_transport import SDKS, sdk_available, transport_for
from archx_agent.application.workspace import NETWORK_RUNTIMES, open_workspace
from archx_agent.helpers.exceptions import (
    ArchxError,
    AuthDeniedError,
    ModelNotFoundError,
    NetworkFailureError,
    ProviderOutageError,
    QuotaExhaustedError,
    RateLimitedError,
)

CLI = os.path.join(os.path.dirname(sys.executable), "archx-agent")
KEY = "sdk-test-key-0123456789"

requires_openai = pytest.mark.skipif(not sdk_available("openai")[0], reason="openai SDK not installed")
requires_anthropic = pytest.mark.skipif(not sdk_available("anthropic")[0], reason="anthropic SDK not installed")
requires_google = pytest.mark.skipif(not sdk_available("google")[0], reason="google-genai SDK not installed")
requires_mistral = pytest.mark.skipif(not sdk_available("mistral")[0], reason="mistralai SDK not installed")
requires_groq = pytest.mark.skipif(not sdk_available("groq")[0], reason="groq SDK not installed")
requires_together = pytest.mark.skipif(not sdk_available("together")[0], reason="together SDK not installed")
requires_cohere = pytest.mark.skipif(not sdk_available("cohere")[0], reason="cohere SDK not installed")
requires_ollama = pytest.mark.skipif(not sdk_available("ollama")[0], reason="ollama SDK not installed")


# --------------------------------------------------------------------------
# one server, three protocols
# --------------------------------------------------------------------------
class _State:
    mode = "ok"            # ok | error
    status = 500
    body: dict = {}
    attempts = 0
    empty_reply = False
    ignore_tools = False
    seen: list[dict] = []

    @classmethod
    def reset(cls) -> None:
        cls.mode, cls.status, cls.body = "ok", 500, {}
        cls.attempts = 0
        cls.empty_reply = False
        cls.ignore_tools = False
        cls.seen = []


def _known_path(path: str) -> bool:
    """The routes these protocols really use, and nothing else."""
    bare = path.split("?")[0].rstrip("/")
    if bare.endswith("/chat/completions"):
        # exactly one prefix per client: groq owns /openai/v1, the rest own /v1
        return bare.endswith("/v1/chat/completions") and "/v1/v1/" not in bare and "/v1/openai/" not in bare
    return (
        bare.endswith("/messages")
        or bare.endswith("/v2/chat")
        or bare.endswith("/api/chat")
        or bare.endswith("/api/tags")
        or "generatecontent" in bare.lower()  # :generateContent vs :streamGenerateContent
        or bare.endswith("/models")
        or bare.endswith("/openai/v1/chat/completions")
    )


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep pytest output readable
        pass

    def _send(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_sse(self, events: list[str], *, done: str | None = "data: [DONE]\n\n") -> None:
        """Server-sent events, close-delimited so the clients stop on the connection ending."""
        body = "".join(events) + (done or "")
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def _stream(self, body: dict) -> None:
        """The streaming shape for whichever route was hit. Paths are matched exactly."""
        path = self.path
        if path.endswith("/v2/chat"):
            frames = [
                {"type": "message-start", "delta": {"message": {"role": "assistant", "content": []}}},
                {"type": "content-start", "delta": {"message": {"content": []}}},
                {"type": "content-delta", "delta": {"message": {"content": {"text": "answer "}}}},
                {"type": "content-delta", "delta": {"message": {"content": {"text": "from cohere"}}}},
                {"type": "message-end", "delta": {"finish_reason": "COMPLETE",
                                                  "usage": {"tokens": {"input_tokens": 13, "output_tokens": 5}}}},
            ]
            return self._send_sse([f"event: {f['type']}\ndata: {json.dumps(f)}\n\n" for f in frames], done=None)
        if path.endswith("/api/chat"):
            frames = [
                {"model": "llama-stub", "message": {"role": "assistant", "content": "answer "}, "done": False},
                {"model": "llama-stub", "message": {"role": "assistant", "content": "from ollama"}, "done": False},
                {"model": "llama-stub", "message": {"role": "assistant", "content": ""}, "done": True,
                 "done_reason": "stop", "prompt_eval_count": 21, "eval_count": 6},
            ]
            return self._send_sse([json.dumps(f) + "\n" for f in frames], done=None)
        if "streamGenerateContent" in path:
            frames = [
                {"candidates": [{"content": {"role": "model", "parts": [{"text": "answer "}]}}]},
                {"candidates": [{"content": {"role": "model", "parts": [{"text": "from google"}]},
                                 "finishReason": "STOP"}]},
            ]
            return self._send_sse([f"data: {json.dumps(f)}\n\n" for f in frames], done=None)
        if path.endswith("/messages"):
            frames = [
                {"type": "message_start", "message": {"id": "msg_1", "role": "assistant", "content": [],
                                                      "usage": {"input_tokens": 12, "output_tokens": 0}}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "answer "}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "from anthropic"}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 4}},
                {"type": "message_stop"},
            ]
            return self._send_sse([f"event: {f['type']}\ndata: {json.dumps(f)}\n\n" for f in frames], done=None)
        # the OpenAI shape, which groq, together and mistral share
        frames = [
            {"id": "c1", "object": "chat.completion.chunk", "model": "openai-stub",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": "answer "}, "finish_reason": None}]},
            {"id": "c1", "object": "chat.completion.chunk", "model": "openai-stub",
             "choices": [{"index": 0, "delta": {"content": "from openai"}, "finish_reason": None}]},
            {"id": "c1", "object": "chat.completion.chunk", "model": "openai-stub",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        return self._send_sse([f"data: {json.dumps(f)}\n\n" for f in frames])

    def do_GET(self):  # noqa: N802
        """The Gemini SDK streams over a GET, so this route needs its own door."""
        _State.attempts += 1
        _State.seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                            "body": {}, "method": "GET"})
        if "streamGenerateContent" in self.path:
            return self._stream({})
        return self._send(404, {"error": "no such route"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            body = {"_raw": raw.decode("utf-8", "replace")}
        _State.attempts += 1
        _State.seen.append({
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": body,
        })
        if _State.mode == "error":
            return self._send(_State.status, _State.body)
        # The stub is strict on purpose. An earlier version answered any path, which let a wrong
        # base URL pass: groq was given /openai/v1 and requested /openai/v1/openai/v1/..., and a
        # permissive stub returned 200. A doubled path must fail here, as it did on a real server.
        if not _known_path(self.path):
            return self._send(404, {"error": {"message": "File Not Found", "type": "not_found_error",
                                              "code": 404}})
        # the Gemini client POSTs to :streamGenerateContent; the others set stream=true and POST
        if "streamGenerateContent" in self.path or body.get("stream") is True:
            return self._stream(body)
        if body.get("tools"):
            # a tool was offered: answer by calling it, unless the test asked for a plain reply
            if _State.ignore_tools:
                return self._send(200, {
                    "id": "chatcmpl_stub", "object": "chat.completion", "created": 1, "model": "openai-stub",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "I will not call it."},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 2},
                })
            return self._send(200, {
                "id": "chatcmpl_stub", "object": "chat.completion", "created": 1, "model": "openai-stub",
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function",
                                    "function": {"name": "record_value", "arguments": "{\"value\": 1}"}}]}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 5},
            })
        if _State.empty_reply:
            return self._send(200, {
                "id": "x", "object": "chat.completion", "created": 1, "model": "m",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": ""},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0},
            })
        if self.path.endswith("/messages"):
            return self._send(200, {
                "id": "msg_stub", "type": "message", "role": "assistant",
                "model": "claude-stub",
                "content": [{"type": "text", "text": "answer from anthropic"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 12, "output_tokens": 4},
            })
        if self.path.endswith("/v2/chat"):
            return self._send(200, {
                "id": "co1", "finish_reason": "COMPLETE",
                "message": {"role": "assistant",
                            "content": [{"type": "text", "text": "answer from cohere"}]},
                "usage": {"tokens": {"input_tokens": 13, "output_tokens": 5}},
            })
        if self.path.endswith("/api/chat"):
            return self._send(200, {
                "model": "llama-stub", "created_at": "2026-01-01T00:00:00Z",
                "message": {"role": "assistant", "content": "answer from ollama"},
                "done": True, "done_reason": "stop",
                "prompt_eval_count": 21, "eval_count": 6,
            })
        if "generateContent" in self.path:
            return self._send(200, {
                "candidates": [{
                    "content": {"role": "model", "parts": [{"text": "answer from google"}]},
                    "finishReason": "STOP",
                }],
                "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 3, "totalTokenCount": 12},
                "modelVersion": "gemini-stub",
            })
        return self._send(200, {
            "id": "chatcmpl_stub", "object": "chat.completion", "created": 1, "model": "openai-stub",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "answer from openai"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
        })


@pytest.fixture()
def stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _State.reset()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


PARAMS = GenerationParams(temperature=0.1, top_p=0.9, max_tokens=32)
MESSAGES = [{"role": "system", "content": "be terse"}, {"role": "user", "content": "hello"}]


# What each client appends to whatever base it is given. This is measured, not read: the paths
# were taken off a loopback server (see tests/test_sdk_m22.py::TestPaths).
UPSTREAM_PATH = {
    "openai": "/chat/completions",
    "groq": "/openai/v1/chat/completions",
    "together": "/v1/chat/completions",
    "mistral": "/v1/chat/completions",
    "anthropic": "/v1/messages",
    "cohere": "/v2/chat",
    "ollama": "/api/chat",
}


def _transport(key: str, url: str, *, base: str | None = None):
    return transport_for(key, api_key=KEY, base_url=(base if base is not None else url))


# --------------------------------------------------------------------------
# the catalogue of clients
# --------------------------------------------------------------------------
class TestCatalogue:
    def test_every_sdk_knows_its_package_and_its_own_environment_variable(self):
        assert set(SDKS) == {
            "openai", "anthropic", "google", "mistral", "groq", "together", "cohere", "ollama",
        }
        for key, spec in SDKS.items():
            assert spec.package and spec.import_name and spec.env_var, key
            assert spec.provider_template, key

    def test_an_unknown_sdk_is_refused_by_name(self):
        with pytest.raises(ProviderErrorTypes.provider) as exc:
            transport_for("nonesuch", api_key=KEY)
        assert "unknown SDK" in exc.value.message

    def test_availability_reports_the_install_line(self):
        ok, why = sdk_available("openai")
        assert ok is True, why


class ProviderErrorTypes:
    from archx_agent.helpers.exceptions import ProviderError as provider  # noqa: N801


# --------------------------------------------------------------------------
# the requests the vendor clients build
# --------------------------------------------------------------------------
class TestOpenAI:
    @requires_openai
    def test_the_answer_is_parsed_and_the_key_travels_in_a_header(self, stub):
        transport = _transport("openai", stub, base=stub + "/v1")
        try:
            result = transport.chat(MESSAGES, PARAMS, model="gpt-test")
        finally:
            transport.close()
        assert result.text == "answer from openai"
        assert (result.prompt_tokens, result.completion_tokens) == (7, 2)
        seen = _State.seen[-1]
        assert seen["path"] == "/v1/chat/completions"
        assert seen["headers"]["authorization"] == f"Bearer {KEY}"
        assert KEY not in seen["path"]
        assert seen["body"]["model"] == "gpt-test"
        assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]

    @requires_openai
    def test_only_one_token_budget_is_sent(self, stub):
        """Newer clients know both names; sending both is a 400 on some models."""
        transport = _transport("openai", stub, base=stub + "/v1")
        try:
            transport.chat(MESSAGES, PARAMS, model="gpt-test")
        finally:
            transport.close()
        body = _State.seen[-1]["body"]
        assert ("max_tokens" in body) != ("max_completion_tokens" in body)

    @requires_openai
    def test_the_client_does_not_retry_behind_our_back(self, stub):
        _State.mode, _State.status = "error", 500
        _State.body = {"error": {"message": "boom", "type": "server_error"}}
        transport = _transport("openai", stub, base=stub + "/v1")
        with pytest.raises(ProviderOutageError):
            transport.chat(MESSAGES, PARAMS, model="gpt-test")
        transport.close()
        assert _State.attempts == 1, "one refused call must be one request, not three"


class TestAnthropic:
    @requires_anthropic
    def test_the_system_prompt_is_top_level_and_the_answer_is_parsed(self, stub):
        transport = _transport("anthropic", stub)
        try:
            result = transport.chat(MESSAGES, PARAMS, model="claude-test")
        finally:
            transport.close()
        assert result.text == "answer from anthropic"
        assert (result.prompt_tokens, result.completion_tokens) == (12, 4)
        assert result.finish_reason == "stop"
        seen = _State.seen[-1]
        assert seen["path"].endswith("/v1/messages")
        # anthropic 1.x sent `x-api-key`; 2.x sends a bearer token. Either is fine, a URL is not.
        carried = seen["headers"].get("x-api-key") or seen["headers"].get("authorization", "")
        assert KEY in carried
        assert seen["body"]["system"] == "be terse"
        assert [m["role"] for m in seen["body"]["messages"]] == ["user"]
        assert KEY not in seen["path"]

    @requires_anthropic
    def test_sampling_parameters_are_sent_only_if_this_client_accepts_them(self, stub):
        """anthropic 2.x dropped temperature from messages.create; sending it is a TypeError."""
        transport = _transport("anthropic", stub)
        try:
            transport.chat(MESSAGES, PARAMS, model="claude-test")
        finally:
            transport.close()
        body = _State.seen[-1]["body"]
        assert "max_tokens" in body
        assert body.get("temperature", 0.1) == 0.1


class TestGoogle:
    @requires_google
    def test_contents_roles_and_usage_are_translated(self, stub):
        transport = _transport("google", stub)
        try:
            result = transport.chat(MESSAGES, PARAMS, model="gemini-test")
        finally:
            transport.close()
        assert result.text == "answer from google"
        assert (result.prompt_tokens, result.completion_tokens) == (9, 3)
        seen = _State.seen[-1]
        assert ":generateContent" in seen["path"]
        assert seen["headers"]["x-goog-api-key"] == KEY
        assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "be terse"
        assert [c["role"] for c in seen["body"]["contents"]] == ["user"]
        assert KEY not in seen["path"]

    @requires_google
    def test_the_generation_config_carries_the_knobs(self, stub):
        transport = _transport("google", stub)
        try:
            transport.chat(MESSAGES, PARAMS, model="gemini-test")
        finally:
            transport.close()
        config = _State.seen[-1]["body"]["generationConfig"]
        assert config["maxOutputTokens"] == 32
        assert config["temperature"] == 0.1


class TestMistral:
    @requires_mistral
    def test_mistral_uses_its_own_client_on_the_openai_shape(self, stub):
        transport = _transport("mistral", stub)
        try:
            result = transport.chat(MESSAGES, PARAMS, model="mistral-test")
        finally:
            transport.close()
        assert result.text == "answer from openai"  # the stub's OpenAI-shaped answer
        seen = _State.seen[-1]
        assert seen["path"].endswith("/v1/chat/completions")
        assert seen["headers"]["authorization"] == f"Bearer {KEY}"
        assert seen["body"]["model"] == "mistral-test"


# --------------------------------------------------------------------------
# the error taxonomy
# --------------------------------------------------------------------------
class TestErrors:
    @pytest.mark.parametrize("key, base", [
        ("openai", "/v1"), ("anthropic", ""), ("google", ""), ("mistral", ""),
        ("groq", "/openai/v1"), ("together", "/v1"), ("cohere", ""),
    ])
    def test_a_401_is_an_auth_failure_for_every_client(self, stub, key, base):
        if not sdk_available(key)[0]:
            pytest.skip(f"{key} SDK not installed")
        _State.mode, _State.status = "error", 401
        _State.body = {"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}}
        transport = _transport(key, stub, base=stub + base)
        with pytest.raises(AuthDeniedError) as exc:
            transport.chat(MESSAGES, PARAMS, model="m")
        transport.close()
        assert KEY not in exc.value.message

    @pytest.mark.parametrize("key, base", [("openai", "/v1"), ("anthropic", ""), ("google", "")])
    def test_a_429_naming_quota_is_an_entitlement_problem_not_a_rate_limit(self, stub, key, base):
        if not sdk_available(key)[0]:
            pytest.skip(f"{key} SDK not installed")
        _State.mode, _State.status = "error", 429
        _State.body = {"error": {"message": "You exceeded your current quota, please check your billing details"}}
        transport = _transport(key, stub, base=stub + base)
        with pytest.raises(QuotaExhaustedError):
            transport.chat(MESSAGES, PARAMS, model="m")
        transport.close()

    @pytest.mark.parametrize("key, base", [("openai", "/v1"), ("anthropic", ""), ("google", "")])
    def test_a_plain_429_is_a_rate_limit(self, stub, key, base):
        if not sdk_available(key)[0]:
            pytest.skip(f"{key} SDK not installed")
        _State.mode, _State.status = "error", 429
        _State.body = {"error": {"message": "Too many requests, please slow down"}}
        transport = _transport(key, stub, base=stub + base)
        with pytest.raises(RateLimitedError) as exc:
            transport.chat(MESSAGES, PARAMS, model="m")
        transport.close()
        assert "rate limited" in exc.value.message.lower()

    @pytest.mark.parametrize("key, base", [("openai", "/v1"), ("anthropic", "")])
    def test_a_404_is_model_not_found(self, stub, key, base):
        if not sdk_available(key)[0]:
            pytest.skip(f"{key} SDK not installed")
        _State.mode, _State.status = "error", 404
        _State.body = {"error": {"message": "model does not exist", "type": "not_found_error"}}
        transport = _transport(key, stub, base=stub + base)
        with pytest.raises(ModelNotFoundError):
            transport.chat(MESSAGES, PARAMS, model="m")
        transport.close()

    def test_an_unreachable_endpoint_is_a_network_failure(self):
        if not sdk_available("openai")[0]:
            pytest.skip("openai SDK not installed")
        # nothing is listening on port 9 (discard); the connection is refused immediately
        transport = transport_for("openai", api_key=KEY, base_url="http://127.0.0.1:9/v1", timeout=2.0)
        with pytest.raises((NetworkFailureError, ProviderOutageError)) as exc:
            transport.chat(MESSAGES, PARAMS, model="m")
        transport.close()
        assert KEY not in exc.value.message

    def test_a_provider_that_says_nothing_is_malformed_not_empty(self, stub):
        from archx_agent.helpers.exceptions import MalformedOutputError

        if not sdk_available("openai")[0]:
            pytest.skip("openai SDK not installed")
        _State.empty_reply = True
        transport = _transport("openai", stub, base=stub + "/v1")
        try:
            with pytest.raises(MalformedOutputError) as exc:
                transport.chat(MESSAGES, PARAMS, model="m")
        finally:
            transport.close()
        assert "empty" in exc.value.message.lower()

    def test_the_classifier_never_echoes_the_key(self):
        class AuthenticationError(Exception):
            status_code = 401

        from archx_agent.adapters.sdk_transport import classify_sdk_error

        exc = classify_sdk_error(AuthenticationError(f"bad key {KEY}"), key=KEY)
        assert KEY not in exc.message
        assert "[REDACTED]" in exc.message


class TestCredential:
    def test_a_runtime_without_a_key_refuses_before_any_request(self, stub):
        from archx_agent.adapters.sdk_runtime import SdkChatRuntime
        from archx_agent.adapters.model_runtime import ModelSpec

        runtime = SdkChatRuntime("openai", api_key="", base_url=stub + "/v1")
        runtime.load(ModelSpec(id="m", provider="openai", runtime="sdk", model="x"))
        ok, why = runtime.available()
        assert ok is False and "no API key" in why
        with pytest.raises(AuthDeniedError):
            runtime.chat(MESSAGES, PARAMS)
        assert _State.seen == []

    def test_close_wipes_the_key_and_the_client(self, stub):
        from archx_agent.adapters.sdk_runtime import SdkChatRuntime
        from archx_agent.adapters.model_runtime import ModelSpec

        runtime = SdkChatRuntime("openai", api_key=KEY, base_url=stub + "/v1")
        runtime.load(ModelSpec(id="m", provider="openai", runtime="sdk", model="x"))
        runtime.chat(MESSAGES, PARAMS)
        runtime.close()
        assert runtime._api_key == ""
        assert runtime._transport._client is None
        assert runtime.loaded is False


# --------------------------------------------------------------------------
# the workspace: registration, availability, the gate, a real turn
# --------------------------------------------------------------------------
@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("SDK_TEST_KEY", KEY)
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


class TestWorkspace:
    def test_the_sdk_runtime_is_gated_like_every_other_network_runtime(self):
        assert "sdk" in NETWORK_RUNTIMES

    def test_registration_stores_a_reference_and_refuses_a_literal_key(self, ws):
        from archx_agent.helpers.exceptions import ValidationError

        record = ws.register_sdk("oai", sdk="openai", model_ref="gpt-test",
                                 credential_ref="secret://env/OPENAI_API_KEY")
        assert record.runtime == "sdk"
        assert record.facts["sdk"] == "openai"
        assert record.user_metadata["credential_ref"] == "secret://env/OPENAI_API_KEY"
        assert KEY not in json.dumps(record.to_dict())
        with pytest.raises(ValidationError):
            ws.register_sdk("bad", sdk="openai", model_ref="x", credential_ref=KEY)

    def test_an_uninstalled_sdk_is_reported_not_assumed(self, ws, monkeypatch):
        record = ws.register_sdk("oai", sdk="openai", model_ref="gpt-test")
        monkeypatch.setattr(
            "archx_agent.application.workspace.models.availability.sdk_available",
            lambda key: (False, f"the {key} SDK is not installed"),
        )
        ready, why = ws.runtime_availability(record)
        assert ready is False
        assert "not installed" in why

    def test_a_missing_secret_reference_is_explained(self, ws):
        record = ws.register_sdk("oai", sdk="openai", model_ref="gpt-test",
                                 credential_ref="secret://env/SURELY_NOT_SET_ANYWHERE")
        ready, why = ws.runtime_availability(record)
        assert ready is False
        assert "could not be resolved" in why

    def test_a_loopback_endpoint_chats_end_to_end_through_the_sdk(self, ws, stub, monkeypatch):
        monkeypatch.setenv("SDK_TEST_KEY", KEY)
        record = ws.register_sdk("oai", sdk="openai", model_ref="gpt-test",
                                 base_url=stub + "/v1", credential_ref="secret://env/SDK_TEST_KEY")
        ready, why = ws.runtime_availability(record)
        assert ready is True, why
        reply = ws.chat.send("hello", model_id=record.id)
        assert reply.text == "answer from openai"
        assert reply.simulated is False
        assert reply.prompt_tokens == 7
        assert ws.tasks.get(reply.task["id"]).status == "completed"

    def test_a_remote_sdk_endpoint_obeys_the_same_four_gates(self, ws):
        record = ws.register_sdk("oai", sdk="openai", model_ref="gpt-test")
        with pytest.raises(ArchxError) as exc:
            ws.chat.send("hello", model_id=record.id)
        assert "model.local_only is true" in exc.value.message

    def test_the_probe_measures_through_the_sdk(self, ws, stub, monkeypatch):
        monkeypatch.setenv("SDK_TEST_KEY", KEY)
        record = ws.register_sdk("oai", sdk="openai", model_ref="gpt-test",
                                 base_url=stub + "/v1", credential_ref="secret://env/SDK_TEST_KEY")
        result = ws.router.probe(record.id, capability="chat")
        assert result["outcome"] == "passed", result["detail"]


# --------------------------------------------------------------------------
# the CLI
# --------------------------------------------------------------------------
def cli(*args, home, key=KEY):
    env = {**os.environ, "ARCHX_PATHS_HOME": str(home)}
    env.pop("ARCHX_ALLOW_SIMULATED", None)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY"):
        env.pop(name, None)
    if key is not None:
        env["OPENAI_API_KEY"] = key
    return subprocess.run([CLI, *args], capture_output=True, text=True, env=env, timeout=180)


class TestCli:
    def test_sdks_lists_what_is_installed_and_where_the_key_comes_from(self, tmp_path):
        result = cli("models", "sdks", home=tmp_path / "home")
        assert result.returncode == 0, result.stderr
        for key in SDKS:
            assert key in result.stdout
        assert "OPENAI_API_KEY" in result.stdout

    def test_add_sdk_registers_and_reports_readiness(self, tmp_path, stub):
        home = tmp_path / "home"
        result = cli("models", "add-sdk", "--name", "oai", "--sdk", "openai",
                     "--model", "gpt-test", "--base-url", stub + "/v1", home=home)
        assert result.returncode == 0, result.stderr
        assert "runtime=sdk" in result.stdout
        assert "secret://env/OPENAI_API_KEY" in result.stdout
        assert KEY not in result.stdout

    def test_a_literal_key_is_refused_by_the_cli(self, tmp_path):
        result = cli("models", "add-sdk", "--name", "oai", "--sdk", "openai",
                     "--model", "gpt-test", "--credential-ref", KEY, home=tmp_path / "home")
        assert result.returncode == 2
        assert "secret://" in result.stderr
        assert KEY not in result.stderr

    def test_an_unknown_sdk_is_a_usage_error(self, tmp_path):
        result = cli("models", "add-sdk", "--name", "x", "--sdk", "nonesuch",
                     "--model", "m", home=tmp_path / "home")
        assert result.returncode == 2
        assert "unknown SDK" in result.stderr

    def test_chat_runs_through_the_sdk_from_the_cli(self, tmp_path, stub):
        home = tmp_path / "home"
        assert cli("models", "add-sdk", "--name", "oai", "--sdk", "openai", "--model", "gpt-test",
                   "--base-url", stub + "/v1", home=home).returncode == 0
        result = cli("chat", "--message", "hello", "--model", "oai", home=home)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "answer from openai" in result.stdout
        assert KEY not in result.stdout + result.stderr


class TestGroqAndTogether:
    @requires_groq
    def test_groq_appends_its_own_openai_prefix(self, stub):
        # the base is the origin; groq adds /openai/v1 itself (measured on a real server)
        transport = _transport("groq", stub)
        try:
            result = transport.chat(MESSAGES, PARAMS, model="llama-3.1-8b-instant")
        finally:
            transport.close()
        assert result.text == "answer from openai"
        seen = _State.seen[-1]
        assert seen["path"] == "/openai/v1/chat/completions", seen["path"]
        assert seen["headers"]["authorization"] == f"Bearer {KEY}"
        assert seen["body"]["model"] == "llama-3.1-8b-instant"

    @requires_together
    def test_together_appends_its_own_v1_prefix(self, stub):
        transport = _transport("together", stub)
        try:
            result = transport.chat(MESSAGES, PARAMS, model="meta-llama/Llama-3-8b")
        finally:
            transport.close()
        assert result.text == "answer from openai"
        assert _State.seen[-1]["path"] == "/v1/chat/completions"
        assert _State.seen[-1]["body"]["model"] == "meta-llama/Llama-3-8b"


class TestCohere:
    @requires_cohere
    def test_the_v2_chat_shape_is_parsed(self, stub):
        transport = _transport("cohere", stub)
        try:
            result = transport.chat(MESSAGES, PARAMS, model="command-r")
        finally:
            transport.close()
        assert result.text == "answer from cohere"
        assert (result.prompt_tokens, result.completion_tokens) == (13, 5)
        seen = _State.seen[-1]
        assert seen["path"].endswith("/v2/chat")
        assert seen["headers"]["authorization"] == f"Bearer {KEY}"
        assert seen["body"]["model"] == "command-r"
        assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]


class TestOllama:
    @requires_ollama
    def test_a_local_daemon_needs_no_key_and_is_still_usable(self, stub):
        """The one client where a missing credential is the normal case."""
        transport = transport_for("ollama", api_key="", base_url=stub)
        ok, why = transport.available()
        assert ok is True, why
        try:
            result = transport.chat(MESSAGES, PARAMS, model="llama3.2")
        finally:
            transport.close()
        assert result.text == "answer from ollama"
        assert (result.prompt_tokens, result.completion_tokens) == (21, 6)
        seen = _State.seen[-1]
        assert seen["path"].endswith("/api/chat")
        assert "authorization" not in seen["headers"], "a local daemon should not receive a key"

    @requires_ollama
    def test_a_key_is_sent_to_a_remote_ollama(self, stub):
        transport = transport_for("ollama", api_key=KEY, base_url=stub)
        try:
            transport.chat(MESSAGES, PARAMS, model="llama3.2")
        finally:
            transport.close()
        assert _State.seen[-1]["headers"]["authorization"] == f"Bearer {KEY}"

    @requires_ollama
    def test_the_options_block_carries_the_knobs(self, stub):
        transport = transport_for("ollama", api_key="", base_url=stub)
        try:
            transport.chat(MESSAGES, PARAMS, model="llama3.2")
        finally:
            transport.close()
        options = _State.seen[-1]["body"]["options"]
        assert options["num_predict"] == 32
        assert options["temperature"] == 0.1


class TestOllamaWorkspace:
    @requires_ollama
    def test_a_loopback_ollama_model_is_ready_without_a_key(self, ws, stub):
        record = ws.register_sdk("local-llama", sdk="ollama", model_ref="llama3.2", base_url=stub,
                                 credential_ref="secret://env/OLLAMA_API_KEY")
        ready, why = ws.runtime_availability(record)
        assert ready is True, why
        reply = ws.chat.send("hello", model_id=record.id)
        assert reply.text == "answer from ollama"
        assert reply.simulated is False


class TestStreaming:
    """Every client streams its own way; each parser is measured, not assumed."""

    def _collect(self, key: str, url: str, base: str | None = None) -> str:
        transport = _transport(key, url, base=base)
        try:
            return "".join(transport.stream(MESSAGES, PARAMS, model="stub-model"))
        finally:
            transport.close()

    @requires_openai
    def test_openai_deltas_are_joined(self, stub):
        assert self._collect("openai", stub, base=stub + "/v1") == "answer from openai"
        assert _State.seen[-1]["path"] == "/v1/chat/completions"
        assert _State.seen[-1]["body"]["stream"] is True

    @requires_groq
    def test_groq_streams_the_same_shape(self, stub):
        assert self._collect("groq", stub) == "answer from openai"
        assert _State.seen[-1]["path"] == "/openai/v1/chat/completions"

    @requires_together
    def test_together_streams_the_same_shape(self, stub):
        assert self._collect("together", stub) == "answer from openai"
        assert _State.seen[-1]["path"] == "/v1/chat/completions"

    @requires_mistral
    def test_mistral_wraps_each_chunk_in_data(self, stub):
        assert self._collect("mistral", stub) == "answer from openai"

    @requires_anthropic
    def test_anthropic_content_block_deltas(self, stub):
        assert self._collect("anthropic", stub) == "answer from anthropic"

    @requires_google
    def test_google_streams_over_a_get(self, stub):
        assert self._collect("google", stub) == "answer from google"
        assert "streamGenerateContent" in _State.seen[-1]["path"]

    @requires_cohere
    def test_cohere_content_delta_events(self, stub):
        assert self._collect("cohere", stub) == "answer from cohere"

    @requires_ollama
    def test_ollama_newline_delimited_chunks(self, stub):
        assert self._collect("ollama", stub) == "answer from ollama"

    @requires_ollama
    def test_a_keyless_local_daemon_can_stream(self, stub):
        transport = transport_for("ollama", api_key="", base_url=stub)
        try:
            text = "".join(transport.stream(MESSAGES, PARAMS, model="stub-model"))
        finally:
            transport.close()
        assert text == "answer from ollama"

    @requires_openai
    def test_a_stream_failure_is_classified_like_any_other(self, stub):
        _State.mode, _State.status = "error", 401
        _State.body = {"error": {"message": "bad key", "type": "invalid_request_error"}}
        transport = _transport("openai", stub, base=stub + "/v1")
        try:
            with pytest.raises(AuthDeniedError):
                list(transport.stream(MESSAGES, PARAMS, model="stub-model"))
        finally:
            transport.close()

    @requires_openai
    def test_the_runtime_streams_and_still_refuses_without_a_model(self, stub):
        from archx_agent.adapters.sdk_runtime import SdkChatRuntime
        from archx_agent.helpers.exceptions import ProviderError

        runtime = SdkChatRuntime("openai", api_key=KEY, base_url=stub + "/v1")
        try:
            with pytest.raises(ProviderError):
                list(runtime.stream(MESSAGES, PARAMS))
        finally:
            runtime.close()


class TestPaths:
    """What each client appends to the base it is given. Measured, not read from documentation.

    This table is why `scripts/remote_model.sh` gives openai `/v1` and the others the bare origin:
    getting it wrong produces `/v1/v1/chat/completions`, and a lenient stub will happily answer.
    """

    @pytest.mark.parametrize("key, base_suffix, expected", [
        ("openai", "/v1", "/v1/chat/completions"),
        ("groq", "", "/openai/v1/chat/completions"),
        ("together", "", "/v1/chat/completions"),
        ("mistral", "", "/v1/chat/completions"),
        ("anthropic", "", "/v1/messages"),
        ("cohere", "", "/v2/chat"),
        ("ollama", "", "/api/chat"),
    ])
    def test_the_requested_path(self, stub, key, base_suffix, expected):
        if not sdk_available(key)[0]:
            pytest.skip(f"{key} SDK not installed")
        transport = _transport(key, stub, base=stub + base_suffix)
        try:
            transport.chat(MESSAGES, PARAMS, model="stub-model")
        finally:
            transport.close()
        assert _State.seen[-1]["path"] == expected


class TestDefaults:
    """Each default base plus what the client appends must equal the vendor's real URL.

    No network: this is arithmetic over two things that are each individually verifiable - the
    documented endpoint, and the path the client actually requested from a loopback server. It
    catches the class of bug the runner found: a base that only works because a stub was lenient.
    """

    PUBLIC = {
        "openai": "https://api.openai.com/v1/chat/completions",
        "anthropic": "https://api.anthropic.com/v1/messages",
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "together": "https://api.together.xyz/v1/chat/completions",
        "mistral": "https://api.mistral.ai/v1/chat/completions",
        "cohere": "https://api.cohere.com/v2/chat",
        "ollama": "http://127.0.0.1:11434/api/chat",
    }

    @pytest.mark.parametrize("key", sorted(PUBLIC))
    def test_the_default_base_lands_on_the_documented_url(self, key):
        expected = self.PUBLIC[key]
        base = SDKS[key].default_base_url or "http://127.0.0.1:11434"
        path = UPSTREAM_PATH[key]
        assert base.rstrip("/") + path == expected


class TestToolProbe:
    """`models probe --capability tools` had no way to pass: nothing ever offered a tool."""

    @requires_openai
    def test_the_openai_client_returns_its_tool_call(self, stub):
        transport = _transport("openai", stub, base=stub + "/v1")
        try:
            result = transport.chat_with_tools(MESSAGES, PARAMS, model="stub-model")
        finally:
            transport.close()
        calls = result.raw["tool_calls"]
        assert calls[0]["name"] == "record_value"
        assert _State.seen[-1]["body"]["tools"]
        assert _State.seen[-1]["body"]["tool_choice"] == "auto"

    @requires_anthropic
    def test_anthropic_speaks_its_flat_tool_shape(self, stub):
        transport = _transport("anthropic", stub)
        try:
            with pytest.raises(Exception):
                # the stub answers text for /v1/messages, so no tool call means a refusal
                transport.chat_with_tools(MESSAGES, PARAMS, model="stub-model")
        finally:
            transport.close()
        offered = _State.seen[-1]["body"]["tools"][0]
        assert set(offered) == {"name", "description", "input_schema"}

    def test_a_client_without_a_tool_path_refuses_instead_of_guessing(self, stub):
        if not sdk_available("cohere")[0]:
            pytest.skip("cohere SDK not installed")
        transport = _transport("cohere", stub)
        try:
            with pytest.raises(Exception) as caught:
                transport.chat_with_tools(MESSAGES, PARAMS, model="stub-model")
        finally:
            transport.close()
        assert "not implemented" in str(caught.value)

    @requires_openai
    def test_a_model_that_ignores_the_tool_is_not_counted_as_passing(self, stub):
        _State.ignore_tools = True
        transport = _transport("openai", stub, base=stub + "/v1")
        try:
            with pytest.raises(Exception) as caught:
                transport.chat_with_tools(MESSAGES, PARAMS, model="stub-model")
        finally:
            transport.close()
        assert "without calling the tool" in str(caught.value)
