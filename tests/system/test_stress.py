"""Stress: the same behaviour, fifty times at once, with clients that misbehave.

Every other suite checks a path once. This one checks the things that only appear under load or
misuse, and it is written against the parts of the app that are hardest to fix later:

* **the single writer.** SQLite allows one writer; the coordinator serialises them. If that
  promise is wrong, the symptom is "database is locked" under exactly the conditions nobody
  reproduces by hand.
* **the GUI's threading.** `ThreadingHTTPServer` means every request is a thread. Twenty chat
  turns at once must produce twenty tasks, not nineteen and a half.
* **the streaming path**, which keeps a thread and a socket alive for the duration of a reply. A
  browser tab closed mid-answer is the normal case, not the edge case.
* **bodies that are too big, too malformed, or never finished.**
* **a provider that never answers**, where the only acceptable outcomes are a timeout error and
  no leaked thread.

Nothing here sleeps for the sake of it: the waits are on real conditions, and the whole file
targets a few minutes on one CPU.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import ArchxError, NetworkFailureError
from archx_agent.interfaces.gui.server import GuiApi, GuiServer


def _home(tmp_path, name="home"):
    return str(tmp_path / name)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "1")
    with open_workspace(home=_home(tmp_path), env={"ARCHX_ALLOW_SIMULATED": "1"}) as workspace:
        workspace.models.register_remote(
            "double",
            provider="test-double",
            runtime="scripted",
            model_ref="simulated",
            context_length=8192,
            capabilities=["chat"],
            verification="unverified",
            claims={"simulated": True},
        )
        yield workspace


@pytest.fixture()
def gui(ws):
    api = GuiApi(ws)
    server = GuiServer(api, port=0)
    server.start()
    try:
        yield api, server
    finally:
        server.stop()


# --------------------------------------------------------------------------
# tiny HTTP client: enough to misbehave on purpose
# --------------------------------------------------------------------------
def request(server: GuiServer, method: str, path: str, payload=None, *, token=None,
            raw: bytes | None = None, headers: dict | None = None, timeout: float = 60.0):
    """Return (status, headers-dict, body-bytes). No urllib: it hides what we want to see."""
    if raw is None and payload is not None:
        raw = json.dumps(payload).encode()
    raw = raw or b""
    lines = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1",
             f"Content-Length: {len(raw)}", "Connection: close"]
    if raw:
        lines.append("Content-Type: application/json")
    if token:
        lines.append(f"X-Archx-Token: {token}")
    for key, value in (headers or {}).items():
        lines.append(f"{key}: {value}")
    blob = ("\r\n".join(lines) + "\r\n\r\n").encode() + raw
    with socket.create_connection(("127.0.0.1", server.port), timeout=timeout) as sock:
        sock.sendall(blob)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    text = head.decode("latin-1")
    status = int(text.split(" ")[1])
    parsed = {}
    for line in text.split("\r\n")[1:]:
        if ": " in line:
            key, value = line.split(": ", 1)
            parsed[key.lower()] = value
    return status, parsed, body


def json_of(server: GuiServer, method: str, path: str, payload=None, *, token=None):
    status, _headers, body = request(server, method, path, payload, token=token)
    return status, json.loads(body or b"{}")


# --------------------------------------------------------------------------
# the single writer
# --------------------------------------------------------------------------
class TestStorageUnderLoad:
    def test_forty_threads_append_to_one_conversation_and_none_is_lost(self, ws):
        conversation = ws.conversations.create("stress")
        writers, per_writer = 8, 5
        errors: list[BaseException] = []
        barrier = threading.Barrier(writers)

        def write(index: int) -> None:
            barrier.wait()
            try:
                for turn in range(per_writer):
                    ws.conversations.append_message(
                        conversation.id, "user", f"writer {index} turn {turn}"
                    )
            except BaseException as exc:  # noqa: BLE001 - the test wants the real failure
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(writers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert errors == [], f"writers raised: {errors[:3]}"
        messages = ws.conversations.messages(conversation.id)
        assert len(messages) == writers * per_writer
        # sequence numbers are unique and contiguous: no gap means no lost write
        assert [m.seq for m in messages] == list(range(1, writers * per_writer + 1))
        # and every writer's own turns are in order relative to itself
        for index in range(writers):
            own = [m.content for m in messages if m.content.startswith(f"writer {index} ")]
            assert own == [f"writer {index} turn {turn}" for turn in range(per_writer)]

    def test_readers_never_see_a_half_written_conversation(self, ws):
        """A reader looping during writes must always see a whole number of messages."""
        conversation = ws.conversations.create("readers")
        stop = threading.Event()
        bad: list[tuple[int, int]] = []

        def reader() -> None:
            while not stop.is_set():
                messages = ws.conversations.messages(conversation.id)
                seqs = [m.seq for m in messages]
                if seqs != list(range(1, len(seqs) + 1)):
                    bad.append((len(seqs), seqs[-1] if seqs else 0))

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            for turn in range(60):
                ws.conversations.append_message(conversation.id, "user", f"turn {turn}")
        finally:
            stop.set()
            thread.join(timeout=10)
        assert bad == []

    def test_a_megabyte_message_survives_the_round_trip(self, ws):
        conversation = ws.conversations.create("big")
        blob = ("the quick brown fox " * 50_000)[:1_048_576]
        ws.conversations.append_message(conversation.id, "user", blob)
        back = ws.conversations.messages(conversation.id)[0].content
        assert len(back) == len(blob)
        assert back == blob


# --------------------------------------------------------------------------
# the GUI's threading
# --------------------------------------------------------------------------
class TestTheServerUnderConcurrency:
    def test_twenty_chat_turns_at_once_each_produce_one_task(self, gui, ws):
        api, server = gui
        before = len(ws.tasks.list(limit=500)) if hasattr(ws.tasks, "list") else 0
        answers: list[tuple[int, str]] = []
        lock = threading.Lock()

        def turn(index: int) -> None:
            status, data = json_of(server, "POST", "/api/chat", {"message": f"turn {index}"},
                                   token=api.token)
            with lock:
                answers.append((status, data.get("data", {}).get("task", {}).get("id", "")))

        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(turn, range(20)))

        assert [status for status, _ in answers] == [200] * 20
        task_ids = [task for _, task in answers]
        assert len(set(task_ids)) == 20, "two turns shared one task"
        assert all(task.startswith("tk_") for task in task_ids)
        after = len(ws.tasks.list(limit=500))
        assert after - before == 20

    def test_three_hundred_requests_leak_no_file_descriptors(self, gui):
        api, server = gui
        fd_dir = "/proc/self/fd"
        if not os.path.isdir(fd_dir):
            pytest.skip("no /proc on this platform")
        before = len(os.listdir(fd_dir))
        for _ in range(300):
            status, _ = json_of(server, "GET", "/api/health")
            assert status == 200
        after = len(os.listdir(fd_dir))
        # a small drift is normal (allocators, sqlite); 300 requests must not add 30 sockets
        assert after - before < 15, f"fds grew from {before} to {after}"

    def test_a_body_over_the_limit_is_refused_without_reading_it_into_memory(self, gui):
        api, server = gui
        status, headers, body = request(
            server, "POST", "/api/chat", raw=b"x" * (1_048_576 + 10), token=api.token
        )
        assert status == 413
        assert json.loads(body)["error"]["code"] == "too_large"
        # and the server is still answering afterwards
        assert json_of(server, "GET", "/api/health")[0] == 200

    def test_a_malformed_body_is_a_400_and_the_server_survives(self, gui):
        api, server = gui
        for broken in (b"{not json", b"\xff\xfe\x00binary", b"[]", b'"a string"'):
            status, _headers, body = request(server, "POST", "/api/chat", raw=broken, token=api.token)
            assert status == 400, f"{broken[:12]!r} -> {status}"
            assert json.loads(body)["ok"] is False
        assert json_of(server, "GET", "/api/health")[0] == 200

    def test_a_slow_client_does_not_block_the_others(self, gui):
        """ThreadingHTTPServer's whole point: one stalled connection must not stop the server."""
        api, server = gui
        stalled = socket.create_connection(("127.0.0.1", server.port), timeout=10)
        try:
            # a request line and headers promising a body that never arrives
            stalled.sendall(b"POST /api/chat HTTP/1.1\r\nHost: x\r\nContent-Length: 500\r\n\r\n")
            time.sleep(0.2)
            started = time.perf_counter()
            status, _ = json_of(server, "GET", "/api/health", token=api.token)
            assert status == 200
            assert time.perf_counter() - started < 5, "the stalled client held the server"
        finally:
            stalled.close()


# --------------------------------------------------------------------------
# streaming: threads, sockets, and clients that vanish
# --------------------------------------------------------------------------
class TestTheStreamUnderStress:
    def _stream(self, server: GuiServer, token: str, message: str, *, read_bytes: int | None = None,
                stop_after: bytes | None = None):
        """POST and read the event stream; optionally hang up after a byte count or a marker.

        The headers alone are several hundred bytes (security headers, CSP), so a byte count has
        to be generous or the "disconnect" happens before any frame exists.
        """
        raw = json.dumps({"message": message}).encode()
        head = (f"POST /api/chat/stream HTTP/1.1\r\nHost: x\r\nContent-Length: {len(raw)}\r\n"
                f"Connection: close\r\nX-Archx-Token: {token}\r\n"
                f"X-Archx-Request: gui\r\nContent-Type: application/json\r\n\r\n").encode()
        sock = socket.create_connection(("127.0.0.1", server.port), timeout=30)
        sock.sendall(head + raw)
        buffer = b""
        try:
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                buffer += data
                if stop_after is not None and stop_after in buffer:
                    break
                if read_bytes is not None and len(buffer) >= read_bytes:
                    break
        finally:
            sock.close()
        return buffer

    def test_a_client_hanging_up_mid_stream_does_not_break_the_server(self, gui):
        api, server = gui
        # read only the first few hundred bytes, then close: the handler's writes will fail
        partial = self._stream(server, api.token, "cut me off", stop_after=b"event: chunk")
        assert b"event: chunk" in partial, "nothing streamed before the disconnect"
        time.sleep(0.2)  # let the handler notice the closed socket
        status, data = json_of(server, "GET", "/api/health")
        assert status == 200
        # and a normal stream still completes afterwards
        full = self._stream(server, api.token, "still working")
        assert b"event: done" in full

    def test_ten_streams_at_once_all_complete(self, gui):
        api, server = gui
        results: list[bytes] = []
        lock = threading.Lock()

        def run(index: int) -> None:
            out = self._stream(server, api.token, f"parallel {index}")
            with lock:
                results.append(out)

        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(run, range(10)))
        assert len(results) == 10
        for out in results:
            assert b"event: done" in out, out[:200]
            assert out.count(b"event: done") == 1

    def test_a_stream_that_fails_still_closes(self, gui):
        api, server = gui
        out = self._stream(server, api.token, f"unknown model", )
        assert b"event: done" in out
        # a bad model id must end in an error frame, and the socket must close (we got here)
        raw = json.dumps({"message": "x", "model_id": "nope"}).encode()
        head = (f"POST /api/chat/stream HTTP/1.1\r\nHost: x\r\nContent-Length: {len(raw)}\r\n"
                f"Connection: close\r\nX-Archx-Token: {api.token}\r\n"
                f"X-Archx-Request: gui\r\nContent-Type: application/json\r\n\r\n").encode()
        with socket.create_connection(("127.0.0.1", server.port), timeout=30) as sock:
            sock.sendall(head + raw)
            body = b""
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                body += data
        assert b"event: error" in body
        assert b"event: done" not in body


# --------------------------------------------------------------------------
# a provider that never answers
# --------------------------------------------------------------------------
class _Sleeper(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    holds = 0

    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802
        type(self).holds += 1
        time.sleep(5)  # longer than the client's timeout, on purpose
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")


class TestASlowProvider:
    def test_a_hanging_provider_times_out_instead_of_hanging_forever(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Sleeper)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            from archx_agent.adapters.sdk_transport import transport_for
            from archx_agent.adapters.model_runtime import GenerationParams

            transport = transport_for(
                "openai", api_key="k", base_url=f"http://127.0.0.1:{server.server_port}/v1",
                timeout=0.5,
            )
            started = time.perf_counter()
            try:
                with pytest.raises(ArchxError) as caught:
                    transport.chat([{"role": "user", "content": "hi"}],
                                   GenerationParams(temperature=0.0, max_tokens=8), model="m")
            finally:
                transport.close()
            elapsed = time.perf_counter() - started
            assert isinstance(caught.value, (NetworkFailureError, ArchxError))
            assert elapsed < 5, f"the client waited {elapsed:.1f}s on a 0.5s timeout"
        finally:
            server.shutdown()
            server.server_close()

    def test_many_concurrent_failures_do_not_accumulate_threads(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Sleeper)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        before = threading.active_count()
        try:
            from archx_agent.adapters.sdk_transport import transport_for
            from archx_agent.adapters.model_runtime import GenerationParams
            base = f"http://127.0.0.1:{server.server_port}/v1"

            def fail() -> None:
                transport = transport_for("openai", api_key="k", base_url=base, timeout=0.3)
                try:
                    transport.chat([{"role": "user", "content": "hi"}],
                                   GenerationParams(temperature=0.0, max_tokens=4), model="m")
                except ArchxError:
                    pass
                finally:
                    transport.close()

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: fail(), range(8)))
            time.sleep(0.5)
            after = threading.active_count()
            assert after - before < 12, f"threads grew {before} -> {after}"
        finally:
            server.shutdown()
            server.server_close()
