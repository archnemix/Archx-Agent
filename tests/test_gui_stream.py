"""The chat reply, as the page receives it: server-sent events over a real socket.

`POST /api/chat` returns a finished reply, which is fine for a script and wrong for a person
watching a slow model think. `POST /api/chat/stream` runs the same turn - same task, same stored
messages - and writes each piece as it arrives.

What would quietly go wrong, and is therefore what these tests check:

* a stream that is really one lump: the chunks must arrive as separate frames, before the `done`;
* a stream with no length: sending `Content-Length` would buffer every frame until the end;
* a stream that forgets it is authenticated: the token and the CSRF header are required, exactly
  as for the non-streaming route;
* a stream that hangs on failure instead of ending with an `error` frame.
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
from pathlib import Path

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.interfaces.gui.server import GuiApi, GuiServer

ASSETS = Path(__file__).resolve().parent.parent / "src" / "archx_agent" / "interfaces" / "gui" / "assets"


@pytest.fixture()
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "1")
    with open_workspace(home=str(tmp_path / "home"), env=dict(os.environ)) as ws:
        ws.models.register_remote(
            "double",
            provider="test-double",
            runtime="scripted",
            model_ref="simulated",
            context_length=8192,
            capabilities=["chat"],
            verification="unverified",
            claims={"simulated": True},
        )
        api = GuiApi(ws)
        server = GuiServer(api, port=0)
        server.start()
        try:
            yield api, server
        finally:
            server.stop()


def _post(server: GuiServer, path: str, payload: dict, *, token: str | None, csrf: bool = True) -> tuple[str, bytes]:
    body = json.dumps(payload).encode()
    lines = [
        f"POST {path} HTTP/1.1",
        "Host: 127.0.0.1",
        f"Content-Length: {len(body)}",
        "Content-Type: application/json",
        "Connection: close",
    ]
    if csrf:
        lines.append("X-Archx-Request: gui")
    if token:
        lines.append(f"X-Archx-Token: {token}")
    request = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
    sock = socket.create_connection(("127.0.0.1", server.port), timeout=20)
    try:
        sock.sendall(request)
        chunks = []
        while True:
            data = sock.recv(8192)
            if not data:
                break
            chunks.append(data)
    finally:
        sock.close()
    raw = b"".join(chunks)
    head, _, rest = raw.partition(b"\r\n\r\n")
    return head.decode("latin-1"), rest


def _frames(rest: bytes) -> list[tuple[str, dict]]:
    out = []
    for block in rest.decode("utf-8").split("\n\n"):
        event, data = "message", ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data += line[6:]
        if data:
            out.append((event, json.loads(data)))
    return out


class TestTheStream:
    def test_it_is_an_event_stream_with_no_length(self, gui):
        api, server = gui
        head, _ = _post(server, "/api/chat/stream", {"message": "hi"}, token=api.token)
        assert head.splitlines()[0].endswith("200 OK")
        assert "content-type: text/event-stream" in head.lower()
        assert "content-length" not in head.lower(), "a length would buffer every frame"
        assert "connection: close" in head.lower()

    def test_the_chunks_arrive_separately_and_before_the_done_frame(self, gui):
        api, server = gui
        _, rest = _post(server, "/api/chat/stream", {"message": "hi"}, token=api.token)
        frames = _frames(rest)
        events = [event for event, _ in frames]
        assert "done" in events
        assert events[-1] == "done"
        chunks = [payload["text"] for event, payload in frames if event == "chunk"]
        assert len(chunks) > 1, "one chunk is a lump, not a stream"
        done = frames[-1][1]
        assert "".join(chunks) == done["text"]
        assert done["task"]["id"].startswith("tk_")

    def test_the_turn_is_recorded_like_any_other(self, gui):
        api, server = gui
        _, rest = _post(server, "/api/chat/stream", {"message": "a streamed turn"}, token=api.token)
        done = _frames(rest)[-1][1]
        messages = api.ws.conversations.messages(done["conversation_id"])
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[0].content == "a streamed turn"
        assert messages[1].content == done["text"]

    def test_it_needs_the_token(self, gui):
        api, server = gui
        head, rest = _post(server, "/api/chat/stream", {"message": "hi"}, token=None)
        assert "401" in head.splitlines()[0]
        assert b"event:" not in rest

    def test_it_refuses_a_write_with_no_credential_of_any_kind(self, gui):
        """A cookie-less request with no CSRF header and no token is not a browser's request.

        It is refused as unauthenticated (`401`) rather than as a CSRF failure: with no cookie
        there is no session to be riding, and telling the caller to add a header would send
        them to fix the wrong thing.
        """
        api, server = gui
        head, rest = _post(server, "/api/chat/stream", {"message": "hi"}, token=None, csrf=False)
        assert "401" in head.splitlines()[0]
        assert b"event: chunk" not in rest

    def test_a_refused_turn_ends_with_an_error_frame_not_a_hang(self, gui):
        api, server = gui
        # no model_id and no usable default: the router refuses, and the stream says so
        _, rest = _post(server, "/api/chat/stream", {"message": "hi", "model_id": "nope"}, token=api.token)
        frames = _frames(rest)
        assert frames, "the stream ended without a frame"
        assert frames[-1][0] == "error"
        assert frames[-1][1]["message"]


class TestThePage:
    def test_the_page_reads_the_stream_and_falls_back(self):
        source = (ASSETS / "app.js").read_text()
        assert "/api/chat/stream" in source
        assert "getReader" in source, "EventSource cannot POST, so the body is read directly"
        # the fallback matters: an older client, or a runtime that cannot stream, still answers
        assert 'api("POST", "/api/chat"' in source
        assert "event: chunk" not in source  # frames are parsed, not assumed

    def test_the_page_paints_partial_text(self):
        source = (ASSETS / "app.js").read_text()
        assert re.search(r"const paint = \(piece\) =>", source)
        assert "renderMarkdown(streamed)" in source
