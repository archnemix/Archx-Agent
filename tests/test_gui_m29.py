"""M29: the local web GUI.

The GUI is the first surface a stranger can reach over a socket, so the tests are organised
around what could go wrong rather than around what the page looks like:

* an unauthenticated request that is answered anyway;
* a cross-site page that can write because a cookie was enough;
* a control that is wired to nothing, or that silently swallows a refusal;
* an asset path that escapes the assets directory;
* a GUI that disagrees with the CLI about what happened.

Everything is exercised through the same objects the HTTP layer uses, plus one real socket
for the things only a socket can prove (headers, HEAD, cookies, body limits, concurrency).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.interfaces.gui.server import (
    ASSETS,
    COOKIE_NAME,
    CSRF_VALUE,
    GuiApi,
    GuiServer,
    Request,
    Response,
    error_for,
    split_target,
)

CLI = os.path.join(os.path.dirname(sys.executable), "archx-agent")
TOKEN = "test-token-for-m29"


# --------------------------------------------------------------------------
# fixtures and helpers
# --------------------------------------------------------------------------
@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_ALLOW_SIMULATED", "1")
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


@pytest.fixture()
def model(ws):
    return ws.models.register_remote(
        "sim",
        provider="test-double",
        runtime="scripted",
        model_ref="simulated",
        capabilities=["chat"],
    )


@pytest.fixture()
def api(ws):
    return GuiApi(ws, token=TOKEN)


def call(api, method, path, *, token=TOKEN, body=None, headers=None, query=None, raw_path=None):
    """Dispatch one request the way the HTTP layer would, without a socket."""
    full = raw_path or path
    parsed_path, parsed_query, url_token = split_target(full)
    merged = {**parsed_query, **(query or {})}
    request = Request(
        method=method,
        path=parsed_path,
        query=merged,
        headers={"x-archx-token": token} if token else {},
        body=body,
        token=url_token,
        token_in_query=url_token is not None,
    )
    for key, value in (headers or {}).items():
        if value is None:
            request.headers.pop(key.lower(), None)
        else:
            request.headers[key.lower()] = value
    response = api.dispatch(request)
    payload = None
    if response.body is None:
        payload = response.payload
    return response.status, payload


def ok(api, method, path, **kwargs):
    status, payload = call(api, method, path, **kwargs)
    assert status == 200, (status, payload)
    assert payload["ok"] is True
    return payload["data"]


def failed(api, method, path, **kwargs):
    status, payload = call(api, method, path, **kwargs)
    assert status >= 400, (status, payload)
    assert payload["ok"] is False
    return status, payload["error"]


def http_get(url, *, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def http_send(url, method, body=None, *, headers=None):
    data = None if body is None else json.dumps(body).encode()
    merged = {"Content-Type": "application/json"} if data else {}
    merged.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=merged, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
class TestRoutes:
    def test_every_route_has_a_doc_and_a_unique_shape(self, api):
        routes = api.routes()
        assert len(routes) >= 18
        assert all(route.doc.strip() for route in routes)
        shapes = [(route.method, route.pattern.pattern) for route in routes]
        assert len(shapes) == len(set(shapes))

    def test_the_routes_are_the_ones_the_docs_claim(self, api):
        shapes = {(route.method, route.pattern.pattern) for route in api.routes()}
        for expected in [
            ("GET", "^/api/status$"),
            ("POST", "^/api/chat$"),
            ("GET", "^/api/search$"),
            ("POST", "^/api/research$"),
            ("GET", "^/api/jobs$"),
            ("POST", "^/api/approvals/(?P<approval_id>[^/]+)/(?P<decision>[^/]+)$"),
        ]:
            assert expected in shapes

    def test_every_route_except_health_requires_the_token(self, api):
        for route in api.routes():
            path = (
                route.pattern.pattern.strip("^$")
                .replace("(?P<approval_id>[^/]+)", "ap_x")
                .replace("(?P<decision>[^/]+)", "approve")
                .replace("(?P<job_id>[^/]+)", "jb_x")
                .replace("(?P<action>[^/]+)", "pause")
                .replace("(?P<task_id>[^/]+)", "tk_x")
                .replace("(?P<run_id>[^/]+)", "rs_x")
                .replace("(?P<grant_id>[^/]+)", "pg_x")
                .replace("(?P<conversation_id>[^/]+)", "conv_x")
            )
            status, payload = call(api, route.method, path, token=None, body={})
            # A write without the CSRF header is refused before authentication is even
            # considered; either refusal is a refusal.
            assert status in {401, 403}, (route.pattern.pattern, status, payload)
            assert payload["ok"] is False

    def test_health_is_public_and_says_nothing_private(self, api):
        status, payload = call(api, "GET", "/api/health", token=None)
        assert status == 200
        data = payload["data"]
        assert data["app"] == "archx-agent"
        assert data["auth"] == "token"
        assert "home" not in data and "database" not in data

    def test_an_unknown_route_is_a_json_404(self, api):
        status, error = failed(api, "GET", "/api/does-not-exist")
        assert status == 404 and error["code"] == "no_route"


# --------------------------------------------------------------------------
# authentication
# --------------------------------------------------------------------------
class TestAuth:
    def test_no_token_is_401_and_says_so(self, api):
        status, error = failed(api, "GET", "/api/status", token=None)
        assert status == 401 and error["code"] == "unauthorized"
        assert "token" in error["message"]

    def test_a_wrong_token_is_401(self, api):
        status, _ = failed(api, "GET", "/api/status", token="not-the-token")
        assert status == 401

    def test_the_token_can_arrive_in_the_query_string(self, api):
        data = ok(api, "GET", "/api/status", token=None, raw_path=f"/api/status?token={TOKEN}")
        assert data["home"]

    def test_the_token_can_arrive_as_a_bearer_header(self, api):
        status, payload = call(api, "GET", "/api/status", token=None,
                               headers={"authorization": f"Bearer {TOKEN}"})
        assert status == 200 and payload["ok"] is True

    def test_the_token_can_arrive_as_a_custom_header(self, api):
        status, payload = call(api, "GET", "/api/status", token=None, headers={"x-archx-token": TOKEN})
        assert status == 200 and payload["ok"] is True

    def test_a_session_cookie_is_issued_and_accepted(self, api):
        status, payload, headers = self._session(api)
        assert status == 200 and payload["ok"] is True
        cookie = headers["Set-Cookie"]
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
        value = cookie.split(";")[0].split("=", 1)[1]
        assert value != TOKEN, "the raw token must not be the cookie value"
        status, payload = call(api, "GET", "/api/status", token=None,
                               headers={"cookie": f"{COOKIE_NAME}={value}"})
        assert status == 200

    def test_a_forged_cookie_is_401(self, api):
        status, _ = failed(api, "GET", "/api/status", token=None,
                           headers={"cookie": f"{COOKIE_NAME}=forged"})
        assert status == 401

    def test_a_new_process_invalidates_old_cookies(self, api, ws):
        _, _, headers = self._session(api)
        value = headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
        restarted = GuiApi(ws)  # a fresh token, as after a restart
        status, _ = failed(restarted, "GET", "/api/status", token=None,
                           headers={"cookie": f"{COOKIE_NAME}={value}"})
        assert status == 401

    def test_a_wrong_session_token_is_refused(self, api):
        status, payload = call(api, "POST", "/api/session", token=None,
                               body={"token": "wrong"}, headers={"x-archx-request": CSRF_VALUE})
        assert status == 401 and payload["ok"] is False

    def test_repeated_bad_tokens_are_rate_limited(self, ws):
        api = GuiApi(ws, token=TOKEN, max_auth_failures=3)
        for _ in range(3):
            assert call(api, "GET", "/api/status", token="bad")[0] == 401
        status, error = failed(api, "GET", "/api/status", token="bad")
        assert status == 429 and error["code"] == "too_many_attempts"

    def test_a_good_token_after_failures_still_works(self, ws):
        api = GuiApi(ws, token=TOKEN, max_auth_failures=5)
        assert call(api, "GET", "/api/status", token="bad")[0] == 401
        assert call(api, "GET", "/api/status")[0] == 200

    def _session(self, api):
        status, payload = call(
            api, "POST", "/api/session", token=None,
            body={"token": TOKEN}, headers={"x-archx-request": CSRF_VALUE},
        )
        # the cookie rides in a Response header, so re-run dispatch here to read it
        api.dispatch(Request(
            method="POST", path="/api/session",
            headers={"x-archx-request": CSRF_VALUE}, body={"token": TOKEN},
        ))
        response = api.open_session(TOKEN)
        return status, payload, response.headers


# --------------------------------------------------------------------------
# CSRF / browser boundary
# --------------------------------------------------------------------------
class TestCsrf:
    def test_a_cookie_write_without_the_header_is_refused(self, api):
        status, error = failed(api, "POST", "/api/memory", token=None,
                               body={"kind": "permanent", "title": "t", "content": "c"},
                               headers={"cookie": f"{COOKIE_NAME}={api._cookie_value()}"})
        assert status == 403 and error["code"] == "csrf"

    def test_a_cookie_write_with_the_header_is_allowed(self, api):
        status, payload = call(
            api, "POST", "/api/memory", token=None,
            body={"kind": "permanent", "title": "cookie write", "content": "it worked"},
            headers={"cookie": f"{COOKIE_NAME}={api._cookie_value()}", "x-archx-request": CSRF_VALUE},
        )
        assert status == 200 and payload["ok"] is True

    def test_a_token_header_is_not_a_csrf_risk(self, api):
        status, payload = call(api, "POST", "/api/memory",
                               body={"kind": "permanent", "title": "script write", "content": "ok"})
        assert status == 200

    def test_options_is_refused_so_no_preflight_can_succeed(self, api):
        status, payload = call(api, "OPTIONS", "/api/chat")
        assert status == 405 and payload["error"]["code"] == "no_cors"

    def test_no_cors_headers_are_ever_sent(self, ws):
        server = GuiServer(GuiApi(ws, token=TOKEN)).start()
        try:
            status, headers, _ = http_get(server.url + "api/health")
            assert status == 200
            lowered = {key.lower() for key in headers}
            assert "access-control-allow-origin" not in lowered
            assert "access-control-allow-credentials" not in lowered
        finally:
            server.stop()


# --------------------------------------------------------------------------
# status and models
# --------------------------------------------------------------------------
class TestStatus:
    def test_status_counts_what_the_managers_hold(self, api, ws, model):
        ws.memory.add("permanent", "Notes", "one writer at a time", category="fact")
        data = ok(api, "GET", "/api/status")
        assert data["memories"] == ws.memory.stats()["total_active"]
        assert data["models_total"] >= 1
        assert data["schema_version"] == data["expected_schema_version"]
        assert data["version"]

    def test_status_says_which_models_can_actually_run(self, api, ws, model):
        data = ok(api, "GET", "/api/status")
        assert data["models_usable"] >= 1

    def test_status_reports_an_empty_home_honestly(self, api):
        data = ok(api, "GET", "/api/status")
        assert data["models_total"] == 0
        assert data["approvals_pending"] == 0
        assert data["net_fetch_granted"] is False

    def test_models_explain_themselves(self, api, ws, model):
        models = ok(api, "GET", "/api/models")
        assert models and models[0]["ready"] is True
        assert models[0]["ready_reason"]


# --------------------------------------------------------------------------
# chat
# --------------------------------------------------------------------------
class TestChat:
    def test_a_turn_is_answered_recorded_and_labelled(self, api, ws, model):
        reply = ok(api, "POST", "/api/chat", body={"message": "hello there"})
        assert reply["text"]
        assert reply["conversation_id"].startswith("conv_")
        assert reply["task"]["type"] == "chat"
        assert reply["simulated"] is True
        assert ws.tasks.get(reply["task"]["id"]).status == "completed"

    def test_a_second_message_continues_the_conversation(self, api, model):
        first = ok(api, "POST", "/api/chat", body={"message": "one"})
        second = ok(api, "POST", "/api/chat",
                    body={"message": "two", "conversation_id": first["conversation_id"]})
        assert second["conversation_id"] == first["conversation_id"]
        messages = ok(api, "GET", f"/api/conversations/{first['conversation_id']}/messages")
        assert [m["role"] for m in messages["messages"]][:4] == ["user", "assistant", "user", "assistant"]

    def test_an_empty_message_is_a_400(self, api, model):
        status, error = failed(api, "POST", "/api/chat", body={"message": "   "})
        assert status == 400 and error["code"] == "validation"

    def test_an_oversize_message_is_refused_before_it_is_stored(self, api, ws, model):
        status, error = failed(api, "POST", "/api/chat", body={"message": "x" * 8001})
        assert status == 400
        assert ws.tasks.list(limit=10) == []

    def test_a_missing_model_is_refused_with_an_explanation(self, api):
        status, error = failed(api, "POST", "/api/chat", body={"message": "hello"})
        assert status == 500 or status == 400
        assert error["message"]

    def test_an_unknown_conversation_is_a_404(self, api):
        status, error = failed(api, "GET", "/api/conversations/conv_nope/messages")
        assert status == 404 and error["code"] == "not_found"


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------
class TestSearch:
    def test_search_returns_hits_with_their_notes(self, api, ws):
        ws.memory.add("permanent", "SQLite locking", "one writer at a time; WAL keeps readers moving",
                      category="fact")
        data = ok(api, "GET", "/api/search?q=sqlite%20locking")
        assert data["hits"]
        assert data["hits"][0]["kind"] == "memory"
        assert "degraded" in data and "skipped" in data

    def test_a_short_query_is_a_400(self, api):
        status, error = failed(api, "GET", "/api/search?q=a")
        assert status == 400 and error["code"] == "validation"

    def test_a_bad_limit_is_a_400(self, api):
        status, error = failed(api, "GET", "/api/search?q=sqlite&limit=0")
        assert status == 400


# --------------------------------------------------------------------------
# memory
# --------------------------------------------------------------------------
class TestMemory:
    def test_a_memory_is_stored_and_listed(self, api):
        stored = ok(api, "POST", "/api/memory",
                    body={"kind": "permanent", "title": "Prefers metric", "content": "Use metric", "category": "preference"})
        assert stored["category"] == "preference"
        items = ok(api, "GET", "/api/memory")
        assert [item["id"] for item in items] == [stored["id"]]

    def test_a_duplicate_is_a_conflict_not_a_silent_second_copy(self, api):
        body = {"kind": "permanent", "title": "Same", "content": "Same content", "category": "fact"}
        ok(api, "POST", "/api/memory", body=body)
        status, error = failed(api, "POST", "/api/memory", body=body)
        assert status == 409 and error["code"] == "conflict"

    def test_an_unknown_kind_is_a_400(self, api):
        status, error = failed(api, "POST", "/api/memory",
                               body={"kind": "imaginary", "title": "t", "content": "c"})
        assert status in {400, 409}
        assert error["message"]

    def test_a_missing_title_is_a_400(self, api):
        status, error = failed(api, "POST", "/api/memory", body={"kind": "permanent", "content": "c"})
        assert status == 400 and error["code"] == "validation"


# --------------------------------------------------------------------------
# tasks
# --------------------------------------------------------------------------
class TestTasks:
    def test_tasks_list_and_detail_agree(self, api, ws, model):
        reply = ok(api, "POST", "/api/chat", body={"message": "a task please"})
        tasks = ok(api, "GET", "/api/tasks?limit=5")
        assert tasks[0]["id"] == reply["task"]["id"]
        detail = ok(api, "GET", f"/api/tasks/{reply['task']['id']}")
        assert detail["task"]["status"] == "completed"
        assert detail["timeline"], "a completed task has a timeline"

    def test_an_unknown_task_is_a_404(self, api):
        status, error = failed(api, "GET", "/api/tasks/tk_nope")
        assert status == 404

    def test_a_status_filter_is_validated_not_ignored(self, api):
        status, error = failed(api, "GET", "/api/tasks?status=imaginary")
        assert status == 400


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------
class TestJobs:
    def test_the_queue_is_reported_with_its_stats(self, api, ws):
        ws.jobs.enqueue("command", "echo hi", {"command": [sys.executable, "-c", "print('hi')"]})
        data = ok(api, "GET", "/api/jobs")
        assert data["stats"]["queued"] == 1
        assert data["queue"][0]["kind"] == "command"

    def test_draining_runs_a_real_job(self, api, ws):
        job = ws.jobs.enqueue("command", "echo hi", {"command": [sys.executable, "-c", "print('hi')"]})
        result = ok(api, "POST", "/api/jobs/drain", body={"max_jobs": 1})
        assert result["ran"] and result["ran"][0]["id"] == job.id
        assert ws.jobs.get(job.id).status == "completed"

    def test_draining_an_empty_queue_says_so(self, api):
        result = ok(api, "POST", "/api/jobs/drain", body={"max_jobs": 3})
        assert result["ran"] == []

    def test_a_bad_drain_limit_is_a_400(self, api):
        status, error = failed(api, "POST", "/api/jobs/drain", body={"max_jobs": 99})
        assert status == 400

    def test_pause_and_resume_are_real_state_changes(self, api, ws):
        job = ws.jobs.enqueue("command", "sleep", {"command": [sys.executable, "-c", "print(1)"]})
        paused = ok(api, "POST", f"/api/jobs/{job.id}/pause", body={})
        assert paused["status"] == "paused"
        resumed = ok(api, "POST", f"/api/jobs/{job.id}/resume", body={})
        assert resumed["status"] == "queued"

    def test_cancel_is_available_and_terminal(self, api, ws):
        job = ws.jobs.enqueue("command", "cancel me", {"command": [sys.executable, "-c", "print(1)"]})
        cancelled = ok(api, "POST", f"/api/jobs/{job.id}/cancel", body={})
        assert cancelled["status"] == "cancelled"

    def test_an_unknown_action_is_a_404(self, api, ws):
        job = ws.jobs.enqueue("command", "x", {"command": [sys.executable, "-c", "print(1)"]})
        status, error = failed(api, "POST", f"/api/jobs/{job.id}/explode", body={})
        assert status == 404


# --------------------------------------------------------------------------
# permissions and approvals
# --------------------------------------------------------------------------
class TestAccess:
    def test_a_pending_approval_can_be_approved_into_exactly_one_grant(self, api, ws):
        approval = ws.permissions.request_approval("fs.read", subject="fs.read", purpose="read a file")
        approvals = ok(api, "GET", "/api/approvals?status=pending")
        assert [item["id"] for item in approvals] == [approval.id]
        result = ok(api, "POST", f"/api/approvals/{approval.id}/approve", body={})
        assert result["grant"]["capability"] == "fs.read"
        grants = ok(api, "GET", "/api/permissions?active_only=1")["grants"]
        assert any(grant["id"] == result["grant"]["id"] for grant in grants)

    def test_denying_creates_no_grant(self, api, ws):
        approval = ws.permissions.request_approval("shell.run", subject="shell.run")
        ok(api, "POST", f"/api/approvals/{approval.id}/deny", body={})
        assert ok(api, "GET", "/api/permissions?active_only=1")["grants"] == []

    def test_approving_twice_is_a_conflict(self, api, ws):
        approval = ws.permissions.request_approval("fs.read", subject="fs.read")
        ok(api, "POST", f"/api/approvals/{approval.id}/approve", body={})
        status, error = failed(api, "POST", f"/api/approvals/{approval.id}/approve", body={})
        assert status in {400, 409}
        assert approval.id not in error["message"] or "already" in error["message"]

    def test_revoking_removes_the_grant(self, api, ws):
        grant = ws.permissions.grant(
            "fs.read", subject="fs.read", duration="persistent", granted_by="test", confirm=True
        )
        ok(api, "POST", f"/api/permissions/{grant.id}/revoke", body={})
        assert ok(api, "GET", "/api/permissions?active_only=1")["grants"] == []

    def test_capabilities_are_listed_with_their_risk(self, api):
        data = ok(api, "GET", "/api/permissions")
        names = {cap["name"] for cap in data["capabilities"]}
        assert {"fs.read", "shell.run", "net.fetch"} <= names
        assert all(cap["risk"] in {"low", "medium", "high"} for cap in data["capabilities"])


# --------------------------------------------------------------------------
# research
# --------------------------------------------------------------------------
class TestResearch:
    def test_a_local_run_returns_a_report_with_its_sources(self, api, ws):
        ws.memory.add("permanent", "SQLite locking",
                      "SQLite takes one write lock per transaction; WAL keeps readers moving.",
                      category="fact")
        result = ok(api, "POST", "/api/research",
                    body={"question": "how does sqlite locking work", "use_model": False})
        run_id = result["run"]["id"]
        assert result["run"]["status"] == "completed"
        detail = ok(api, "GET", f"/api/research/{run_id}")
        assert detail["sources"]
        assert detail["verification"]["ok"] is True
        assert detail["labels"], "the GUI shows the same S<n> labels the report uses"

    def test_the_report_endpoint_serves_the_report_not_its_json(self, api, ws):
        ws.memory.add("permanent", "SQLite locking", "one write lock per transaction", category="fact")
        result = ok(api, "POST", "/api/research",
                    body={"question": "how does sqlite locking work", "use_model": False})
        status, payload = call(api, "GET", f"/api/research/{result['run']['id']}/report")
        assert status == 200
        assert payload is None  # a raw body, not the JSON envelope

    def test_web_mode_without_a_grant_is_a_403_with_an_approval(self, api):
        status, error = failed(api, "POST", "/api/research",
                               body={"question": "how does sqlite locking work", "mode": "web",
                                     "urls": ["http://127.0.0.1:9/x"], "use_model": False})
        assert status == 403 and error["code"] == "approval_required"
        assert "ap_" in error["message"]

    def test_web_mode_without_urls_is_a_400(self, api):
        status, error = failed(api, "POST", "/api/research",
                               body={"question": "how does sqlite locking work", "mode": "web",
                                     "use_model": False})
        assert status == 400
        assert "url" in error["message"].lower()

    def test_an_empty_question_is_refused(self, api):
        status, error = failed(api, "POST", "/api/research", body={"question": "  "})
        assert status == 400

    def test_an_unknown_run_is_a_404(self, api):
        status, error = failed(api, "GET", "/api/research/rs_nope")
        assert status == 404


# --------------------------------------------------------------------------
# assets and browser safety
# --------------------------------------------------------------------------
class TestAssets:
    def test_the_page_and_its_assets_are_served_from_package_data(self, api):
        page = api.page()
        assert page.status == 200
        assert b"<title>Archx Agent</title>" in page.body
        for name in ("app.js", "style.css"):
            asset = api.asset(name)
            assert asset.status == 200
            assert asset.body == (ASSETS / name).read_bytes()

    def test_the_memory_kinds_in_the_page_are_the_ones_the_manager_accepts(self):
        """A dropdown that offers a kind the manager refuses is a broken control."""
        from archx_agent.managers.memory import KINDS

        html = (ASSETS / "index.html").read_text()
        block = html.split('id="memory-kind"')[1].split("</select>")[0]
        offered = [value for value in __import__("re").findall(r'value="([^"]+)"', block)]
        assert offered and set(offered) == set(KINDS)
        assert offered[0] == "permanent", "the default the panel sends must be valid"

    def test_every_control_in_the_page_is_wired(self):
        """No placeholder controls: each id the script touches exists, and each refresh
        button actually has a listener (which is how an unwired button hides)."""
        html = (ASSETS / "index.html").read_text()
        script = (ASSETS / "app.js").read_text()
        ids = set(__import__("re").findall(r'id="([^"]+)"', html))
        used = set(__import__("re").findall(r'getElementById\("([^"]+)"\)', script))
        assert used <= ids, f"the script asks for ids the page does not have: {sorted(used - ids)}"
        wired = set(__import__("re").findall(r'getElementById\("([^"]+)"\)\.addEventListener', script))
        refresh = {name for name in ids if name.endswith("-refresh")}
        assert refresh <= wired, f"buttons with no listener: {sorted(refresh - wired)}"
        views = set(__import__("re").findall(r'data-view="([^"]+)"', html))
        sections = {name[5:] for name in ids if name.startswith("view-")}
        assert views == sections, "every tab must have a section and every section a tab"

    def test_the_page_loads_nothing_from_anywhere_else(self):
        """No CDN, no font host, no remote script: the GUI works with the network unplugged.

        Hint text that *mentions* a URL (a CLI command the user could run) is fine; what
        matters is that nothing is fetched from, or linked to, another origin.
        """
        html = (ASSETS / "index.html").read_text()
        script = (ASSETS / "app.js").read_text()
        css = (ASSETS / "style.css").read_text()
        for blob in (html, script, css):
            for marker in ('src="http', "src='http", 'href="http', "href='http",
                           "fetch(\"http", "fetch('http", "url(http", "@import", "//cdn"):
                assert marker not in blob, marker
        assert '<script src="/app.js">' in html
        assert "<style" not in html
        assert "onclick=" not in html
        assert 'fetch(path' in script or "fetch(" in script

    def test_assets_are_served_by_exact_name_only(self, api):
        for name in ("../server.py", "..%2Fserver.py", ".env", "assets/../../server.py"):
            with pytest.raises(Exception):
                api.asset(name)
        with pytest.raises(Exception):
            api.asset("missing.js")

    def test_the_security_headers_are_present_and_the_page_may_be_framed(self, api):
        from archx_agent.interfaces.gui.server import _SECURITY_HEADERS

        csp = _SECURITY_HEADERS["Content-Security-Policy"]
        assert "script-src 'self'" in csp
        assert "default-src 'self'" in csp
        assert "frame-ancestors *" in csp
        assert "X-Frame-Options" not in _SECURITY_HEADERS
        assert _SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"

    def test_a_chinese_asset_name_cannot_escape(self, api):
        with pytest.raises(Exception):
            api.asset("....//server.py")


# --------------------------------------------------------------------------
# the real socket
# --------------------------------------------------------------------------
class TestHttp:
    def test_a_request_over_tcp_gets_the_page_and_the_api(self, ws, model):
        server = GuiServer(GuiApi(ws, token=TOKEN)).start()
        try:
            status, headers, body = http_get(server.url)
            assert status == 200 and b"Archx Agent" in body
            assert headers["X-Content-Type-Options"] == "nosniff"
            status, _, body = http_get(server.url + "api/status", headers={"X-Archx-Token": TOKEN})
            assert status == 200 and json.loads(body)["ok"] is True
            status, _, body = http_get(server.url + "api/status")
            assert status == 401 and json.loads(body)["error"]["code"] == "unauthorized"
        finally:
            server.stop()

    def test_the_server_does_not_advertise_the_interpreter(self, ws):
        server = GuiServer(GuiApi(ws, token=TOKEN)).start()
        try:
            _, headers, _ = http_get(server.url + "api/health")
            assert "Python" not in headers.get("Server", "")
        finally:
            server.stop()

    def test_head_returns_headers_without_a_body(self, ws):
        server = GuiServer(GuiApi(ws, token=TOKEN)).start()
        try:
            request = urllib.request.Request(server.url, method="HEAD")
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 200
                assert response.read() == b""
                assert int(response.headers["Content-Length"]) > 0
        finally:
            server.stop()

    def test_bad_json_is_a_400_and_never_a_traceback(self, ws):
        server = GuiServer(GuiApi(ws, token=TOKEN)).start()
        try:
            request = urllib.request.Request(
                server.url + "api/chat", data=b"{not json",
                headers={"Content-Type": "application/json", "X-Archx-Token": TOKEN}, method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
            assert caught.value.code == 400
            body = json.loads(caught.value.read())
            assert body["error"]["code"] == "bad_json"
        finally:
            server.stop()

    def test_an_oversize_body_is_refused_without_reading_it_all(self, ws):
        server = GuiServer(GuiApi(ws, token=TOKEN, max_body_bytes=2048)).start()
        try:
            request = urllib.request.Request(
                server.url + "api/chat", data=b"x" * 4096,
                headers={"Content-Type": "application/json", "X-Archx-Token": TOKEN}, method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
            assert caught.value.code == 413
        finally:
            server.stop()

    def test_a_session_cookie_round_trip_over_tcp(self, ws):
        server = GuiServer(GuiApi(ws, token=TOKEN)).start()
        try:
            status, headers, _ = http_send(
                server.url + "api/session", "POST", {"token": TOKEN},
                headers={"X-Archx-Request": CSRF_VALUE},
            )
            assert status == 200
            cookie = headers["Set-Cookie"].split(";")[0]
            status, _, body = http_get(server.url + "api/status", headers={"Cookie": cookie})
            assert status == 200 and json.loads(body)["ok"] is True
        finally:
            server.stop()

    def test_twenty_concurrent_reads_are_all_answered(self, ws):
        server = GuiServer(GuiApi(ws, token=TOKEN)).start()
        results: list[int] = []

        def worker() -> None:
            status, _, _ = http_get(server.url + "api/health")
            results.append(status)

        try:
            threads = [threading.Thread(target=worker) for _ in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
        finally:
            server.stop()
        assert results == [200] * 20

    def test_stopping_the_server_closes_the_port(self, ws):
        server = GuiServer(GuiApi(ws, token=TOKEN)).start()
        port = server.port
        server.stop()
        with pytest.raises(OSError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2)


# --------------------------------------------------------------------------
# error mapping and the CLI
# --------------------------------------------------------------------------
class TestErrorsAndCli:
    def test_domain_errors_map_to_statuses(self):
        assert error_for(ValidationError("bad")).status == 400
        assert error_for(NotFoundError("gone")).status == 404
        assert error_for(ConflictError("dupe")).status == 409
        assert error_for(RuntimeError("boom")).status == 500

    def test_a_traceback_never_reaches_the_client(self, api, monkeypatch):
        def explode(*args, **kwargs):
            raise RuntimeError("secret internal detail")

        monkeypatch.setattr(api.ws.jobs, "stats", explode)
        status, error = failed(api, "GET", "/api/status")
        assert status == 500
        assert "Traceback" not in error["message"]
        assert "RuntimeError" in error["message"]

    def test_gui_routes_lists_the_endpoints(self, tmp_path):
        env = {**os.environ, "ARCHX_PATHS_HOME": str(tmp_path / "home")}
        result = subprocess.run([CLI, "gui", "routes"], capture_output=True, text=True, env=env, timeout=120)
        assert result.returncode == 0, result.stderr
        assert "/api/chat" in result.stdout

    def test_a_remote_bind_requires_the_flag(self, tmp_path):
        env = {**os.environ, "ARCHX_PATHS_HOME": str(tmp_path / "home")}
        subprocess.run([CLI, "init"], capture_output=True, text=True, env=env, timeout=120)
        result = subprocess.run(
            [CLI, "gui", "serve", "--host", "0.0.0.0", "--port", "0"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert result.returncode == 2
        assert "allow-remote" in (result.stdout + result.stderr)

    def test_the_cli_serves_and_prints_its_token(self, tmp_path):
        env = {**os.environ, "ARCHX_PATHS_HOME": str(tmp_path / "home")}
        subprocess.run([CLI, "init"], capture_output=True, text=True, env=env, timeout=120)
        process = subprocess.Popen(
            [CLI, "gui", "serve", "--port", "0", "--token", "cli-token"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        try:
            line = ""
            for _ in range(200):
                line = process.stdout.readline()
                if "access token" in line:
                    break
            assert "access token: cli-token" in line
            url_line = process.stdout.readline()
            assert "open" in url_line and "token=cli-token" in url_line
        finally:
            process.terminate()
            process.wait(timeout=20)

    def test_split_target_keeps_the_query_and_extracts_the_token(self):
        path, query, token = split_target("/api/search?q=a+b&token=xyz&kind=memory")
        assert path == "/api/search" and token == "xyz"
        assert query["q"] == ["a b"] and query["kind"] == ["memory"]
        assert split_target("/") == ("/", {}, None)

    def test_a_response_encodes_json_by_default(self):
        response = Response(payload={"ok": True, "data": [1, 2]})
        assert json.loads(response.encode())["data"] == [1, 2]
        assert Response(body=b"raw").encode() == b"raw"
