"""Malformed providers and native lifecycle failures must fail as domain errors."""

from __future__ import annotations

import io
import json
import sys
import types
import urllib.error

import pytest

from archx_agent.adapters.http_runtime import HttpChatRuntime
from archx_agent.adapters.llama_cpp_runtime import LlamaCppRuntime
from archx_agent.adapters.model_runtime import GenerationParams, ModelSpec
from archx_agent.helpers.exceptions import (
    AuthDeniedError,
    MalformedOutputError,
    ModelNotFoundError,
    NetworkFailureError,
    QuotaExhaustedError,
    ResourceExhaustedError,
)


def http():
    runtime = HttpChatRuntime("http://127.0.0.2:9999", max_retries=2)
    runtime.load(ModelSpec("model", "test", "http", model="model"))
    return runtime


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"choices": "bad"},
        {"choices": [None]},
        {"choices": [{"message": []}]},
        {"choices": [{"message": {"content": 7}}]},
        {"choices": [{"message": {"content": "ok"}}], "usage": []},
        {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": "nan"},
        },
        {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"completion_tokens": -1},
        },
        {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"completion_tokens": True},
        },
    ],
)
def test_chat_rejects_malformed_payload(monkeypatch, payload):
    runtime = http()
    monkeypatch.setattr(runtime, "_request", lambda *args: payload)
    with pytest.raises(MalformedOutputError):
        runtime.chat([], GenerationParams())


@pytest.mark.parametrize(
    "calls",
    [
        None,
        {},
        [None],
        [{"function": None}],
        [{"function": {"name": "f", "arguments": {}}}],
        [{"function": {"name": "", "arguments": "{}"}}],
    ],
)
def test_tool_probe_rejects_bad_calls(monkeypatch, calls):
    runtime = http()
    monkeypatch.setattr(
        runtime,
        "_request",
        lambda *args: {"choices": [{"message": {"tool_calls": calls}}]},
    )
    with pytest.raises(MalformedOutputError):
        runtime.chat_with_tools([], GenerationParams(), tools=[{"type": "function"}])


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (429, "insufficient_quota", QuotaExhaustedError),
        (429, "billing_limit", QuotaExhaustedError),
        (401, "insufficient_quota", AuthDeniedError),
    ],
)
def test_quota_and_auth_are_not_retried(monkeypatch, status, code, expected):
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError(
            "http://test",
            status,
            "failed",
            {},
            io.BytesIO(
                json.dumps(
                    {"error": {"message": "request failed", "code": code}}
                ).encode()
            ),
        )

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(expected):
        http().chat([], GenerationParams())
    assert len(calls) == 1


@pytest.mark.parametrize("raw", [b"[]", b"null", b'"text"', b"\xff"])
def test_request_rejects_non_object_json(monkeypatch, raw):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: io.BytesIO(raw))
    with pytest.raises(MalformedOutputError):
        http()._request("GET", "/models")


@pytest.mark.parametrize(
    "event",
    [
        b"not json",
        b"[]",
        b'{"choices":7}',
        b'{"choices":[null]}',
        b'{"choices":[{"delta":[]}]}',
        b'{"choices":[{"delta":{"content":7}}]}',
        b"\xff",
    ],
)
def test_stream_rejects_malformed_events(monkeypatch, event):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **kw: io.BytesIO(b"data: " + event + b"\n")
    )
    with pytest.raises(MalformedOutputError):
        list(http().stream([], GenerationParams()))


def test_stream_interruption_never_replays_partial_text(monkeypatch):
    attempts = []

    class Interrupted(io.BytesIO):
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n'
            raise TimeoutError("interrupted")

    def open_stream(request, **kwargs):
        attempts.append(json.loads(request.data))
        return Interrupted()

    monkeypatch.setattr("urllib.request.urlopen", open_stream)
    stream = http().stream([], GenerationParams(top_p=0.4, stop=("END",), seed=17))
    assert next(stream) == "first"
    with pytest.raises(NetworkFailureError):
        next(stream)
    assert len(attempts) == 1
    assert attempts[0]["top_p"] == 0.4
    assert attempts[0]["stop"] == ["END"]
    assert attempts[0]["seed"] == 17


def test_health_reports_unsupported_endpoint(monkeypatch):
    runtime = http()

    def fail(*args):
        raise runtime._classify_http(405, {}, "http://test")

    monkeypatch.setattr(runtime, "_request", fail)
    assert not runtime.health().ok
    assert runtime.is_local


def native(monkeypatch, tmp_path):
    class FakeLlama:
        closed = False

        def __init__(self, **kwargs):
            pass

        def close(self):
            self.closed = True

        def create_chat_completion(self, **kwargs):
            return {"choices": [{"message": {"content": "hello"}}]}

    monkeypatch.setitem(
        sys.modules, "llama_cpp", types.SimpleNamespace(Llama=FakeLlama)
    )
    path = tmp_path / "model.gguf"
    path.write_bytes(b"x" * 2048)
    runtime = LlamaCppRuntime()
    runtime.load(ModelSpec("native", "local", "llama-cpp", path=str(path)))
    return runtime, FakeLlama


@pytest.mark.parametrize("failure", ["missing", "directory", "tiny", "memory"])
def test_failed_native_reload_clears_old_model(monkeypatch, tmp_path, failure):
    runtime, fake = native(monkeypatch, tmp_path)
    old = runtime._model
    path = tmp_path / failure
    if failure == "directory":
        path.mkdir()
    if failure == "tiny":
        path.write_bytes(b"small")
    if failure == "memory":
        path.write_bytes(b"x" * 2048)

        def oom(**kwargs):
            raise MemoryError("oom")

        monkeypatch.setattr(sys.modules["llama_cpp"], "Llama", oom)
    with pytest.raises(
        ResourceExhaustedError if failure == "memory" else ModelNotFoundError
    ):
        runtime.load(ModelSpec("bad", "local", "llama-cpp", path=str(path)))
    assert old.closed
    assert runtime._model is None and runtime.spec is None
    assert not runtime.health().ok


def test_native_stream_maps_memory_and_malformed_output(monkeypatch, tmp_path):
    runtime, fake = native(monkeypatch, tmp_path)
    monkeypatch.setattr(
        fake, "create_chat_completion", lambda *a, **kw: iter([{"choices": 9}])
    )
    with pytest.raises(MalformedOutputError):
        list(runtime.stream([], GenerationParams()))

    def oom(*args, **kwargs):
        raise MemoryError("oom")

    monkeypatch.setattr(fake, "create_chat_completion", oom)
    with pytest.raises(ResourceExhaustedError):
        list(runtime.stream([], GenerationParams()))


def test_native_stat_failure_maps_domain_error_and_clears_old_state(
    monkeypatch, tmp_path
):
    from pathlib import Path
    from archx_agent.helpers.exceptions import LocalRuntimeFailureError

    runtime, _ = native(monkeypatch, tmp_path)
    old = runtime._model
    target = tmp_path / "protected.gguf"
    original = Path.stat

    def denied(path, *args, **kwargs):
        if path == target:
            raise PermissionError(13, "denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    with pytest.raises(LocalRuntimeFailureError, match="cannot inspect"):
        runtime.load(ModelSpec("denied", "local", "llama-cpp", path=str(target)))
    assert old.closed and runtime.spec is None and runtime._model is None
    assert not runtime.health().ok


@pytest.mark.parametrize("operation", ["unload", "close", "reload"])
def test_native_close_failure_is_explicit_and_never_leaves_loaded_state(
    monkeypatch, tmp_path, operation
):
    from archx_agent.helpers.exceptions import LocalRuntimeFailureError

    runtime, fake = native(monkeypatch, tmp_path)

    def fail(self):
        raise RuntimeError("native close failed")

    monkeypatch.setattr(fake, "close", fail)
    with pytest.raises(LocalRuntimeFailureError, match="failed to release"):
        if operation == "reload":
            runtime.load(
                ModelSpec(
                    "replacement",
                    "local",
                    "llama-cpp",
                    path=str(tmp_path / "model.gguf"),
                )
            )
        else:
            getattr(runtime, operation)()
    assert runtime.spec is None and runtime._model is None and not runtime.loaded
    assert not runtime.health().ok
    runtime.close()  # idempotent cleanup must not call the failed model a second time
