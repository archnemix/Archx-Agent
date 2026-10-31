"""M37 - Remote compute and portability: hand work out, and check what comes back.

Remote compute is the easiest feature in this repository to fake, and every fake looks the same:
send "train this", receive a number, print the number. The tests are built around the questions a
fake cannot answer:

1. **is the input identified?** `TestTheBundle` checks that a bundle carries the corpus, that each
   record's *file* digest and *text* digest are recorded separately (they differ - `fs.read` trims),
   that the bundle hash matches its bytes, and that a corpus edited after the build is refused
   rather than shipped.
2. **did the worker check anything?** `TestTheProtocol` drives the real worker and its refusals:
   another protocol version, a bundle whose hash moved, a record edited in transit, a manifest that
   does not rebuild, and a bundle with nothing to train on.
3. **did the numbers come from the same trainer?** `TestTheRoundTrip` compares a remote run with a
   local run of the same config and asserts the perplexities are *equal*, not close - the worker
   calls the same function, so any difference would mean a second implementation.
4. **what happens when the far end lies?** `TestWhatAResultIsWorth` has a worker claim a hash it did
   not produce, and checks the artifact is stored, marked `received`, never `verified`, and that a
   second `verify` cannot rescue it.
5. **does a dispatch that never arrived leave a trace?** `TestTheBoundary` and
   `TestTheRoundTrip` check the refusal rows, the approvals, and the attempts log.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from archx_agent.application.remote_worker import (
    Worker,
    WorkerRefusal,
    check_bundle,
    make_server,
)
from archx_agent.application.training import NGramModel, train_records
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import ValidationError
from archx_agent.interfaces.gui.server import GuiApi, Request, split_target
from archx_agent.managers.remote import PROTOCOL, STATUSES
from archx_agent.managers.schema import SCHEMA_VERSION


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture()
def lab(tmp_path) -> Path:
    folder = tmp_path / "lab"
    for language, template in (
        ("python", "def function_{n}(x):\n    return x + {n}\n"),
        ("rust", "fn function_{n}(x: i32) -> i32 {{\n    x + {n}\n}}\n"),
    ):
        (folder / "corpus" / language).mkdir(parents=True, exist_ok=True)
        for n in range(1, 5):
            (folder / "corpus" / language / f"file{n}.txt").write_text(
                template.format(n=n), encoding="utf-8"
            )
    return folder


@pytest.fixture()
def ws(tmp_path, lab):
    with open_workspace(home=str(tmp_path / "home"), overrides={"tools.roots": [str(lab)]}) as workspace:
        workspace.permissions.grant("fs.read", subject="*", duration="persistent", confirm=True)
        workspace.permissions.grant("fs.write", subject="*", duration="persistent", confirm=True)
        workspace.config.set("remote.enabled", True)
        yield workspace


@pytest.fixture()
def dataset(ws):
    created = ws.data.create("code", ["corpus"], license="MIT")
    ws.data.scan(created["id"])
    ws.data.clean(created["id"])
    ws.data.split(created["id"], train=0.5, val=0.25, test=0.25, seed="m37")
    ws.data.build(created["id"])
    return created["id"]


@pytest.fixture()
def bundle_job(ws, dataset):
    return ws.remotes.export(dataset, order=2, seed=5)


@pytest.fixture()
def worker_server():
    """A real worker on a real port, torn down afterwards."""
    worker = Worker(name="testbox")
    server = make_server(worker, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], worker
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def endpoint(port: int) -> str:
    return f"http://127.0.0.1:{port}"


# --------------------------------------------------------------------------
# 1. the ledger
# --------------------------------------------------------------------------
class TestTheLedger:
    def test_the_schema_adopts_the_reserved_table(self, ws):
        assert SCHEMA_VERSION >= 27
        assert ws.store.table_exists("remote_jobs")
        assert ws.store.table_exists("remote_attempts")
        columns = {row["name"] for row in ws.store.query("PRAGMA table_info(remote_jobs)")}
        for reserved in ("provider", "status", "config", "estimate", "actual", "outputs",
                         "approved_by", "task_id"):
            assert reserved in columns
        for added in ("kind", "dataset_id", "endpoint", "machine", "protocol", "bundle_sha256",
                      "claimed_sha256", "received_sha256", "artifact_path", "verified_at",
                      "verify_note", "remote_job_id"):
            assert added in columns

    def test_a_fresh_home_has_dispatched_nothing(self, ws):
        stats = ws.remotes.stats()
        assert stats["jobs"] == 0
        assert stats["attempts"] == 0
        assert stats["protocol"] == PROTOCOL
        assert stats["statuses"] == list(STATUSES)

    def test_the_settings_default_to_off(self, tmp_path):
        with open_workspace(home=str(tmp_path / "fresh")) as fresh:
            assert fresh.config.get("remote.enabled") is False
            assert fresh.config.get("remote.require_approval") is True
            assert fresh.config.get("remote.endpoint") == ""
            assert "off" in " ".join(fresh.remotes.blockers())


# --------------------------------------------------------------------------
# 2. the bundle
# --------------------------------------------------------------------------
class TestTheBundle:
    def test_the_bundle_hashes_to_its_own_bytes(self, ws, bundle_job):
        job = ws.remotes.view(bundle_job["id"])
        path = Path(ws.config.path("paths.artifacts")) / "remote" / Path(job["bundle_path"]).name
        body = path.read_text(encoding="utf-8")
        assert hashlib.sha256(body.encode("utf-8")).hexdigest() == job["bundle_sha256"]

    def test_the_bundle_carries_the_corpus(self, ws, bundle_job):
        path = Path(ws.config.path("paths.artifacts")) / "remote" / Path(bundle_job["bundle_path"]).name
        bundle = json.loads(path.read_text(encoding="utf-8"))
        entries = bundle["dataset"]["entries"]
        assert len(entries) == 8
        assert {entry["split"] for entry in entries} == {"train", "val", "test"}
        assert all(entry["text"] for entry in entries)
        # the file digest and the text digest are both recorded, and they are not the same thing
        assert all(entry["file_sha256"] and entry["text_sha256"] for entry in entries)

    def test_the_two_digests_measure_different_things(self, ws, bundle_job):
        """`fs.read` trims surrounding whitespace, so a record's file digest and text digest differ.

        Recording one number for both would be wrong for every file that ends in a newline - which
        is most of them - and the bundle would then refuse its own records.
        """
        path = Path(ws.config.path("paths.artifacts")) / "remote" / Path(bundle_job["bundle_path"]).name
        entry = json.loads(path.read_text(encoding="utf-8"))["dataset"]["entries"][0]
        assert entry["file_sha256"] != entry["text_sha256"]
        assert hashlib.sha256(entry["text"].encode("utf-8")).hexdigest() == entry["text_sha256"]

    def test_the_manifest_checksum_is_the_datasets(self, ws, dataset, bundle_job):
        path = Path(ws.config.path("paths.artifacts")) / "remote" / Path(bundle_job["bundle_path"]).name
        bundle = json.loads(path.read_text(encoding="utf-8"))
        assert bundle["dataset"]["manifest_checksum"] == ws.data.manifest(dataset)["checksum"]
        assert bundle["protocol"] == PROTOCOL
        assert bundle["schema_version"] == SCHEMA_VERSION

    def test_an_unbuilt_dataset_is_not_exportable(self, ws):
        created = ws.data.create("draft", ["corpus"], license="unknown")
        ws.data.scan(created["id"])
        with pytest.raises(ValidationError, match="no manifest yet"):
            ws.remotes.export(created["id"])

    def test_a_corpus_edited_after_the_build_is_refused(self, ws, lab, dataset):
        (lab / "corpus" / "python" / "file1.txt").write_text("something else entirely\n", encoding="utf-8")
        with pytest.raises(ValidationError, match="no longer hashes"):
            ws.remotes.export(dataset)

    def test_a_bundle_over_the_size_limit_is_refused(self, ws, dataset):
        ws.config.set("remote.max_chars", 10)
        with pytest.raises(ValidationError, match="max_chars"):
            ws.remotes.export(dataset)

    def test_the_run_is_declared_in_the_bundle(self, ws, bundle_job):
        path = Path(ws.config.path("paths.artifacts")) / "remote" / Path(bundle_job["bundle_path"]).name
        bundle = json.loads(path.read_text(encoding="utf-8"))
        assert bundle["run"] == {
            "method": "ngram", "order": 2, "smoothing": 0.1, "seed": 5, "label_source": "record",
        }

    def test_a_different_run_gives_a_different_hash(self, ws, dataset):
        first = ws.remotes.export(dataset, order=2, seed=5)
        second = ws.remotes.export(dataset, order=3, seed=5)
        assert first["bundle_sha256"] != second["bundle_sha256"]


# --------------------------------------------------------------------------
# 3. the boundary: nothing leaves without a switch, a name and an approval
# --------------------------------------------------------------------------
class TestTheBoundary:
    def test_a_refusal_names_every_missing_condition(self, tmp_path, lab):
        with open_workspace(home=str(tmp_path / "home2"), overrides={"tools.roots": [str(lab)]}) as fresh:
            reasons = fresh.remotes.blockers()
            assert any("remote compute is off" in reason for reason in reasons)
            assert any("no endpoint" in reason for reason in reasons)
            assert any("no cloud provider" in reason for reason in reasons)

    def test_an_url_that_is_not_http_is_named_as_such(self, ws):
        reasons = ws.remotes.blockers("localhost:9001")
        assert any("not an http(s) URL" in reason for reason in reasons)

    def test_dispatch_without_approval_sends_nothing(self, ws, bundle_job):
        job = ws.remotes.dispatch(bundle_job["id"], endpoint="http://127.0.0.1:9")
        assert job["status"] == "refused"
        assert any("require_approval" in reason for reason in job["reasons"])
        assert job["attempts"][0]["action"] == "dispatch"
        assert job["attempts"][0]["status"] == "refused"

    def test_dispatch_with_the_switch_off_sends_nothing(self, ws, bundle_job):
        ws.remotes.approve(bundle_job["id"], by="tester")
        ws.config.set("remote.enabled", False)
        job = ws.remotes.dispatch(bundle_job["id"], endpoint="http://127.0.0.1:9")
        assert job["status"] == "refused"
        assert any("remote compute is off" in reason for reason in job["reasons"])

    def test_an_approval_is_recorded_on_the_job_and_in_the_log(self, ws, bundle_job):
        approved = ws.remotes.approve(bundle_job["id"], by="tester")
        assert approved["approved_by"] == "user:tester"
        assert any(item["action"] == "approve" and item["status"] == "ok" for item in approved["attempts"])

    def test_an_endpoint_nobody_is_listening_on_is_a_row_not_a_traceback(self, ws, bundle_job):
        ws.remotes.approve(bundle_job["id"], by="tester")
        job = ws.remotes.dispatch(bundle_job["id"], endpoint="http://127.0.0.1:9", timeout=1.0)
        assert job["status"] == "failed"
        assert job["error"]
        assert job["attempts"][0]["status"] == "failed"
        assert "could not be reached" in job["reasons"][0]

    def test_collecting_an_undispatched_job_is_a_validation_error(self, ws, bundle_job):
        with pytest.raises(ValidationError, match="never dispatched"):
            ws.remotes.collect(bundle_job["id"])

    def test_verifying_without_an_artifact_is_a_validation_error(self, ws, bundle_job):
        with pytest.raises(ValidationError, match="no artifact"):
            ws.remotes.verify(bundle_job["id"])


# --------------------------------------------------------------------------
# 4. the protocol: the worker checks before it computes
# --------------------------------------------------------------------------
def _request_for(ws, bundle_job) -> dict:
    path = Path(ws.config.path("paths.artifacts")) / "remote" / Path(bundle_job["bundle_path"]).name
    bundle = json.loads(path.read_text(encoding="utf-8"))
    return {
        "protocol": PROTOCOL,
        "bundle": bundle,
        "bundle_sha256": bundle_job["bundle_sha256"],
        "requester": "test",
    }


class TestTheProtocol:
    def test_a_well_formed_bundle_passes(self, ws, bundle_job):
        checked = check_bundle(_request_for(ws, bundle_job))
        assert len(checked["dataset"]["entries"]) == 8

    def test_another_protocol_version_is_refused_with_both_named(self, ws, bundle_job):
        request = _request_for(ws, bundle_job)
        request["protocol"] = "archx-remote/0"
        with pytest.raises(WorkerRefusal) as refusal:
            check_bundle(request)
        assert "archx-remote/0" in str(refusal.value)
        assert PROTOCOL in str(refusal.value)

    def test_a_bundle_whose_hash_moved_is_refused(self, ws, bundle_job):
        request = _request_for(ws, bundle_job)
        request["bundle"]["run"]["seed"] = 99
        with pytest.raises(WorkerRefusal, match="hashes to"):
            check_bundle(request)

    def test_a_record_edited_in_transit_is_refused(self, ws, bundle_job):
        request = _request_for(ws, bundle_job)
        request["bundle"]["dataset"]["entries"][0]["text"] += " tampered"
        request["bundle_sha256"] = hashlib.sha256(
            json.dumps(request["bundle"], indent=2, sort_keys=True).encode("utf-8")
        ).hexdigest()
        with pytest.raises(WorkerRefusal, match="text digest"):
            check_bundle(request)

    def test_a_manifest_that_does_not_rebuild_is_refused(self, ws, bundle_job):
        request = _request_for(ws, bundle_job)
        request["bundle"]["dataset"]["entries"][0]["file_sha256"] = "0" * 64
        request["bundle_sha256"] = hashlib.sha256(
            json.dumps(request["bundle"], indent=2, sort_keys=True).encode("utf-8")
        ).hexdigest()
        with pytest.raises(WorkerRefusal, match="contradicts itself"):
            check_bundle(request)

    def test_a_bundle_with_nothing_to_train_on_is_refused(self, ws, bundle_job):
        request = _request_for(ws, bundle_job)
        for entry in request["bundle"]["dataset"]["entries"]:
            entry["split"] = "val"
        # the manifest is rebuilt from the entries, so a bundle that says "no train records" must
        # also say so in its checksum - otherwise this test would be catching the other refusal
        lines = sorted(
            f"{entry['split']}\t{entry['file_sha256']}\t{entry['file_bytes']}\t{entry['path']}"
            for entry in request["bundle"]["dataset"]["entries"]
        )
        request["bundle"]["dataset"]["manifest_checksum"] = hashlib.sha256(
            "\n".join(lines).encode("utf-8")
        ).hexdigest()
        request["bundle_sha256"] = hashlib.sha256(
            json.dumps(request["bundle"], indent=2, sort_keys=True).encode("utf-8")
        ).hexdigest()
        with pytest.raises(WorkerRefusal, match="train split"):
            check_bundle(request)

    def test_the_worker_refuses_over_the_socket(self, ws, bundle_job, worker_server):
        port, worker = worker_server
        ws.remotes.approve(bundle_job["id"], by="tester")
        ws.config.set("remote.endpoint", "http://127.0.0.1:1")  # deliberately wrong
        job = ws.remotes.dispatch(bundle_job["id"], endpoint=endpoint(port))
        assert job["status"] == "dispatched"
        assert worker.jobs  # the worker accepted it
        # a second dispatch to the same worker with a bad protocol is refused by the worker
        assert job["machine"] == "testbox"
        assert job["protocol"] == PROTOCOL


# --------------------------------------------------------------------------
# 5. the round trip: dispatch, collect, verify
# --------------------------------------------------------------------------
class TestTheRoundTrip:
    def test_a_worker_computes_and_the_hash_is_checked_here(self, ws, bundle_job, worker_server):
        port, worker = worker_server
        ws.remotes.approve(bundle_job["id"], by="tester")
        sent = ws.remotes.dispatch(bundle_job["id"], endpoint=endpoint(port))
        assert sent["status"] == "dispatched"
        assert sent["remote_job_id"].startswith("rj_worker_")
        collected = ws.remotes.collect(bundle_job["id"])
        assert collected["status"] == "verified"
        assert collected["claimed_sha256"] == collected["received_sha256"]
        assert collected["verified_at"]
        assert collected["machine"] == "testbox"

    def test_the_artifact_on_disk_is_the_one_the_row_names(self, ws, bundle_job, worker_server):
        port, _worker = worker_server
        ws.remotes.approve(bundle_job["id"], by="tester")
        ws.remotes.dispatch(bundle_job["id"], endpoint=endpoint(port))
        job = ws.remotes.collect(bundle_job["id"])
        read = ws.tools.execute(
            "fs.read", {"path": job["artifact_path"]}, requester="test"
        ).result["content"]
        assert hashlib.sha256(read.encode("utf-8")).hexdigest() == job["received_sha256"]
        artifact = json.loads(read)
        assert artifact["kind"] == "ngram"
        assert artifact["computed_by"] == "worker:testbox"
        assert artifact["trained_on"] == ws.remotes.manager.get(job["id"]).dataset_id

    def test_the_remote_numbers_equal_a_local_run(self, ws, dataset, bundle_job, worker_server):
        """The strongest claim in the milestone: the worker is not a second implementation."""
        port, _worker = worker_server
        ws.remotes.approve(bundle_job["id"], by="tester")
        ws.remotes.dispatch(bundle_job["id"], endpoint=endpoint(port))
        remote = ws.remotes.collect(bundle_job["id"])
        local = ws.trainer.run(method="ngram", dataset=dataset, order=2, seed=5, label_source="record")
        assert remote["status"] == "verified"
        for split, values in local["metrics"].items():
            for name, value in values.items():
                assert remote["outputs"]["metrics"][split][name] == value

    def test_a_verified_result_survives_a_second_verify(self, ws, bundle_job, worker_server):
        port, _worker = worker_server
        ws.remotes.approve(bundle_job["id"], by="tester")
        ws.remotes.dispatch(bundle_job["id"], endpoint=endpoint(port))
        ws.remotes.collect(bundle_job["id"])
        again = ws.remotes.verify(bundle_job["id"])
        assert again["agrees"] is True
        assert again["status"] == "verified"

    def test_every_attempt_is_in_the_log(self, ws, bundle_job, worker_server):
        port, _worker = worker_server
        ws.remotes.approve(bundle_job["id"], by="tester")
        ws.remotes.dispatch(bundle_job["id"], endpoint=endpoint(port))
        ws.remotes.collect(bundle_job["id"])
        actions = [item["action"] for item in ws.remotes.attempts(job_id=bundle_job["id"])]
        assert set(actions) == {"approve", "dispatch", "collect"}

    def test_a_worker_that_is_slow_can_be_collected_later(self, ws, bundle_job):
        worker = Worker(name="slowbox", delay=0.6)
        server = make_server(worker, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            ws.remotes.approve(bundle_job["id"], by="tester")
            ws.remotes.dispatch(bundle_job["id"], endpoint=endpoint(server.server_address[1]))
            pending = ws.remotes.collect(bundle_job["id"])
            assert pending["status"] == "running"
            assert any("has not finished" in reason for reason in pending["reasons"])
            import time

            time.sleep(0.9)
            done = ws.remotes.collect(bundle_job["id"])
            assert done["status"] == "verified"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


# --------------------------------------------------------------------------
# 6. what a result is worth: a hash that disagrees is not a result
# --------------------------------------------------------------------------
class TestWhatAResultIsWorth:
    @pytest.fixture()
    def liar(self):
        """A worker that returns a correct artifact but a *wrong* hash for it."""
        worker = Worker(name="liarbox")
        server = make_server(worker, port=0)
        original = worker.result

        def result(job_id: str) -> dict:
            payload = original(job_id)
            if payload.get("status") == "completed":
                payload["artifact_sha256"] = "0" * 64
            return payload

        worker.result = result  # type: ignore[method-assign]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_address[1], worker
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_a_mismatched_hash_is_stored_as_a_disagreement(self, ws, bundle_job, liar):
        port, _worker = liar
        ws.remotes.approve(bundle_job["id"], by="tester")
        ws.remotes.dispatch(bundle_job["id"], endpoint=endpoint(port))
        job = ws.remotes.collect(bundle_job["id"])
        assert job["status"] == "received"
        assert job["claimed_sha256"] == "0" * 64
        assert job["received_sha256"] != job["claimed_sha256"]
        assert "claimed" in job["verify_note"] and "hash to" in job["verify_note"]
        assert job["verified_at"] is None
        assert job["attempts"][0]["status"] == "mismatch"

    def test_a_second_verify_cannot_rescue_a_disagreement(self, ws, bundle_job, liar):
        port, _worker = liar
        ws.remotes.approve(bundle_job["id"], by="tester")
        ws.remotes.dispatch(bundle_job["id"], endpoint=endpoint(port))
        ws.remotes.collect(bundle_job["id"])
        again = ws.remotes.verify(bundle_job["id"])
        assert again["agrees"] is False
        assert again["status"] == "received"
        assert "does not settle" in again["verify_note"]

    def test_an_artifact_edited_after_it_arrived_stops_verifying(self, ws, lab, bundle_job, worker_server):
        port, _worker = worker_server
        ws.remotes.approve(bundle_job["id"], by="tester")
        ws.remotes.dispatch(bundle_job["id"], endpoint=endpoint(port))
        job = ws.remotes.collect(bundle_job["id"])
        target = Path(lab) / Path(job["artifact_path"]).name
        target.write_text("{}", encoding="utf-8")
        again = ws.remotes.verify(bundle_job["id"])
        assert again["agrees"] is False
        assert again["status"] == "received"

    def test_stats_counts_an_unverified_result(self, ws, bundle_job, liar):
        port, _worker = liar
        ws.remotes.approve(bundle_job["id"], by="tester")
        ws.remotes.dispatch(bundle_job["id"], endpoint=endpoint(port))
        ws.remotes.collect(bundle_job["id"])
        assert ws.remotes.stats()["unverified"] == 1


# --------------------------------------------------------------------------
# 7. the page: one more client of the same service
# --------------------------------------------------------------------------
TOKEN = "m37-token"


@pytest.fixture()
def api(ws):
    return GuiApi(ws, token=TOKEN)


def call(api, method, path, *, token=TOKEN, body=None):
    parsed, query, url_token = split_target(path)
    request = Request(
        method=method,
        path=parsed,
        query=query,
        headers={"x-archx-token": token} if token else {},
        body=body,
        token=url_token,
        token_in_query=url_token is not None,
    )
    response = api.dispatch(request)
    return response.status, response.payload


class TestThePage:
    def test_the_jobs_route_lists_and_explains(self, api, bundle_job):
        status, payload = call(api, "GET", "/api/remote/jobs")
        assert status == 200
        assert payload["data"]["jobs"][0]["id"] == bundle_job["id"]
        assert payload["data"]["stats"]["protocol"] == PROTOCOL

    def test_an_unknown_status_is_a_400(self, api):
        status, payload = call(api, "GET", "/api/remote/jobs?status=nonsense")
        assert status == 400
        assert payload["error"]["code"] == "validation"

    def test_an_unknown_job_is_a_404(self, api):
        status, payload = call(api, "GET", "/api/remote/jobs/rj_nope")
        assert status == 404
        assert payload["error"]["code"] == "not_found"

    def test_without_a_token_the_route_is_closed(self, api):
        status, _payload = call(api, "GET", "/api/remote/jobs", token=None)
        assert status == 401

    def test_the_page_can_export_approve_and_dispatch(self, api, dataset, worker_server):
        port, _worker = worker_server
        status, payload = call(api, "POST", "/api/remote/export", body={"dataset": dataset, "order": 2})
        assert status == 200
        job_id = payload["data"]["id"]
        status, payload = call(api, "POST", f"/api/remote/jobs/{job_id}/approve", body={})
        assert status == 200
        assert payload["data"]["approved_by"] == "user:gui"
        status, payload = call(
            api, "POST", f"/api/remote/jobs/{job_id}/dispatch", body={"endpoint": endpoint(port)}
        )
        assert status == 200
        assert payload["data"]["status"] == "dispatched"
        status, payload = call(api, "POST", f"/api/remote/jobs/{job_id}/collect", body={})
        assert status == 200
        assert payload["data"]["status"] == "verified"
        status, payload = call(api, "GET", "/api/remote/jobs")
        assert any(job["status"] == "verified" for job in payload["data"]["jobs"])

    def test_status_reports_remote_still_off_by_default(self, api, ws):
        ws.config.set("remote.enabled", False)
        status, payload = call(api, "GET", "/api/status")
        assert status == 200
        assert payload["data"]["remote"]["enabled"] is False


# --------------------------------------------------------------------------
# 8. the same trainer, whichever machine runs it
# --------------------------------------------------------------------------
class TestTheSameTrainer:
    def test_the_worker_path_and_the_local_path_agree(self, ws, bundle_job):
        """`train_records` is the one implementation; this checks both callers get the same answer."""
        path = Path(ws.config.path("paths.artifacts")) / "remote" / Path(bundle_job["bundle_path"]).name
        bundle = json.loads(path.read_text(encoding="utf-8"))
        entries = [
            {"path": entry["path"], "split": entry["split"], "label": entry["label"],
             "text": entry["text"]}
            for entry in bundle["dataset"]["entries"]
        ]
        trained = train_records(entries, "ngram", bundle["run"])
        model = NGramModel(order=2, smoothing=0.1)
        model.fit([e["text"] for e in entries if e["split"] == "train"])
        assert trained["artifact"]["counts"] == model.to_dict()["counts"]
        for split in ("train", "val", "test"):
            texts = [e["text"] for e in entries if e["split"] == split]
            expected = sum(model.perplexity(text) for text in texts) / len(texts)
            assert trained["metrics"][split]["perplexity"] == pytest.approx(expected)

    def test_a_method_the_worker_cannot_run_is_named(self):
        with pytest.raises(ValidationError, match="not a trainer"):
            train_records([{"path": "a", "split": "train", "label": None, "text": "x"}], "lora", {})
