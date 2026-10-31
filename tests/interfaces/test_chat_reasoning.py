"""Provider-output fixtures exercise reasoning plumbing, not real model inference."""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from archx_agent.adapters.http_runtime import HttpChatRuntime
from archx_agent.adapters.model_runtime import GenerationParams, ModelSpec
from archx_agent.adapters.reasoning import ThinkingSplitter, reasoning_text
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import MalformedOutputError
from archx_agent.interfaces.gui.server import GuiApi, GuiServer
from tests.interfaces.test_gui_stream import _frames, _post


@pytest.mark.parametrize("width", range(1, 15))
def test_leading_thinking_tags_split_at_arbitrary_boundaries(width):
    splitter = ThinkingSplitter()
    text = "  <think>Check a < b.\nThen compare.</think>Final answer."
    parts = []
    for index in range(0, len(text), width):
        parts.extend(splitter.feed(text[index:index + width]))
    parts.extend(splitter.finish())
    assert "".join(piece for kind, piece in parts if kind == "reasoning") == "Check a < b.\nThen compare."
    assert "".join(piece for kind, piece in parts if kind == "content") == "Final answer."


@pytest.mark.parametrize("text", ["Plain answer", "Example: <think> is a tag", "<thing>", "  ", "<thin"])
def test_ordinary_answers_and_partial_prefixes_are_preserved(text):
    splitter = ThinkingSplitter()
    parts = splitter.feed(text) + splitter.finish()
    assert parts == [("content", text)]


def test_unclosed_thinking_block_is_not_presented_as_an_answer():
    splitter = ThinkingSplitter()
    parts = splitter.feed("<think>Still working") + splitter.finish()
    assert parts == [("reasoning", "Still working")]
    assert ThinkingSplitter().feed("<think>") == []


@pytest.mark.parametrize("key", ["reasoning", "reasoning_content"])
def test_reasoning_fields_are_optional_but_must_be_text(key):
    assert reasoning_text({key: "provider words"}, "fixture") == "provider words"
    assert reasoning_text({key: None}, "fixture") == ""
    with pytest.raises(MalformedOutputError):
        reasoning_text({key: {"not": "text"}}, "fixture")


@pytest.fixture()
def provider():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if body.get("stream") else "application/json")
            self.end_headers()
            if body.get("stream"):
                deltas = [{"role": "assistant", "content": None}, {"reasoning": "First, "}, {"reasoning_content": "compare."}, {"content": "RAM is temporary."}]
                if body["model"].endswith("-tags"):
                    tagged = "<think>First, compare.</think>RAM is temporary."
                    deltas = [{"content": tagged[index:index + 3]} for index in range(0, len(tagged), 3)]
                for delta in deltas:
                    self.wfile.write(("data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\n").encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                message = {"content": "RAM is temporary.", "reasoning": "First, compare."}
                if body["model"].endswith("-tags"):
                    message = {"content": "<think>First, compare.</think>RAM is temporary."}
                self.wfile.write(json.dumps({"choices": [{"message": message}]}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_legacy_http_stream_still_yields_only_answer_strings(provider):
    url, _ = provider
    runtime = HttpChatRuntime(url)
    runtime.load(ModelSpec("fixture", "fixture", "openai-http", model="test-model"))
    assert list(runtime.stream([{"role": "user", "content": "hello"}], GenerationParams())) == ["RAM is temporary."]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("model_ref", ["test-model", "test-model-tags"])
def test_http_to_gui_to_saved_history_keeps_reasoning_separate(tmp_path, provider, stream, model_ref):
    url, requests = provider
    with open_workspace(home=str(tmp_path / "home"), env={}) as ws:
        model = ws.models.register_remote("HTTP output fixture", provider="openai-compatible", runtime="openai-http", model_ref=model_ref, base_url=url, capabilities=["chat"])
        api = GuiApi(ws)
        server = GuiServer(api, port=0)
        server.start()
        try:
            head, body = _post(server, "/api/chat/stream" if stream else "/api/chat", {"message": "Compare RAM", "model_id": model.id}, token=api.token)
            assert "200 OK" in head
            if stream:
                frames = _frames(body)
                assert frames[-1][0] == "done", frames
                assert "".join(data["text"] for event, data in frames if event == "reasoning") == "First, compare."
                assert "".join(data["text"] for event, data in frames if event == "chunk") == "RAM is temporary."
                reply = frames[-1][1]
            else:
                reply = json.loads(body)["data"]
            assert reply["text"] == "RAM is temporary."
            assert reply["reasoning"] == "First, compare."
            assert reply["model"]["model_id"] == model.id
            saved = ws.conversations.messages(reply["conversation_id"])[-1]
            assert saved.content == reply["text"]
            assert saved.metadata["reasoning"] == reply["reasoning"]
            request = urllib.request.Request(server.url + "api/conversations/" + reply["conversation_id"] + "/messages", headers={"X-Archx-Token": api.token})
            with urllib.request.urlopen(request) as response:
                history = json.load(response)["data"]
            assert history["model_id"] == model.id
            assert history["messages"][-1]["reasoning"] == reply["reasoning"]
            assert len(requests) == 1, "GUI must not replay a turn"
            assert requests[0]["model"] == model_ref
        finally:
            server.stop()
