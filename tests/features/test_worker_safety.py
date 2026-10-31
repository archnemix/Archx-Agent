"""Real worker HTTP/process/filesystem refusals and asynchronous artifact identity."""

from __future__ import annotations

import http.client
import json
import os
import shlex
import socket
import sys
import threading
import time

import pytest

from archx_agent.application.remote_worker import (
    Worker,
    WorkerRefusal,
    check_bundle,
    make_server,
)
from archx_agent.application.remote_worker.protocol import PROTOCOL, _canonical, _sha


@pytest.fixture
def worker(tmp_path):
    return Worker(
        name="safety", allow_exec=True, token="test-token", workdir=str(tmp_path)
    )


@pytest.fixture
def server(worker):
    httpd = make_server(worker, port=0, max_body_bytes=4096, request_timeout=0.15)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=3)


def raw_request(
    server,
    *,
    headers=b"",
    body=b"",
    method=b"POST",
    path=b"/exec",
    auth=True,
    eof=False,
):
    with socket.create_connection(server.server_address, timeout=3) as connection:
        connection.settimeout(3)
        token = b"Authorization: Bearer test-token\r\n" if auth else b""
        connection.sendall(
            method
            + b" "
            + path
            + b" HTTP/1.1\r\nHost: localhost\r\n"
            + token
            + headers
            + b"\r\n"
            + body
        )
        if eof:
            connection.shutdown(socket.SHUT_WR)
        response = http.client.HTTPResponse(connection)
        response.begin()
        return response.status, json.loads(response.read())


@pytest.mark.parametrize(
    "headers",
    [
        b"Content-Length: -1\r\n",
        b"Content-Length: nope\r\n",
        b"Content-Length: 9999999999999\r\n",
        b"Content-Length: 1, 1\r\n",
        b"Content-Length: 0\r\nContent-Length: 0\r\n",
        b"Transfer-Encoding: chunked\r\n",
        b"Transfer-Encoding: \r\nContent-Length: 0\r\n",
    ],
)
def test_bad_framing_refused_before_execution(server, worker, monkeypatch, headers):
    def forbidden(*args):
        pytest.fail("malformed request reached execution")

    monkeypatch.setattr(worker, "execute", forbidden)
    assert raw_request(server, headers=headers)[0] == 400


def test_oversized_body_refused_without_read(server):
    assert raw_request(server, headers=b"Content-Length: 4097\r\n")[0] == 413


def test_short_body_and_body_timeout_are_answers(server):
    assert (
        raw_request(server, headers=b"Content-Length: 8\r\n", body=b"{}", eof=True)[0]
        == 400
    )
    assert raw_request(server, headers=b"Content-Length: 8\r\n", body=b"{}")[0] == 408


@pytest.mark.parametrize(
    "body", [b"[]", b"null", b'"text"', b"8", b"\xff", b"{", b"[" * 1200 + b"]" * 1200]
)
def test_bad_json_and_nonobject_requests_are_answers(server, body):
    status, payload = raw_request(
        server, headers=f"Content-Length: {len(body)}\r\n".encode(), body=body
    )
    assert status == 400 and "error" in payload


@pytest.mark.parametrize(
    "headers",
    [
        b"",
        b"Authorization: Bearer wrong\r\n",
        b"Authorization: Bearer \xff\r\n",
        b"Authorization: Bearer test-token\r\nAuthorization: Bearer test-token\r\n",
    ],
)
def test_authentication_is_checked_before_body_read(server, headers):
    status, _ = raw_request(
        server, headers=headers + b"Content-Length: 4000\r\n", auth=False
    )
    assert status == 401


@pytest.mark.parametrize("path", [b"/files-extra", b"/jobs/", b"/jobs/id/extra"])
def test_only_exact_routes_match(server, path):
    assert raw_request(server, method=b"GET", path=path)[0] == 404


def test_invalid_target_and_file_root_are_refused(server):
    assert raw_request(server, method=b"GET", path=b"http://[bad")[0] == 400
    assert (
        raw_request(server, method=b"GET", path=b"/files?root=../../outside")[0] == 403
    )


def test_optional_token_policy_remains_explicit(tmp_path):
    worker = Worker(allow_exec=False, workdir=str(tmp_path))
    httpd = make_server(worker, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        assert raw_request(httpd, method=b"GET", path=b"/health", auth=False)[0] == 200
        assert raw_request(httpd, auth=False)[0] == 403  # execution still opt-in
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize("timeout", [0, -1, True, 1.5, "3", None])
def test_execution_limit_refusal_has_no_process_effect(worker, timeout):
    answer = worker.execute({"command": "echo should-not-run", "timeout": timeout})
    assert "refused" in answer


@pytest.mark.parametrize("command", [None, [], {}, 5, "", "\0"])
def test_execution_command_types_refused(worker, command):
    assert "refused" in worker.execute({"command": command})


def test_execution_output_spools_and_reports_truncation(worker):
    command = shlex.join(
        [
            sys.executable,
            "-c",
            "import sys; print('x'*1000000);sys.stderr.write('e'*1000000)",
        ]
    )
    answer = worker.execute({"command": command})
    assert answer["exit_code"] == 0 and answer["truncated"]
    assert len(answer["stdout"]) == len(answer["stderr"]) == 65536


@pytest.mark.skipif(os.name != "posix", reason="POSIX group cleanup")
def test_worker_timeout_terminates_its_shell_descendants(worker):
    marker = worker.workdir / "escaped"
    child = f"import time,pathlib;time.sleep(2);pathlib.Path({str(marker)!r}).write_text('escaped')"
    parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(20)"
    answer = worker.execute(
        {"command": shlex.join([sys.executable, "-c", parent]), "timeout": 1}
    )
    assert answer["timed_out"] and answer["exit_code"] is None
    time.sleep(2)
    assert not marker.exists()


@pytest.mark.parametrize(
    "files",
    [
        [],
        None,
        {"x": 8},
        {"": "x"},
        {"a": "ok", "z/../../escape": "bad"},
        {"a": "file", "a/b": "child"},
        {"a/b": "child", "a": "file"},
        {"x": "\ud800"},
    ],
)
def test_invalid_file_batch_is_preflighted_before_writes(worker, files):
    assert "refused" in worker.write_files({"files": files})
    assert not (worker.workdir / "project").exists()


def test_push_and_pull_file_byte_and_aggregate_limits(worker, monkeypatch):
    import archx_agent.application.remote_worker.files as files

    monkeypatch.setattr(files, "MAX_FILE_BYTES", 8)
    monkeypatch.setattr(files, "MAX_TRANSFER_BYTES", 12)
    assert "refused" in worker.write_files({"files": {"one": "x" * 9}})
    assert "refused" in worker.write_files({"files": {"one": "x" * 8, "two": "y" * 8}})
    assert not (worker.workdir / "project").exists()
    root = worker.workdir / "project"
    root.mkdir()
    (root / "one").write_text("x" * 9)
    assert "refused" in worker.list_files()
    (root / "one").write_text("x" * 8)
    (root / "two").write_text("y" * 8)
    assert "refused" in worker.list_files()


def test_file_count_and_scan_limits_are_not_silent_truncation(worker, monkeypatch):
    import archx_agent.application.remote_worker.files as files

    monkeypatch.setattr(files, "MAX_FILES", 1)
    assert "refused" in worker.write_files({"files": {"a": "a", "b": "b"}})
    root = worker.workdir / "project"
    root.mkdir()
    (root / "a").write_text("a")
    (root / "b").write_text("b")
    assert "refused" in worker.list_files()
    monkeypatch.setattr(files, "MAX_SCAN_ENTRIES", 1)
    assert "refused" in worker.list_files()


def test_outside_symlink_never_leaks_content(worker, tmp_path):
    root = worker.workdir / "project"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("must-not-leak")
    (root / "linked.txt").symlink_to(outside)
    answer = worker.list_files()
    assert "refused" in answer and "must-not-leak" not in str(answer)


def test_text_pull_rejects_invalid_utf8_and_does_not_create_missing_roots(worker):
    assert worker.list_files("missing")["files"] == []
    assert not (worker.workdir / "missing").exists()
    root = worker.workdir / "project"
    root.mkdir()
    (root / "binary").write_bytes(b"\xff")
    assert "refused" in worker.list_files()


def bundle_request():
    text = "one two one"
    digest = _sha(text)
    entry = {
        "path": "x.txt",
        "text": text,
        "split": "train",
        "file_sha256": digest,
        "text_sha256": digest,
        "file_bytes": len(text),
    }
    bundle = {
        "dataset": {
            "id": "ds_test",
            "entries": [entry],
            "manifest_checksum": _sha(f"train\t{digest}\t{len(text)}\tx.txt"),
        },
        "run": {"method": "ngram", "order": 2, "smoothing": 1.0, "seed": 7},
    }
    return {
        "protocol": PROTOCOL,
        "bundle": bundle,
        "bundle_sha256": _sha(_canonical(bundle)),
    }


@pytest.mark.parametrize(
    "where,value",
    [
        ("dataset", []),
        ("run", []),
        ("entries", "bad"),
        ("entries", [None]),
        ("entries", [{"path": "x", "text": 7}]),
    ],
)
def test_malformed_bundle_shapes_are_domain_refusals(where, value):
    request = bundle_request()
    if where == "entries":
        request["bundle"]["dataset"]["entries"] = value
    else:
        request["bundle"][where] = value
    request["bundle_sha256"] = _sha(_canonical(request["bundle"]))
    with pytest.raises(WorkerRefusal):
        check_bundle(request)


def test_completed_artifact_is_bound_to_accepted_input_without_stamp_race(
    worker, monkeypatch
):
    import archx_agent.application.remote_worker.worker as implementation

    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original_train = implementation.train_records
    original_run = Worker._run

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original_train(*args, **kwargs)

    def run_and_signal(self, *args):
        try:
            original_run(self, *args)
        finally:
            finished.set()

    monkeypatch.setattr(implementation, "train_records", delayed)
    monkeypatch.setattr(Worker, "_run", run_and_signal)
    request = bundle_request()
    identity = request["bundle_sha256"]
    accepted = worker.accept(request)
    try:
        assert started.wait(3)
        worker.stamp(
            accepted["job_id"], identity
        )  # formerly a no-op before artifact existed
        request["bundle"]["dataset"]["id"] = "changed-by-caller"
        request["bundle"]["run"]["seed"] = 999
    finally:
        release.set()
    assert finished.wait(5)
    result = worker.result(accepted["job_id"])
    assert result["status"] == "completed", result.get("error")
    assert result["artifact"]["bundle_sha256"] == identity
    assert (
        result["artifact"]["trained_on"] == "ds_test"
        and result["artifact"]["seed"] == 7
    )
    assert result["artifact_sha256"] == _sha(_canonical(result["artifact"]))
    with pytest.raises(WorkerRefusal):
        worker.stamp(accepted["job_id"], "forged-identity")
