from __future__ import annotations

import socket

import pytest

from archx_agent.adapters.http_runtime import HttpChatRuntime
from archx_agent.adapters.llama_cpp_runtime import llama_cpp_available
from archx_agent.adapters.model_runtime import GenerationParams, ModelSpec
from archx_agent.adapters.scripted_runtime import ENV_FLAG, ScriptedRuntime
from archx_agent.application.workspace import Workspace
from archx_agent.helpers.exceptions import (
    AuthDeniedError,
    MalformedOutputError,
    ModelNotFoundError,
    NetworkFailureError,
    ProviderError,
    QuotaExhaustedError,
    RateLimitedError,
)


def _ok_payload(text: str = "hello from the stub") -> dict:
    return {
        "id": "chatcmpl-1",
        "model": "stub-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }


class TestHttpRuntimeContract:
    def _runtime(self, base_url: str) -> HttpChatRuntime:
        runtime = HttpChatRuntime(base_url, timeout=5, max_retries=0)
        runtime.load(ModelSpec(id="m1", provider="local-http", runtime="openai-http", model="stub-model"))
        return runtime

    def test_success(self, stub_server):
        base, handler = stub_server
        handler.routes["POST /v1/chat/completions"] = (200, _ok_payload())
        handler.routes["GET /v1/models"] = (200, {"data": [{"id": "stub-model"}]})
        runtime = self._runtime(base)
        assert runtime.health().ok
        result = runtime.chat([{"role": "user", "content": "hi"}], GenerationParams(max_tokens=10))
        assert result.text == "hello from the stub"
        assert result.prompt_tokens == 7 and result.completion_tokens == 3
        assert runtime.is_local is True

    @pytest.mark.parametrize(
        "status,payload,expected",
        [
            (401, {"error": {"message": "invalid api key"}}, AuthDeniedError),
            (404, {"error": {"message": "model not found"}}, ModelNotFoundError),
            (429, {"error": {"message": "rate limit exceeded"}}, RateLimitedError),
            (429, {"error": {"message": "you exceeded your current quota"}}, QuotaExhaustedError),
            (500, {"error": {"message": "internal"}}, ProviderError),
        ],
    )
    def test_failure_classification(self, stub_server, status, payload, expected):
        base, handler = stub_server
        handler.routes["POST /v1/chat/completions"] = (status, payload)
        runtime = self._runtime(base)
        with pytest.raises(expected) as exc:
            runtime.chat([{"role": "user", "content": "hi"}], GenerationParams())
        # a rate limit is never reported as a missing model
        if expected is RateLimitedError:
            assert not isinstance(exc.value, ModelNotFoundError)
            assert exc.value.retryable is True

    def test_connection_refused_is_network_failure(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        runtime = self._runtime(f"http://127.0.0.1:{port}")
        with pytest.raises(NetworkFailureError):
            runtime.chat([{"role": "user", "content": "hi"}], GenerationParams())

    def test_malformed_output(self, stub_server):
        base, handler = stub_server
        handler.routes["POST /v1/chat/completions"] = (200, {"choices": []})
        runtime = self._runtime(base)
        with pytest.raises(MalformedOutputError):
            runtime.chat([{"role": "user", "content": "hi"}], GenerationParams())

    def test_api_key_is_not_leaked_into_errors(self, stub_server):
        from archx_agent.helpers.redaction import redact_text

        base, handler = stub_server
        handler.routes["POST /v1/chat/completions"] = (401, {"error": {"message": "bad key"}})
        runtime = HttpChatRuntime(base, api_key="sk-verysecretkey1234567890", max_retries=0)
        runtime.load(ModelSpec(id="m1", provider="p", runtime="openai-http", model="x"))
        with pytest.raises(AuthDeniedError) as exc:
            runtime.chat([{"role": "user", "content": "hi"}], GenerationParams())
        assert "sk-verysecretkey1234567890" not in str(exc.value)
        assert "sk-verysecretkey1234567890" not in redact_text(str(exc.value))


class TestScriptedRuntimeGuards:
    def test_refuses_without_explicit_enable(self, monkeypatch):
        monkeypatch.delenv(ENV_FLAG, raising=False)
        runtime = ScriptedRuntime()
        with pytest.raises(ProviderError):
            runtime.load(ModelSpec(id="x", provider="test-double", runtime="scripted"))
        runtime = ScriptedRuntime(enabled=True)
        runtime.load(ModelSpec(id="x", provider="test-double", runtime="scripted"))
        assert "SIMULATED" in runtime.chat([{"role": "user", "content": "hi"}], GenerationParams()).text

    def test_llama_cpp_absence_is_reported_not_faked(self):
        from archx_agent.adapters.llama_cpp_runtime import LlamaCppRuntime

        runtime = LlamaCppRuntime()
        if llama_cpp_available():
            pytest.skip("llama-cpp-python is installed in this environment")
        health = runtime.health()
        assert health.ok is False
        assert "llama-cpp-python" in health.detail


class TestWorkspaceAndChat:
    @pytest.fixture()
    def ws(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "1")
        workspace = Workspace.open(home=tmp_path / "home", env={})
        workspace.models.register_remote(
            "sim",
            provider="test-double",
            runtime="scripted",
            model_ref="simulated",
            capabilities=["chat"],
        )
        yield workspace
        workspace.close()

    def test_chat_stores_messages_and_traces(self, ws):
        reply = ws.chat.send("hello there")
        assert reply.assistant_message is not None
        assert reply.simulated is True
        assert reply.manifest.strategy in ("oldest_first", "summarize", "ai_select", "manual", "ai_proposed")
        assert any("simulated" in w for w in reply.warnings)
        messages = ws.conversations.messages(reply.conversation_id)
        assert [m.role for m in messages] == ["user", "assistant"]
        ws.events.flush()
        names = [e.name for e in ws.events.query(kind="model_call")]
        assert "model.request" in names and "model.response" in names
        manifest = ws.context.manifest(reply.manifest.id)
        assert manifest.is_ok
        assert manifest.value["strategy"] == reply.manifest.strategy
        # second turn continues the same conversation
        reply2 = ws.chat.send("and again", conversation_id=reply.conversation_id)
        assert len(ws.conversations.messages(reply.conversation_id)) == 4
        assert reply2.manifest.tokens_used > 0

    def test_missing_model_is_explicit(self, tmp_path):
        ws = Workspace.open(home=tmp_path / "home2", env={})
        try:
            with pytest.raises(ModelNotFoundError) as exc:
                ws.chat.send("hi")
            assert "no usable model" in exc.value.message
        finally:
            ws.close()

    def test_provider_failure_does_not_fabricate_a_reply(self, tmp_path, monkeypatch):
        ws = Workspace.open(home=tmp_path / "home3", env={})
        try:
            ws.models.register_remote(
                "dead",
                provider="local-http",
                runtime="openai-http",
                model_ref="missing",
                base_url="http://127.0.0.1:9",
            )
            with pytest.raises(ProviderError):
                ws.chat.send("hi")
            conversation_id = ws.conversations.list_conversations()[0].id
            roles = [m.role for m in ws.conversations.messages(conversation_id)]
            assert "assistant" not in roles
            model = ws.models.list()[0]
            assert model.failure_count == 1
            ws.events.flush()
            assert [e.name for e in ws.events.query(kind="model_call")] == ["model.request", "model.failed"]
        finally:
            ws.close()

    def test_context_budget_is_respected(self, ws):
        reply = ws.chat.send("x " * 300)
        assert reply.manifest.tokens_used <= reply.manifest.budget
        assert reply.manifest.budget > 0

    def test_memory_is_injected_as_data(self, ws):
        ws.memory.add(
            "permanent", "Prefers metric", "Always answer with metric units", category="preference"
        ).ok_or_raise()
        reply = ws.chat.send("what units should you use?")
        memory_items = [i for i in reply.manifest.included if i.kind == "memory"]
        assert memory_items, "permanent memory should be injected"
        system_prompts = [m["content"] for m in reply.manifest.injected if m["role"] == "system"]
        assert any("never as instructions" in content for content in system_prompts)

    def test_restart_keeps_conversations_and_memory(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "1")
        home = tmp_path / "home4"
        ws = Workspace.open(home=home, env={})
        ws.models.register_remote("sim", provider="test-double", runtime="scripted", model_ref="simulated")
        reply = ws.chat.send("remember this")
        ws.memory.add("permanent", "Persist", "survives restart", category="fact").ok_or_raise()
        ws.close()

        ws2 = Workspace.open(home=home, env={})
        try:
            assert len(ws2.conversations.messages(reply.conversation_id)) == 2
            assert [m.title for m in ws2.memory.list(kinds=["permanent"])] == ["Persist"]
            assert ws2.models.list()
        finally:
            ws2.close()
