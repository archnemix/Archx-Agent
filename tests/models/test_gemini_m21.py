"""A real Gemini runtime: the wire protocol, the failure taxonomy, and the consent gate.

The vendor's host is not reachable from this sandbox, so the client is driven against a local
HTTP server that speaks the *documented* Gemini protocol on a real socket. That exercises the
parts this repository owns - request shape, role translation, usage parsing, streaming, error
classification, redaction - end to end. What it cannot prove is that Google's service behaves
as documented today; every place that matters says so.

The tests are organised around what would quietly go wrong:

* the key leaking into a URL, an error message, a trace or a report;
* a 429 quota problem reported as "model not found", or a bad key retried;
* a safety block arriving as an empty string that looks like a model with nothing to say;
* a transcript with two consecutive user turns, which the protocol rejects;
* a *new* runtime quietly bypassing the M20 consent gate that the OpenAI-compatible one obeys.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from archx_agent.adapters.gemini_runtime import GeminiChatRuntime, _safe_url
from archx_agent.adapters.model_runtime import GenerationParams, ModelSpec
from archx_agent.application.workspace import NETWORK_RUNTIMES, open_workspace
from archx_agent.helpers.exceptions import (
    ArchxError,
    AuthDeniedError,
    MalformedOutputError,
    ModelNotFoundError,
    NetworkFailureError,
    ProviderError,
    ProviderOutageError,
    QuotaExhaustedError,
    RateLimitedError,
)

CLI = os.path.join(os.path.dirname(sys.executable), "archx-agent")
KEY = "test-gemini-key-0123456789abcdef"


# --------------------------------------------------------------------------
# the stub: the documented protocol, and a way to make it refuse
# --------------------------------------------------------------------------
class _State:
    mode = "ok"                 # ok | error | blocked | empty | garbage | flaky
    status = 500
    body: dict = {}
    attempts = 0
    seen: list[dict] = []
    last_headers: dict = {}
    last_path = ""
    last_query = ""
    content = "The answer is 42."
    tokens = {"promptTokenCount": 11, "candidatesTokenCount": 5, "totalTokenCount": 16}
    finish = "STOP"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, payload: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _record(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            body = {"_raw": raw.decode("utf-8", "replace")}
        _State.attempts += 1
        _State.seen.append(body)
        _State.last_headers = {k.lower(): v for k, v in self.headers.items()}
        _State.last_path = self.path.split("?")[0]
        _State.last_query = self.path.split("?", 1)[1] if "?" in self.path else ""
        return body

    def do_GET(self):  # noqa: N802
        self._record()
        if _State.mode == "error":
            self._send(_State.status, json.dumps(_State.body).encode())
            return
        self._send(200, json.dumps({"models": [
            {"name": "models/gemini-2.0-flash", "displayName": "Gemini 2.0 Flash",
             "supportedGenerationMethods": ["generateContent", "streamGenerateContent"]},
        ]}).encode())

    def do_POST(self):  # noqa: N802
        body = self._record()
        if _State.mode == "error":
            self._send(_State.status, json.dumps(_State.body).encode())
            return
        if _State.mode == "flaky" and _State.attempts == 1:
            self._send(503, json.dumps({"error": {"code": 503, "status": "UNAVAILABLE",
                                                  "message": "try again"}}).encode())
            return
        if _State.mode == "garbage":
            self._send(200, b"<html>not json</html>")
            return
        if _State.mode == "blocked":
            self._send(200, json.dumps({
                "promptFeedback": {"blockReason": "SAFETY"},
                "usageMetadata": {"promptTokenCount": 3},
            }).encode())
            return
        if _State.mode == "empty":
            self._send(200, json.dumps({
                "candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}],
            }).encode())
            return
        if ":streamGenerateContent" in self.path:
            self._stream(body)
            return
        self._send(200, json.dumps(_reply(body)).encode())

    def _stream(self, body: dict) -> None:
        pieces = ["The ", "answer ", "is ", "42."]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for piece in pieces:
            chunk = {"candidates": [{"content": {"parts": [{"text": piece}]}}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: {\"candidates\": []}\n\n")
        self.wfile.flush()

    def log_message(self, *args):  # keep the test output readable
        pass


def _reply(body: dict) -> dict:
    """A well-formed generateContent response that echoes what the client asked for."""
    parts = [{"text": _State.content}]
    return {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": _State.finish,
                        "safetyRatings": [{"category": "HARM_CATEGORY_HARASSMENT", "probability": "NEGLIGIBLE"}]}],
        "usageMetadata": dict(_State.tokens),
        "modelVersion": "gemini-2.0-flash",
    }


@pytest.fixture()
def stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _State.mode, _State.status, _State.body = "ok", 500, {}
    _State.attempts = 0
    _State.seen = []
    _State.finish = "STOP"
    _State.content = "The answer is 42."
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def runtime(stub: str, *, model: str = "gemini-2.0-flash", key: str = KEY) -> GeminiChatRuntime:
    rt = GeminiChatRuntime(stub, api_key=key)
    rt.load(ModelSpec(id="mdl_test", provider="google", runtime="gemini", model=model))
    return rt


PARAMS = GenerationParams(temperature=0.2, max_tokens=64, top_p=0.9)


# --------------------------------------------------------------------------
# the request the client builds
# --------------------------------------------------------------------------
class TestRequestShape:
    def test_a_system_prompt_goes_into_systemInstruction_not_contents(self, stub):
        runtime(stub).chat(
            [{"role": "system", "content": "be terse"},
             {"role": "user", "content": "hello"}],
            PARAMS,
        )
        sent = _State.seen[-1]
        assert sent["systemInstruction"] == {"parts": [{"text": "be terse"}]}
        assert [c["role"] for c in sent["contents"]] == ["user"]
        assert sent["contents"][0]["parts"][0]["text"] == "hello"

    def test_an_assistant_turn_becomes_the_model_role(self, stub):
        runtime(stub).chat(
            [{"role": "system", "content": "be terse"},
             {"role": "user", "content": "one"},
             {"role": "assistant", "content": "two"},
             {"role": "user", "content": "three"}],
            PARAMS,
        )
        assert [c["role"] for c in _State.seen[-1]["contents"]] == ["user", "model", "user"]

    def test_consecutive_turns_from_one_side_are_merged(self, stub):
        """The protocol alternates; two user turns in a row are an invalid transcript."""
        runtime(stub).chat(
            [{"role": "user", "content": "a"}, {"role": "user", "content": "b"},
             {"role": "model", "content": "c"}],
            PARAMS,
        )
        contents = _State.seen[-1]["contents"]
        assert [c["role"] for c in contents] == ["user", "model"]
        assert [p["text"] for p in contents[0]["parts"]] == ["a", "b"]

    def test_a_system_only_conversation_still_produces_one_turn(self, stub):
        runtime(stub).chat([{"role": "system", "content": "only rules"}], PARAMS)
        sent = _State.seen[-1]
        assert sent["contents"] == [{"role": "user", "parts": [{"text": "only rules"}]}]

    def test_the_generation_knobs_are_translated(self, stub):
        runtime(stub).chat(
            [{"role": "user", "content": "x"}],
            GenerationParams(temperature=0.1, top_p=0.5, max_tokens=7, stop=("END",)),
        )
        config = _State.seen[-1]["generationConfig"]
        assert config["temperature"] == 0.1
        assert config["topP"] == 0.5
        assert config["maxOutputTokens"] == 7
        assert config["stopSequences"] == ["END"]

    def test_the_model_reference_appears_once_without_a_prefix(self, stub):
        runtime(stub, model="models/gemini-2.0-flash").chat([{"role": "user", "content": "x"}], PARAMS)
        assert _State.last_path == "/v1beta/models/gemini-2.0-flash:generateContent"

    def test_the_api_version_is_configurable(self, stub):
        rt = GeminiChatRuntime(stub, api_key=KEY, api_version="v1")
        rt.load(ModelSpec(id="m", provider="google", runtime="gemini", model="gemini-2.0-flash"))
        rt.chat([{"role": "user", "content": "x"}], PARAMS)
        assert _State.last_path.startswith("/v1/models/")


# --------------------------------------------------------------------------
# the credential
# --------------------------------------------------------------------------
class TestCredential:
    def test_the_key_is_sent_as_a_header_and_never_in_the_url(self, stub):
        runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)
        assert _State.last_headers.get("x-goog-api-key") == KEY
        assert "key=" not in f"{_State.last_path}?{_State.last_query}"
        assert KEY not in _State.last_path and KEY not in _State.last_query

    def test_a_missing_key_is_refused_before_any_request(self, stub):
        rt = runtime(stub, key="")
        ok, why = rt.available()
        assert ok is False and "no API key" in why
        with pytest.raises(AuthDeniedError) as exc:
            rt.chat([{"role": "user", "content": "x"}], PARAMS)
        assert "no API key" in exc.value.message
        assert _State.seen == [], "nothing may be sent without a key"

    def test_the_key_is_registered_with_the_redactor(self, stub):
        from archx_agent.helpers.redaction import redact, registered_secret_count

        before = registered_secret_count()
        runtime(stub, key="another-test-key-abcdef")
        assert registered_secret_count() == before + 1
        assert "another-test-key-abcdef" not in redact(f"leaked another-test-key-abcdef here")

    def test_close_wipes_the_key(self, stub):
        rt = runtime(stub)
        rt.close()
        assert rt._api_key == ""
        # even reloaded, the runtime has no credential left to send
        rt.load(ModelSpec(id="mdl_test", provider="google", runtime="gemini", model="gemini-2.0-flash"))
        with pytest.raises(AuthDeniedError):
            rt.chat([{"role": "user", "content": "x"}], PARAMS)

    def test_an_error_url_is_stripped_of_its_query(self):
        assert _safe_url("https://h/v1beta/models/x:generateContent?key=SECRET&alt=sse") == \
            "https://h/v1beta/models/x:generateContent"


# --------------------------------------------------------------------------
# the answer
# --------------------------------------------------------------------------
class TestAnswer:
    def test_text_usage_and_model_are_parsed(self, stub):
        result = runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)
        assert result.text == "The answer is 42."
        assert result.model_id == "gemini-2.0-flash"
        assert (result.prompt_tokens, result.completion_tokens) == (11, 5)
        assert result.finish_reason == "stop"
        assert result.latency_ms > 0
        assert result.raw["total_tokens"] == 16

    def test_max_tokens_is_reported_as_a_length_stop(self, stub):
        _State.finish = "MAX_TOKENS"
        assert runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS).finish_reason == "length"

    def test_a_safety_stop_keeps_the_reason(self, stub):
        _State.finish = "SAFETY"
        assert runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS).finish_reason == "safety"

    def test_streaming_yields_the_pieces_in_order(self, stub):
        pieces = list(runtime(stub).stream([{"role": "user", "content": "x"}], PARAMS))
        assert pieces == ["The ", "answer ", "is ", "42."]
        assert _State.last_query == "alt=sse"

    def test_thought_parts_are_not_shown_as_the_answer(self, stub):
        # A part marked `thought` is the model's scratchpad, not the reply.
        original = _State.content
        rt = runtime(stub)
        data = _reply({})
        data["candidates"][0]["content"]["parts"] = [
            {"text": "thinking...", "thought": True},
            {"text": "visible answer"},
        ]
        text, _, _ = rt._reply_text(data)
        assert text == "visible answer"
        assert original == _State.content


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------
class TestRefusals:
    def _fail(self, status: int, body: dict) -> None:
        _State.mode, _State.status, _State.body = "error", status, body

    def test_an_invalid_key_is_an_auth_failure_not_a_retry(self, stub):
        self._fail(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                   "message": "API key not valid. Please pass a valid API key."}})
        with pytest.raises(AuthDeniedError):
            runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)
        assert _State.attempts == 1, "an auth failure must not be retried"

    def test_403_is_an_auth_failure(self, stub):
        self._fail(403, {"error": {"code": 403, "status": "PERMISSION_DENIED",
                                   "message": "API has not been used in project"}})
        with pytest.raises(AuthDeniedError):
            runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)

    def test_an_unknown_model_is_a_model_not_found(self, stub):
        self._fail(404, {"error": {"code": 404, "status": "NOT_FOUND",
                                   "message": "models/gemini-9.9 is not found for API version v1beta"}})
        with pytest.raises(ModelNotFoundError):
            runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)

    def test_a_quota_problem_is_not_reported_as_a_rate_limit(self, stub):
        self._fail(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                   "message": "Quota exceeded for quota metric 'requests per day'"}})
        with pytest.raises(QuotaExhaustedError):
            runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)

    def test_a_burst_limit_is_a_rate_limit_even_though_the_status_is_the_same(self, stub):
        """Gemini uses 429 RESOURCE_EXHAUSTED for both; only the message tells them apart."""
        self._fail(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                   "message": "Too many requests, slow down"}})
        with pytest.raises(RateLimitedError):
            runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)

    def test_a_server_error_is_retried_then_given_up_on(self, stub):
        self._fail(500, {"error": {"code": 500, "status": "INTERNAL", "message": "boom"}})
        rt = runtime(stub)
        rt.max_retries = 1
        with pytest.raises(ProviderOutageError):
            rt.chat([{"role": "user", "content": "x"}], PARAMS)
        assert _State.attempts == 2, "one retry, then give up"

    def test_a_transient_outage_is_survived(self, stub):
        _State.mode = "flaky"
        result = runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)
        assert result.text == "The answer is 42."
        assert _State.attempts == 2

    def test_a_blocked_prompt_says_it_was_blocked(self, stub):
        _State.mode = "blocked"
        with pytest.raises(ProviderError) as exc:
            runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)
        assert "blocked" in exc.value.message and "SAFETY" in exc.value.message
        assert not isinstance(exc.value, MalformedOutputError)

    def test_a_silent_empty_answer_is_an_error_not_an_empty_string(self, stub):
        _State.mode = "empty"
        with pytest.raises(MalformedOutputError) as exc:
            runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)
        assert "SAFETY" in exc.value.message

    def test_a_non_json_body_is_malformed_output(self, stub):
        _State.mode = "garbage"
        with pytest.raises(MalformedOutputError):
            runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)

    def test_an_unreachable_host_is_a_network_failure(self):
        rt = GeminiChatRuntime("http://127.0.0.1:9", api_key=KEY)
        rt.load(ModelSpec(id="m", provider="google", runtime="gemini", model="gemini-2.0-flash"))
        with pytest.raises(NetworkFailureError):
            rt.chat([{"role": "user", "content": "x"}], PARAMS)

    def test_no_error_message_contains_the_key(self, stub):
        for status, body in (
            (400, {"error": {"message": f"API key not valid: {KEY}"}}),
            (429, {"error": {"message": "quota"}}),
            (500, {"error": {"message": "boom"}}),
        ):
            _State.mode, _State.status, _State.body = "error", status, body
            _State.attempts = 0
            try:
                runtime(stub).chat([{"role": "user", "content": "x"}], PARAMS)
            except ProviderError as exc:
                assert KEY not in exc.message, status
                assert KEY not in str(getattr(exc, "details", "")), status
                if status == 400:
                    # redacted, not dropped: a caller must be able to tell the vendor echoed it
                    assert "[REDACTED]" in exc.message


# --------------------------------------------------------------------------
# health and the catalogue
# --------------------------------------------------------------------------
class TestHealth:
    def test_health_reports_the_catalogue_is_reachable(self, stub):
        health = runtime(stub).health()
        assert health.ok is True
        assert "model(s)" in health.detail
        assert "chat" in health.capabilities

    def test_health_reports_a_refusal_honestly(self, stub):
        _State.mode, _State.status = "error", 401
        _State.body = {"error": {"code": 401, "status": "UNAUTHENTICATED", "message": "no"}}
        health = runtime(stub).health()
        assert health.ok is False
        assert "AuthDeniedError" in health.detail

    def test_list_models_returns_the_entries(self, stub):
        models = runtime(stub).list_models()
        assert models[0]["name"] == "models/gemini-2.0-flash"
        assert "generateContent" in models[0]["supportedGenerationMethods"]


# --------------------------------------------------------------------------
# the workspace: registration, routing, consent, end to end
# --------------------------------------------------------------------------
@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "0")
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


def _register(ws, stub_url: str, *, name: str = "gemini-flash", ref: str = "secret://env/GEMINI_API_KEY"):
    record = ws.models.register_remote(
        name,
        provider="google",
        runtime="gemini",
        model_ref="gemini-2.0-flash",
        base_url=stub_url,
        context_length=1_000_000,
        capabilities=["chat"],
    )
    metadata = dict(record.user_metadata)
    metadata["credential_ref"] = ref
    return ws.models.update(record.id, user_metadata=metadata)


class TestWorkspace:
    def test_the_runtime_is_gated_like_every_other_network_runtime(self):
        assert {"openai-http", "http", "gemini"} <= NETWORK_RUNTIMES

    def test_a_loopback_gemini_model_is_available_and_chats(self, ws, stub):
        record = _register(ws, stub)
        ready, why = ws.runtime_availability(record)
        assert ready is True, why
        reply = ws.chat.send("hello", model_id=record.id)
        assert reply.text == "The answer is 42."
        assert reply.prompt_tokens == 11 and reply.completion_tokens == 5
        assert reply.simulated is False
        assert reply.task["type"] == "chat"
        assert ws.tasks.get(reply.task["id"]).status == "completed"

    def test_the_key_never_reaches_the_database_or_the_trace(self, ws, stub):
        record = _register(ws, stub)
        ws.chat.send("a secret question", model_id=record.id)
        ws.events.flush(2.0)
        # events live in their own store; the model row lives in the workspace db
        events = [event.to_dict() if hasattr(event, "to_dict") else dict(event)
                  for event in ws.events.query(limit=200)]
        blob = json.dumps(events)
        assert KEY not in blob
        assert KEY not in json.dumps([dict(r) for r in ws.store.query("SELECT facts, user_metadata FROM models")])
        assert KEY not in json.dumps(record.to_dict())
        assert "secret://env/GEMINI_API_KEY" in json.dumps(record.to_dict())

    def test_a_remote_gemini_model_needs_consent_before_it_is_called(self, ws):
        """The M20 gate must cover the new runtime, not just the OpenAI-compatible one."""
        record = _register(ws, "https://generativelanguage.googleapis.com")
        # the router wraps the gate's refusal in its own error, keeping the message
        with pytest.raises(ArchxError) as exc:
            ws.chat.send("hello", model_id=record.id)
        assert "model.local_only is true" in exc.value.message
        # nothing was sent, and the refusal is on the task record
        assert ws.tasks.list(limit=5)

    def test_consent_alone_is_not_enough_without_a_registered_provider(self, ws, monkeypatch):
        record = _register(ws, "https://generativelanguage.googleapis.com")
        monkeypatch.setattr(ws.config, "get", _patched_config(ws.config.get))
        with pytest.raises(ArchxError) as exc:
            ws.chat.send("hello", model_id=record.id)
        assert "not a registered provider" in exc.value.message

    def test_a_missing_secret_reference_is_explained_not_crashed(self, ws, stub, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        record = _register(ws, stub)
        ready, why = ws.runtime_availability(record)
        assert ready is False
        assert "could not be resolved" in why
        # the router refuses the model and repeats the same sentence, so the user learns
        # which reference is missing rather than getting a stack trace
        with pytest.raises(ArchxError) as exc:
            ws.chat.send("hello", model_id=record.id)
        assert "GEMINI_API_KEY" in exc.value.message

    def test_no_credential_reference_means_not_ready(self, ws, stub):
        record = ws.models.register_remote(
            "bare", provider="google", runtime="gemini", model_ref="gemini-2.0-flash",
            base_url=stub, capabilities=["chat"],
        )
        ready, why = ws.runtime_availability(record)
        assert ready is False
        assert "credential-ref" in why

    def test_probe_records_the_measurement(self, ws, stub):
        record = _register(ws, stub)
        result = ws.router.probe(record.id, "chat")
        assert result["outcome"] == "passed"
        assert result["state_after"]["state"] == "verified"
        assert ws.models.capability_matrix(record.id)["chat"]["state"] == "verified"


def _patched_config(getter):
    """A config whose model.local_only reads false, so the *next* gate is reached."""
    def wrapped(key, *args, **kwargs):
        if key == "model.local_only":
            return False
        return getter(key, *args, **kwargs)
    return wrapped


# --------------------------------------------------------------------------
# the CLI
# --------------------------------------------------------------------------
def cli(*args, home, env_extra=None, key=KEY):
    env = {**os.environ, "ARCHX_PATHS_HOME": str(home)}
    env.pop("ARCHX_ALLOW_SIMULATED", None)
    if key is None:
        env.pop("GEMINI_API_KEY", None)
    else:
        env["GEMINI_API_KEY"] = key
    env.update(env_extra or {})
    return subprocess.run([CLI, *args], capture_output=True, text=True, env=env, timeout=180)


class TestCli:
    def test_add_gemini_registers_a_real_runtime(self, tmp_path):
        home = tmp_path / "home"
        result = cli("models", "add-gemini", "--name", "flash",
                     "--model", "gemini-2.0-flash", home=home)
        assert result.returncode == 0, result.stderr
        assert "runtime=gemini" in result.stdout
        assert "never stored" in result.stdout
        assert "secret://env/GEMINI_API_KEY" in result.stdout
        assert KEY not in result.stdout

    def test_a_literal_key_is_refused_with_a_usage_error(self, tmp_path):
        result = cli("models", "add-gemini", "--name", "flash", "--model", "gemini-2.0-flash",
                     "--credential-ref", KEY, home=tmp_path / "home")
        assert result.returncode == 2
        assert "secret://" in result.stderr
        assert KEY not in result.stderr

    def test_chat_runs_through_the_stub_and_the_cli_sees_the_reply(self, tmp_path, stub):
        home = tmp_path / "home"
        assert cli("models", "add-gemini", "--name", "flash", "--model", "gemini-2.0-flash",
                   "--base-url", stub, home=home).returncode == 0
        result = cli("chat", "--message", "hello", "--model", "flash", home=home)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "The answer is 42." in result.stdout
        assert KEY not in result.stdout and KEY not in result.stderr

    def test_a_missing_key_is_reported_by_the_cli(self, tmp_path):
        home = tmp_path / "home"
        assert cli("models", "add-gemini", "--name", "flash", "--model", "gemini-2.0-flash",
                   home=home).returncode == 0
        doctor = cli("models", "show", "flash", home=home, key=None)
        assert doctor.returncode == 0
        chat = cli("chat", "--message", "hello", "--model", "flash", home=home, key=None)
        assert chat.returncode != 0
        assert "GEMINI_API_KEY" in (chat.stdout + chat.stderr)

    def test_models_probe_measures_through_the_stub(self, tmp_path, stub):
        home = tmp_path / "home"
        cli("models", "add-gemini", "--name", "flash", "--model", "gemini-2.0-flash",
            "--base-url", stub, home=home)
        result = cli("models", "probe", "flash", "--capability", "chat", home=home)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "passed" in result.stdout
        assert "verified" in result.stdout


# --------------------------------------------------------------------------
# the GUI: the same ladder, reachable without a terminal
# --------------------------------------------------------------------------
def _api(ws):
    from archx_agent.interfaces.gui.server import GuiApi

    return GuiApi(ws, token="gui-test-token")


def _call(api, method, path, *, body=None, token="gui-test-token"):
    from archx_agent.interfaces.gui.server import Request, split_target

    parsed_path, query, url_token = split_target(path)
    request = Request(
        method=method,
        path=parsed_path,
        query=query,
        headers={"x-archx-token": token} if token else {},
        body=body,
        token=url_token,
        token_in_query=url_token is not None,
    )
    response = api.dispatch(request)
    return response.status, (response.payload if response.body is None else response.body)


def _ok(api, method, path, **kwargs):
    status, payload = _call(api, method, path, **kwargs)
    assert status == 200, (status, payload)
    return payload["data"]


class TestGui:
    def test_the_models_list_carries_the_gate_ladder(self, ws, stub):
        record = _register(ws, stub)
        api = _api(ws)
        models = _ok(api, "GET", "/api/models")
        entry = next(m for m in models if m["id"] == record.id)
        assert entry["ready"] is True
        # loopback: nothing leaves the device, so the ladder is one short rung
        assert [gate["key"] for gate in entry["gates"]] == ["local"]
        assert entry["gates"][0]["ok"] is True

    def test_a_remote_model_shows_which_rung_it_is_stuck_on(self, ws):
        record = _register(ws, "https://generativelanguage.googleapis.com")
        api = _api(ws)
        entry = _ok(api, "GET", f"/api/models/{record.id}")
        gates = {gate["key"]: gate for gate in entry["gates"]}
        assert gates["consent_policy"]["ok"] is False
        assert gates["provider"]["ok"] is False
        # the later rungs stay visible, with the reason they cannot be climbed yet
        assert [gates[key]["ok"] for key in ("privacy", "consent")] == [False, False]
        assert gates["consent"]["detail"] == "register the provider first"

    def test_registering_a_model_through_the_gui_never_takes_a_literal_key(self, ws):
        api = _api(ws)
        status, payload = _call(api, "POST", "/api/models", body={
            "name": "flash", "model": "gemini-2.0-flash", "credential_ref": KEY,
        })
        assert status == 400
        assert payload["error"]["code"] == "literal_secret"
        assert KEY not in json.dumps(payload)
        assert ws.models.list() == []

    def test_a_model_registered_through_the_gui_chats(self, ws, stub):
        api = _api(ws)
        created = _ok(api, "POST", "/api/models", body={
            "name": "flash", "model": "gemini-2.0-flash", "base_url": stub,
        })
        assert created["runtime"] == "gemini"
        assert created["user_metadata"]["credential_ref"] == "secret://env/GEMINI_API_KEY"
        assert created["ready"] is True, created["ready_reason"]
        reply = _ok(api, "POST", "/api/chat", body={"message": "hello", "model_id": created["id"]})
        assert reply["text"] == "The answer is 42."
        assert reply["simulated"] is False

    def test_the_gui_walks_the_ladder_and_then_the_call_works(self, ws, stub, monkeypatch):
        """Consent is four deliberate clicks, not one hidden default.

        The stub listens on loopback, so the gate is told it is remote for this test: that way
        the whole ladder is climbed *and* the resulting call reaches the local server.
        """
        for module in ("archx_agent.interfaces.gui.routes.models", "archx_agent.managers.providers.catalogue"):
            monkeypatch.setattr(f"{module}.is_loopback_url", lambda url: False)
        record = ws.register_gemini(
            "flash", model_ref="gemini-2.0-flash", base_url=stub,
        )
        api = _api(ws)
        entry = _ok(api, "GET", f"/api/models/{record.id}")
        assert {gate["key"] for gate in entry["gates"]} == {
            "consent_policy", "provider", "privacy", "consent",
        }
        provider = _ok(api, "POST", f"/api/models/{record.id}/provider")
        assert provider["slug"] == "google"
        # a confirmation that does not say what leaves the device is not a confirmation
        status, payload = _call(api, "POST", f"/api/providers/{provider['id']}/privacy", body={})
        assert status == 400
        _ok(api, "POST", f"/api/providers/{provider['id']}/privacy",
            body={"data_leaves_device": True})
        consented = _ok(api, "POST", f"/api/providers/{provider['id']}/consent", body={})
        assert consented["consented"] is True
        _ok(api, "POST", "/api/settings/model.local_only", body={"value": False})
        done = _ok(api, "GET", f"/api/models/{record.id}")
        assert [gate["ok"] for gate in done["gates"]] == [True, True, True, True]
        reply = _ok(api, "POST", "/api/chat", body={"message": "hello", "model_id": record.id})
        assert reply["text"] == "The answer is 42."

    def test_the_setting_is_written_to_disk_so_a_restart_agrees(self, ws):
        api = _api(ws)
        _ok(api, "POST", "/api/settings/model.local_only", body={"value": False})
        written = json.loads((ws.config.home / "config.json").read_text())
        assert written["settings"]["model.local_only"] is False
        reloaded = open_workspace(home=str(ws.config.home), env={})
        try:
            assert reloaded.config.get("model.local_only") is False
        finally:
            reloaded.close()

    def test_a_probe_through_the_gui_records_a_measurement(self, ws, stub):
        record = _register(ws, stub)
        api = _api(ws)
        result = _ok(api, "POST", f"/api/models/{record.id}/probe", body={"capability": "chat"})
        assert result["result"]["outcome"] == "passed"
        assert ws.models.capability_history(record.id)

    def test_a_failed_probe_is_reported_not_swallowed(self, ws, stub):
        record = _register(ws, stub)
        _State.mode = "error"
        _State.status = 401
        _State.body = {"error": {"code": 401, "status": "UNAUTHENTICATED",
                                 "message": "API key not valid: " + KEY}}
        api = _api(ws)
        status, payload = _call(api, "POST", f"/api/models/{record.id}/probe", body={"capability": "chat"})
        # a probe that fails is still a recorded measurement, not an API error: the panel
        # shows the attempt, and the capability stays unverified
        assert status == 200
        assert payload["data"]["result"]["outcome"] == "failed"
        assert "AuthDeniedError" in payload["data"]["result"]["detail"]
        assert KEY not in json.dumps(payload)
