"""Worker binding/credentials and bounded, race-safe training admission."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import http.client
import json
import threading

import pytest

from archx_agent.application.remote_worker import Worker, make_server
from archx_agent.application.remote_worker.policy import require_authenticated_bind
from archx_agent.application.remote_worker.protocol import WorkerBusy
from archx_agent.interfaces.cli.main import main
from tests.features.test_worker_safety import bundle_request


@contextmanager
def serving(worker):
    server = make_server(worker, port=0, request_timeout=0.2)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(server, method="GET", path="/health", token=None, body=None):
    client = http.client.HTTPConnection(*server.server_address, timeout=3)
    try:
        headers = {} if token is None else {"Authorization": "Bearer " + token}
        client.request(method, path, body=body, headers=headers)
        response = client.getresponse()
        return response.status, json.loads(response.read())
    finally:
        client.close()


@pytest.mark.parametrize("token", ["", " ", "a b", "a\n", "a\t", "é", "\0", "x" * 4097, 12, False])
def test_invalid_token_fails_before_workdir_creation(tmp_path, token):
    path = tmp_path / "not-created"
    with pytest.raises(ValueError, match="worker token"):
        Worker(token=token, workdir=str(path))
    assert not path.exists()


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.1", "localhost", "example.invalid", "", None])
def test_open_network_or_hostname_refused_before_socket_creation(tmp_path, monkeypatch, host):
    import archx_agent.application.remote_worker.http as transport
    worker = Worker(workdir=str(tmp_path))
    monkeypatch.setattr(transport, "ThreadingHTTPServer", lambda *a: pytest.fail("opened socket before policy"))
    with pytest.raises(ValueError):
        make_server(worker, host=host, port=0)


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1"])
def test_training_numeric_loopback_policy(host):
    require_authenticated_bind(host, token=None, allow_exec=False)
    with pytest.raises(ValueError, match="require a bearer token"):
        require_authenticated_bind(host, token=None, allow_exec=True)


def test_exec_without_token_cannot_listen(tmp_path, monkeypatch):
    import archx_agent.application.remote_worker.http as transport
    worker = Worker(allow_exec=True, workdir=str(tmp_path))
    monkeypatch.setattr(transport, "ThreadingHTTPServer", lambda *a: pytest.fail("opened socket"))
    with pytest.raises(ValueError, match="require a bearer token"):
        make_server(worker, port=0)


def test_authenticated_nonloopback_policy():
    for host in ["0.0.0.0", "::", "localhost", "example.invalid"]:
        require_authenticated_bind(host, token="secret", allow_exec=True)


def test_training_loopback_still_works_and_cannot_upgrade_to_open_exec(tmp_path):
    worker = Worker(workdir=str(tmp_path))
    with serving(worker) as server:
        status, payload = request(server)
        assert status == 200
        assert payload["capacity"] == {
            "running_jobs": 0, "retained_jobs": 0,
            "max_running_jobs": 4, "max_jobs": 128,
        }
        worker.allow_exec = True
        assert request(server)[0] == 401
        assert request(server, "POST", "/exec", body='{"command":"echo no"}')[0] == 401


def test_token_mutation_does_not_disable_auth_or_rotate_bound_credential(tmp_path):
    worker = Worker(token="original", workdir=str(tmp_path))
    with serving(worker) as server:
        worker.token = None
        assert request(server)[0] == 401
        assert request(server, token="original")[0] == 200
        worker.token = "replacement"
        assert request(server, token="replacement")[0] == 401
        assert request(server, token="original")[0] == 200


def test_auth_refusal_precedes_waiting_for_body_and_execution(tmp_path, monkeypatch):
    worker = Worker(token="secret", allow_exec=True, workdir=str(tmp_path))
    monkeypatch.setattr(worker, "execute", lambda *a: pytest.fail("unauthenticated execution"))
    with serving(worker) as server:
        client = http.client.HTTPConnection(*server.server_address, timeout=2)
        try:
            client.putrequest("POST", "/exec")
            client.putheader("Content-Length", "1000000")
            client.endheaders()  # Deliberately never send the promised body.
            response = client.getresponse()
            assert response.status == 401
            assert response.getheader("Connection") == "close"
            assert "secret" not in response.read().decode()
        finally:
            client.close()


@pytest.mark.parametrize("flag", ["max_jobs", "max_running_jobs"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2", None])
def test_limits_validate_before_creating_workdir(tmp_path, flag, value):
    path = tmp_path / "missing"
    with pytest.raises(ValueError, match="positive integer"):
        Worker(workdir=str(path), **{flag: value})
    assert not path.exists()


def block_training(worker, monkeypatch):
    release = threading.Event()
    finished = threading.Event()
    original = worker._run

    def blocked(job_id, bundle):
        try:
            assert release.wait(5), "test did not release training"
            original(job_id, bundle)
        finally:
            finished.set()
    monkeypatch.setattr(worker, "_run", blocked)
    return release, finished


def test_concurrent_admission_never_exceeds_one_slot(tmp_path, monkeypatch):
    worker = Worker(max_running_jobs=1, max_jobs=8, workdir=str(tmp_path))
    release, finished = block_training(worker, monkeypatch)
    def submit(_):
        try:
            return worker.accept(bundle_request())
        except WorkerBusy:
            return None
    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(submit, range(12)))
        assert sum(r is not None for r in results) == 1
        assert len(worker.jobs) == 1
    finally:
        release.set()
        assert finished.wait(3)


def test_finished_job_releases_running_slot_without_evicting_result(tmp_path, monkeypatch):
    worker = Worker(max_running_jobs=1, max_jobs=2, workdir=str(tmp_path))
    release, finished = block_training(worker, monkeypatch)
    try:
        first = worker.accept(bundle_request())
        with pytest.raises(WorkerBusy):
            worker.accept(bundle_request())
    finally:
        release.set()
        assert finished.wait(3)
    second = worker.accept(bundle_request())
    assert second["job_id"] != first["job_id"]
    assert worker.result(first["job_id"])["status"] == "completed"
    with pytest.raises(WorkerBusy, match="result capacity"):
        worker.accept(bundle_request())
    assert len(worker.jobs) == 2


def test_failed_training_releases_slot_and_retains_failure(tmp_path, monkeypatch):
    import archx_agent.application.remote_worker.worker as implementation
    worker = Worker(max_running_jobs=1, max_jobs=2, workdir=str(tmp_path))
    done = threading.Event()
    def fail(*a, **kw):
        raise ValueError("training failed")
    original = worker._run
    def run(*a):
        try:
            original(*a)
        finally:
            done.set()
    monkeypatch.setattr(implementation, "train_records", fail)
    monkeypatch.setattr(worker, "_run", run)
    first = worker.accept(bundle_request())
    assert done.wait(3)
    assert worker.result(first["job_id"])["status"] == "failed"
    worker.accept(bundle_request())
    assert len(worker.jobs) == 2


@pytest.mark.parametrize("stage", ["constructor", "start"])
def test_thread_start_failure_rolls_back_reserved_job(tmp_path, monkeypatch, stage):
    import archx_agent.application.remote_worker.worker as implementation
    worker = Worker(max_jobs=1, workdir=str(tmp_path))
    original = implementation.threading.Thread
    def fail(*a, **kw):
        raise RuntimeError("no threads")
    if stage == "constructor":
        monkeypatch.setattr(implementation.threading, "Thread", fail)
    else:
        monkeypatch.setattr(implementation.threading.Thread, "start", fail)
    with pytest.raises(WorkerBusy, match="could not start"):
        worker.accept(bundle_request())
    assert not worker.jobs
    # pytest restores the original thread machinery after this test.
    assert original is not None


def test_http_capacity_returns_429_without_new_job(tmp_path, monkeypatch):
    worker = Worker(token="secret", max_running_jobs=1, workdir=str(tmp_path))
    release, finished = block_training(worker, monkeypatch)
    try:
        with serving(worker) as server:
            body = json.dumps(bundle_request())
            assert request(server, "POST", "/jobs", "secret", body)[0] == 200
            status, payload = request(server, "POST", "/jobs", "secret", body)
            assert status == 429 and payload["status"] == "refused"
            assert len(worker.jobs) == 1
    finally:
        release.set()
        assert finished.wait(3)


@pytest.mark.parametrize("value", [None, "", "bad value"])
def test_cli_missing_or_invalid_env_refuses_without_serving(monkeypatch, capsys, value):
    import archx_agent.application.remote_worker as remote
    monkeypatch.setattr(remote, "serve", lambda **kw: pytest.fail("served invalid credentials"))
    if value is None:
        monkeypatch.delenv("WORKER_TEST_SECRET", raising=False)
    else:
        monkeypatch.setenv("WORKER_TEST_SECRET", value)
    assert main(["remote", "worker", "--allow-exec", "--token-env", "WORKER_TEST_SECRET"]) == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "bad value" not in captured.err


def test_cli_env_forwards_token_and_limits_without_echo(monkeypatch, capsys):
    import archx_agent.application.remote_worker as remote
    captured = {}
    monkeypatch.setenv("WORKER_TEST_SECRET", "private-value")
    monkeypatch.setattr(remote, "serve", lambda **kw: captured.update(kw))
    assert main(["remote", "worker", "--host", "0.0.0.0", "--allow-exec", "--token-env", "WORKER_TEST_SECRET", "--max-running-jobs", "2", "--max-jobs", "7"]) == 0
    assert captured["token"] == "private-value"
    assert captured["max_running_jobs"] == 2 and captured["max_jobs"] == 7
    output = capsys.readouterr()
    assert "private-value" not in output.out + output.err


def test_cli_open_exec_refuses_cleanly(capsys):
    assert main(["remote", "worker", "--allow-exec"]) == 2
    assert "require a bearer token" in capsys.readouterr().err


def test_cli_credentials_mutually_exclusive():
    with pytest.raises(SystemExit) as exc:
        main(["remote", "worker", "--token", "a", "--token-env", "B"])
    assert exc.value.code == 2


def test_capacity_snapshot_tracks_running_and_retained_jobs(tmp_path, monkeypatch):
    worker = Worker(max_running_jobs=2, max_jobs=3, workdir=str(tmp_path))
    release, finished = block_training(worker, monkeypatch)
    try:
        worker.accept(bundle_request())
        assert worker.capacity() == {
            "running_jobs": 1, "retained_jobs": 1,
            "max_running_jobs": 2, "max_jobs": 3,
        }
    finally:
        release.set()
        assert finished.wait(3)
    assert worker.capacity()["running_jobs"] == 0
    assert worker.capacity()["retained_jobs"] == 1
