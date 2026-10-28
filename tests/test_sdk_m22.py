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


# --------------------------------------------------------------------------
# one server, three protocols
# --------------------------------------------------------------------------
class _State:
    mode = "ok"            # ok | error
    status = 500
    body: dict = {}
    attempts = 0
    empty_reply = False
    seen: list[dict] = []

    @classmethod
    def reset(cls) -> None:
        cls.mode, cls.status, cls.body = "ok", 500, {}
        cls.attempts = 0
        cls.empty_reply = False
        cls.seen = []


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


def _transport(key: str, url: str, *, base: str | None = None):
    return transport_for(key, api_key=KEY, base_url=(base if base is not None else url))


# --------------------------------------------------------------------------
# the catalogue of clients
# --------------------------------------------------------------------------
class TestCatalogue:
    def test_every_sdk_knows_its_package_and_its_own_environment_variable(self):
        assert set(SDKS) == {"openai", "anthropic", "google", "mistral"}
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
            "archx_agent.application.workspace.sdk_available",
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
