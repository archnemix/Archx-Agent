"""Edge cases: the inputs a client sends when it is confused, hostile, or just wrong.

Each test here exists because of a specific way the GUI can be got at, and several were written
after a bug: `str(request.field(...))` coerced a JSON object into its Python repr and stored it as
a chat message; a non-string `model_id` reached SQLite and produced a **500**; `/api/health`
answered `DELETE`; and a four-thousand-character path produced a 500 with a message about missing
assets. All four are regression tests below.

The rule these encode: **anything the client controls is a 4xx, never a 5xx.** A 500 is the
server admitting it did not anticipate its own input.
"""

from __future__ import annotations

import json
import socket

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.interfaces.gui.server import GuiApi, GuiServer

BODY_LIMIT = 1_048_576
MESSAGE_LIMIT = 8000


@pytest.fixture()
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "1")
    with open_workspace(home=str(tmp_path / "home"), env={"ARCHX_ALLOW_SIMULATED": "1"}) as ws:
        ws.models.register_remote(
            "double", provider="test-double", runtime="scripted", model_ref="simulated",
            context_length=8192, capabilities=["chat"], verification="unverified",
            claims={"simulated": True},
        )
        api = GuiApi(ws)
        server = GuiServer(api, port=0)
        server.start()
        try:
            yield api, server, ws
        finally:
            server.stop()


def call(server, method, path, *, payload=None, raw=None, token=None, headers=None):
    if raw is None and payload is not None:
        raw = json.dumps(payload).encode()
    raw = raw or b""
    lines = [f"{method} {path} HTTP/1.1", "Host: x", f"Content-Length: {len(raw)}",
             "Connection: close"]
    if raw:
        lines.append("Content-Type: application/json")
    if token:
        lines.append(f"X-Archx-Token: {token}")
    for key, value in (headers or {}).items():
        lines.append(f"{key}: {value}")
    blob = ("\r\n".join(lines) + "\r\n\r\n").encode() + raw
    with socket.create_connection(("127.0.0.1", server.port), timeout=60) as sock:
        sock.sendall(blob)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1])
    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError:
        parsed = {"_unparsed": body.decode("utf-8", "replace")}
    return status, parsed, body


# --------------------------------------------------------------------------
# the type of a field
# --------------------------------------------------------------------------
class TestFieldTypes:
    """A field has a type. Coercing it is how junk reaches a model."""

    @pytest.mark.parametrize("bad", [123, 4.5, True, ["a"], {"a": 1}, [{"a": 1}]])
    def test_a_message_that_is_not_a_string_is_a_400(self, gui, bad):
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/chat", payload={"message": bad},
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 400, f"{bad!r} was accepted"
        assert data["error"]["code"] == "validation"
        assert "must be a string" in data["error"]["message"]

    def test_a_non_string_model_id_is_a_400_not_a_500(self, gui):
        """It was a 500: the dict reached SQLite and raised a ProgrammingError."""
        api, server, _ws = gui
        for bad in ({"a": 1}, ["x"], 7):
            status, data, _ = call(server, "POST", "/api/chat",
                                   payload={"message": "hi", "model_id": bad},
                                   headers={"X-Archx-Request": "gui"}, token=api.token)
            assert status == 400, f"model_id={bad!r} -> {status}"
            assert data["error"]["code"] == "validation"

    def test_a_non_string_conversation_id_is_a_400(self, gui):
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/chat",
                               payload={"message": "hi", "conversation_id": 42},
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 400
        assert "conversation_id must be a string" in data["error"]["message"]

    def test_the_same_types_are_refused_on_the_streaming_route(self, gui):
        api, server, _ws = gui
        status, _data, body = call(server, "POST", "/api/chat/stream",
                                   payload={"message": {"a": 1}},
                                   headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 400
        assert b"event:" not in body

    def test_other_routes_validate_their_strings_too(self, gui):
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/memory",
                               payload={"kind": "permanent", "title": {"a": 1}, "content": "x"},
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 400, data
        assert data["error"]["code"] == "validation"


# --------------------------------------------------------------------------
# boundaries
# --------------------------------------------------------------------------
class TestMessageBoundaries:
    def test_exactly_the_limit_is_accepted(self, gui):
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/chat",
                               payload={"message": "a" * MESSAGE_LIMIT},
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 200
        assert data["ok"] is True

    def test_one_over_the_limit_is_refused(self, gui):
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/chat",
                               payload={"message": "a" * (MESSAGE_LIMIT + 1)},
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 400
        assert "8000" in data["error"]["message"]

    @pytest.mark.parametrize("empty", ["", "   ", "\n\t ", " \u00a0 "])
    def test_an_empty_or_blank_message_is_refused(self, gui, empty):
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/chat", payload={"message": empty},
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 400
        assert data["error"]["code"] == "validation"

    def test_a_body_over_the_limit_is_413_and_the_connection_stays_usable(self, gui):
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/chat",
                               raw=b"x" * (BODY_LIMIT + 1),
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 413
        assert data["error"]["code"] == "too_large"
        assert call(server, "GET", "/api/health")[0] == 200


# --------------------------------------------------------------------------
# text that is not ASCII
# --------------------------------------------------------------------------
class TestOddText:
    @pytest.mark.parametrize("text", [
        "héllo wörld",
        "🌍🌏🌎 emoji only",
        "مرحبا بالعالم",            # RTL
        "日本語のテキスト",           # CJK, no spaces
        "a\u0301\u0301 combining",   # combining marks
        "zero\u0000byte",            # a NUL inside JSON is legal
        "tab\tand\nnewline",
        "line\u2028separator",       # Unicode line separator
        "🦀" * 100,                  # astral plane, repeated
    ])
    def test_the_text_comes_back_exactly(self, gui, text):
        api, server, ws = gui
        status, data, _ = call(server, "POST", "/api/chat", payload={"message": text},
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 200, data
        conversation_id = data["data"]["conversation_id"]
        stored = ws.conversations.messages(conversation_id)[0].content
        assert stored == text

    def test_invalid_utf8_in_the_body_is_a_400(self, gui):
        api, server, _ws = gui
        broken = b'{"message": "abc\xff\xfe"}'
        status, data, _ = call(server, "POST", "/api/chat", raw=broken,
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 400
        assert data["error"]["code"] in {"bad_json", "validation"}


# --------------------------------------------------------------------------
# malformed requests
# --------------------------------------------------------------------------
class TestMalformedRequests:
    @pytest.mark.parametrize("raw", [b"{", b"{,}", b"[1,2", b"null", b"true", b"42", b'"str"', b"[]"])
    def test_a_body_that_is_not_a_json_object_is_a_400(self, gui, raw):
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/chat", raw=raw,
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 400, f"{raw!r} -> {status}"
        assert data["ok"] is False

    def test_a_missing_body_is_a_400_not_a_crash(self, gui):
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/chat", raw=b"",
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 400
        assert data["error"]["code"] == "validation"

    def test_duplicate_json_keys_do_not_smuggle_a_second_message(self, gui):
        """The last key wins, JSON's rule; the point is that it is one message, not two."""
        api, server, ws = gui
        raw = b'{"message": "first", "message": "second"}'
        status, data, _ = call(server, "POST", "/api/chat", raw=raw,
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 200
        messages = ws.conversations.messages(data["data"]["conversation_id"])
        assert [m.content for m in messages if m.role == "user"] == ["second"]


# --------------------------------------------------------------------------
# routing and methods
# --------------------------------------------------------------------------
class TestRouting:
    def test_health_answers_get_only(self, gui):
        """It answered DELETE, PUT and POST with a health payload - a routing accident."""
        api, server, _ws = gui
        for method in ("POST", "PUT", "DELETE", "PATCH", "FROBNICATE"):
            status, data, _ = call(server, method, "/api/health", token=api.token)
            assert status == 405, f"{method} -> {status}"
            assert data["error"]["code"] == "method_not_allowed"
        assert call(server, "GET", "/api/health")[0] == 200

    def test_an_unknown_verb_gets_json_not_the_stdlib_501_page(self, gui):
        """`PATCH` used to return an HTML 501 from BaseHTTPRequestHandler."""
        api, server, _ws = gui
        status, data, body = call(server, "PATCH", "/api/chat", payload={"message": "x"},
                                  headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status != 501
        assert b"<html" not in body.lower()
        assert isinstance(data, dict) and data["ok"] is False

    def test_head_returns_headers_and_no_body(self, gui):
        api, server, _ws = gui
        status, _data, body = call(server, "HEAD", "/api/health")
        assert status == 200
        assert body == b""

    def test_a_wrong_method_on_a_real_route_is_404(self, gui):
        api, server, _ws = gui
        status, data, _ = call(server, "GET", "/api/chat", token=api.token)
        assert status == 404
        assert data["error"]["code"] == "no_route"

    def test_an_unknown_api_route_is_404(self, gui):
        api, server, _ws = gui
        status, data, _ = call(server, "GET", "/api/does-not-exist", token=api.token)
        assert status == 404
        assert data["error"]["code"] == "no_route"

    @pytest.mark.parametrize("path", [
        "/../server.py", "/%2e%2e%2fserver.py", "/..%2f..%2fserver.py",
        "/assets/../../server.py", "/.git/config", "/%00", "/app.js%00.png",
    ])
    def test_no_path_escapes_the_assets_directory(self, gui, path):
        api, server, _ws = gui
        status, _data, body = call(server, "GET", path)
        assert status in {404, 400}, f"{path} -> {status}"
        assert b"class " not in body[:200] or b"GuiApi" not in body

    def test_an_absurdly_long_path_is_a_404_not_a_500(self, gui):
        """It was a 500 whose message complained about missing assets."""
        api, server, _ws = gui
        status, data, _ = call(server, "GET", "/" + "a" * 4000)
        assert status == 404, data
        assert data["error"]["code"] == "not_found"


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------
class TestCredentials:
    def test_a_missing_token_is_401_on_every_data_route(self, gui):
        api, server, _ws = gui
        for method, path in (("GET", "/api/status"), ("GET", "/api/models"),
                             ("GET", "/api/conversations"), ("POST", "/api/chat")):
            status, _data, _ = call(server, method, path,
                                    payload={"message": "x"} if method == "POST" else None,
                                    headers={"X-Archx-Request": "gui"})
            assert status == 401, f"{method} {path} -> {status}"

    def test_a_wrong_token_is_401_and_looks_like_a_missing_one(self, gui):
        api, server, _ws = gui
        good, bad, _ = call(server, "GET", "/api/status", token=api.token)
        assert good == 200 and bad["ok"] is True
        wrong, wrong_data, _ = call(server, "GET", "/api/status", token="nope")
        assert bad["ok"] is True and wrong == 401
        # the two failures must be indistinguishable: "your token is wrong" is a hint
        missing, missing_data, _ = call(server, "GET", "/api/status")
        assert wrong_data["error"]["code"] == missing_data["error"]["code"]
        assert wrong_data["error"]["message"] == missing_data["error"]["message"]

    def test_a_write_with_a_cookie_but_no_csrf_header_is_refused(self, gui):
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/chat", payload={"message": "x"},
                               headers={"Cookie": f"archx_gui={api._cookie_value()}"})
        assert status == 403
        assert data["error"]["code"] == "csrf"

    def test_health_is_the_one_public_endpoint(self, gui):
        api, server, _ws = gui
        status, data, _ = call(server, "GET", "/api/health")
        assert status == 200
        # and it says nothing a stranger could use beyond "the process is alive"
        assert set(data["data"]) >= {"app", "version", "uptime_seconds"}

    def test_health_answers_head_so_a_monitor_can_curl_it(self, gui):
        """`curl -I` is what every uptime check does; HEAD is GET without the body."""
        _api, server, _ws = gui
        status, _data, body = call(server, "HEAD", "/api/health")
        assert status == 200
        assert body == b""

    def test_health_refuses_every_write_verb_with_a_json_405(self, gui):
        """It answers by accident for any verb the router lets through; a POST that returns
        a health payload is a routing hole, not a feature."""
        _api, server, _ws = gui
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            status, data, _ = call(server, method, "/api/health",
                                   payload={} if method in {"POST", "PUT", "PATCH"} else None)
            assert status == 405, f"{method} /api/health -> {status}"
            assert data["error"]["code"] == "method_not_allowed"

    def test_an_unauthenticated_write_says_401_not_csrf(self, gui):
        """There is no credential, so there is nothing to have forged. Telling the caller a
        CSRF header is missing sends them to fix the wrong thing."""
        _api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/memory", payload={"title": "x"},
                               headers={"X-Archx-Request": "gui"})
        assert status == 401
        assert data["error"]["code"] == "unauthorized"


# --------------------------------------------------------------------------
# things that do not exist
# --------------------------------------------------------------------------
class TestMissingThings:
    def test_a_conversation_that_does_not_exist_is_404(self, gui):
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/chat",
                               payload={"message": "hi", "conversation_id": "conv_nope"},
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 404
        assert data["error"]["code"] == "not_found"

    def test_a_model_that_does_not_exist_is_404_not_500(self, gui):
        """`ModelNotFoundError` inherits `ProviderError`, so it used to map to 500."""
        api, server, _ws = gui
        status, data, _ = call(server, "POST", "/api/chat",
                               payload={"message": "hi", "model_id": "mdl_nope"},
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 404, data
        assert data["error"]["code"] == "model_not_found"

    def test_a_message_for_a_missing_model_still_streams_an_error_frame(self, gui):
        api, server, _ws = gui
        status, _data, body = call(server, "POST", "/api/chat/stream",
                                   payload={"message": "hi", "model_id": "mdl_nope"},
                                   headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 200, "the stream begins, then reports the failure as a frame"
        assert b"event: error" in body
        assert b"event: done" not in body


# --------------------------------------------------------------------------
# a provider's fault is not the server's fault
# --------------------------------------------------------------------------
class TestProviderFaultsAreNotServerFaults:
    """Every one of these used to be a 500, because they all inherit `ProviderError`.

    A user reading "500 internal error" when their key is wrong, or when a vendor is down, is
    being told the wrong thing and will look in the wrong place.
    """

    @pytest.mark.parametrize("error, expected, code", [
        ("ModelNotFoundError", 404, "model_not_found"),
        ("AuthDeniedError", 403, "auth_denied"),
        ("RateLimitedError", 429, "rate_limited"),
        ("QuotaExhaustedError", 402, "quota_exhausted"),
        ("ProviderOutageError", 503, "provider_outage"),
        ("NetworkFailureError", 502, "network_failure"),
        ("MalformedOutputError", 502, "malformed_output"),
        ("ModelUnavailableError", 409, "model_unavailable"),
        ("UnsupportedCapabilityError", 422, "unsupported_capability"),
        ("LocalRuntimeFailureError", 503, "runtime_failure"),
        ("StorageBusyError", 503, "storage_busy"),
        ("ToolTimeoutError", 504, "tool_timeout"),
        ("ContextOverflowError", 413, "context_overflow"),
        ("PrivacyUnknownError", 403, "privacy_unknown"),
        ("ConsentRequiredError", 403, "consent_required"),
    ])
    def test_the_status_and_the_code(self, error, expected, code):
        import archx_agent.helpers.exceptions as exceptions
        from archx_agent.interfaces.gui.server import error_for

        kind = getattr(exceptions, error)
        mapped = error_for(kind("something went wrong"))
        assert (mapped.status, mapped.code) == (expected, code)

    def test_a_bug_is_still_a_500(self):
        """Widening the map must not swallow the server's own mistakes."""
        from archx_agent.interfaces.gui.server import error_for

        assert error_for(ZeroDivisionError("boom")).status == 500
        assert error_for(TypeError("x")).code == "internal"

    def test_a_provider_failure_over_http_carries_its_code(self, gui, monkeypatch):
        api, server, _ws = gui
        from archx_agent.application.chat import ChatService
        from archx_agent.helpers.exceptions import ProviderOutageError

        def explode(*args, **kwargs):
            raise ProviderOutageError("the vendor is down", provider="test")

        # `Workspace.chat` builds a new service on every access, so patch the class: patching an
        # instance would have patched nothing and the test would have passed for the wrong reason.
        monkeypatch.setattr(ChatService, "send", explode)
        status, data, _ = call(server, "POST", "/api/chat", payload={"message": "hi"},
                               headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 503
        assert data["error"]["code"] == "provider_outage"

    def test_the_stream_reports_the_same_code_in_a_frame(self, gui, monkeypatch):
        api, server, _ws = gui
        from archx_agent.application.chat import ChatService
        from archx_agent.helpers.exceptions import AuthDeniedError

        def explode(*args, **kwargs):
            raise AuthDeniedError("no key", provider="test")

        monkeypatch.setattr(ChatService, "send", explode)
        status, _data, body = call(server, "POST", "/api/chat/stream", payload={"message": "hi"},
                                   headers={"X-Archx-Request": "gui"}, token=api.token)
        assert status == 200
        assert b"event: error" in body
        assert b"auth_denied" in body, body[-200:]
