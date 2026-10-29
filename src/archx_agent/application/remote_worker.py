"""The far end of the protocol: a worker that runs the same trainer and says what it did.

A worker is deliberately boring. It has no database, no tools, no permissions and no state worth
keeping: it takes a bundle, checks the bundle against itself, runs the trainer that this build
already has, and returns an artifact with its sha256. Everything it needs is in the request, which is
what makes it a *remote* worker rather than a second client of the same database.

It checks three things before it trains anything:

``protocol``
    the request names the version it speaks; a mismatch is refused with both versions named;
``bundle_sha256``
    the body re-hashed here must equal the hash sent alongside it, so the worker trains on exactly
    the input the requester hashed;
``manifest``
    the manifest lines are recomputed from the entries, so a bundle whose records were edited after
    the dataset was built fails here rather than producing a number about an input nobody agreed on.

Then it runs :func:`archx_agent.application.training.train_records` - the same function the local
`train run` uses. A worker with its own implementation would make every remote metric a claim about
a second program.

The server is ``http.server``: a dependency-free thread-per-request handler, not a job queue,
because the milestone is about whether a result can be *checked*, not about throughput. It binds
``127.0.0.1`` by default and must be told to bind anything else, so "remote compute" cannot quietly
become "an open port on a laptop".
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from archx_agent.application.training import train_records
from archx_agent.managers.remote import PROTOCOL


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


class WorkerRefusal(Exception):
    """The bundle cannot be trained on, and the reason is the interesting part."""


def check_bundle(request: dict[str, Any]) -> dict[str, Any]:
    """Everything that must be true before a worker spends a cycle on a stranger's request."""
    if request.get("protocol") != PROTOCOL:
        raise WorkerRefusal(
            f"this worker speaks {PROTOCOL!r}, the request speaks {request.get('protocol')!r}"
        )
    bundle = request.get("bundle")
    if not isinstance(bundle, dict):
        raise WorkerRefusal("the request carries no bundle")
    body = _canonical(bundle)
    measured = _sha(body)
    claimed = str(request.get("bundle_sha256") or "")
    if not claimed:
        raise WorkerRefusal("the request names no bundle hash, so the input cannot be identified")
    if measured != claimed:
        raise WorkerRefusal(
            f"the bundle hashes to {measured[:16]} here and to {claimed[:16]} at the requester: "
            "the input moved in transit, so no number from it would mean anything"
        )
    dataset = bundle.get("dataset") or {}
    entries = dataset.get("entries") or []
    if not entries:
        raise WorkerRefusal("the bundle carries no records")
    for entry in entries:
        measured_text = _sha(str(entry.get("text") or ""))
        if measured_text != entry.get("text_sha256"):
            raise WorkerRefusal(
                f"{entry.get('path')} does not hash to the text digest in the bundle: the corpus "
                "was edited in transit"
            )
    # The manifest is rebuilt from the *file* digests the dataset recorded, which is what it was
    # built from - not from the trimmed text this worker trains on.
    lines = sorted(
        f"{entry.get('split') or 'train'}\t{entry.get('file_sha256')}\t"
        f"{entry.get('file_bytes')}\t{entry.get('path')}"
        for entry in entries
    )
    if _sha("\n".join(lines)) != dataset.get("manifest_checksum"):
        raise WorkerRefusal(
            "the bundle's records do not rebuild the manifest checksum it claims: the request "
            "contradicts itself"
        )
    if not any((entry.get("split") or "train") == "train" for entry in entries):
        raise WorkerRefusal("no record in the bundle is in the train split, so there is nothing to train")
    return bundle


class Worker:
    """A job registry plus the arithmetic. Deliberately small."""

    def __init__(self, *, name: str | None = None, delay: float = 0.0) -> None:
        self.name = name or socket.gethostname()
        self.delay = float(delay)
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def accept(self, request: dict[str, Any]) -> dict[str, Any]:
        bundle = check_bundle(request)
        job_id = f"rj_worker_{uuid.uuid4().hex[:12]}"
        with self.lock:
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": "running",
                "bundle_sha256": request["bundle_sha256"],
                "started_at": time.time(),
            }
        thread = threading.Thread(target=self._run, args=(job_id, bundle), daemon=True)
        thread.start()
        return {
            "protocol": PROTOCOL,
            "machine": self.name,
            "job_id": job_id,
            "approved_by": f"worker:{self.name}",
            "status": "running",
        }

    def _run(self, job_id: str, bundle: dict[str, Any]) -> None:
        try:
            if self.delay:
                time.sleep(self.delay)
            entries = [
                {
                    "path": entry["path"],
                    "split": entry.get("split") or "train",
                    "label": entry.get("label"),
                    "text": entry["text"],
                }
                for entry in bundle["dataset"]["entries"]
            ]
            run = bundle.get("run") or {}
            trained = train_records(entries, run.get("method") or "ngram", run)
            artifact = dict(trained["artifact"])
            artifact["trained_on"] = bundle["dataset"]["id"]
            artifact["seed"] = int(run.get("seed") or 0)
            artifact["computed_by"] = f"worker:{self.name}"
            # The bundle's hash is stamped by `stamp()`, after the body has been computed: a
            # document cannot contain its own hash, and pretending otherwise would mean hashing
            # something other than what was sent.
            body = _canonical(artifact)
            with self.lock:
                self.jobs[job_id].update(
                    {
                        "status": "completed",
                        "artifact": artifact,
                        "artifact_sha256": _sha(body),
                        "metrics": trained["metrics"],
                        "actual": {
                            "records": len(entries),
                            "seconds": round(time.time() - self.jobs[job_id]["started_at"], 3),
                        },
                        "finished_at": time.time(),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - a failed worker job is reported, not raised
            with self.lock:
                self.jobs[job_id].update({"status": "failed", "error": str(exc)})

    def result(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return {"protocol": PROTOCOL, "machine": self.name, "status": "unknown"}
            payload = {
                "protocol": PROTOCOL,
                "machine": self.name,
                "job_id": job_id,
                "status": job["status"],
            }
            for key in ("artifact", "artifact_sha256", "metrics", "actual", "error"):
                if key in job:
                    payload[key] = job[key]
            return payload

    def stamp(self, job_id: str, bundle_sha256: str) -> None:
        """Record which bundle produced the artifact, once the hash is known."""
        with self.lock:
            job = self.jobs.get(job_id)
            if job and "artifact" in job:
                job["artifact"]["bundle_sha256"] = bundle_sha256
                job["artifact_sha256"] = _sha(_canonical(job["artifact"]))


def make_server(worker: Worker, *, host: str = "127.0.0.1", port: int = 9001) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "archx-worker/1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - quiet by default
            if os.environ.get("ARCHX_WORKER_LOG"):
                super().log_message(fmt, *args)

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - http.server's naming
            if self.path in ("/health", "/"):
                self._send(200, {
                    "protocol": PROTOCOL, "machine": worker.name, "status": "ok",
                    "jobs": len(worker.jobs),
                })
                return
            if self.path.startswith("/jobs/"):
                job_id = self.path.split("/jobs/", 1)[1].strip("/")
                self._send(200, worker.result(job_id))
                return
            self._send(404, {"protocol": PROTOCOL, "error": f"no route for {self.path}"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                request = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError as exc:
                self._send(400, {"protocol": PROTOCOL, "error": f"not json: {exc}"})
                return
            if self.path.rstrip("/") == "/jobs":
                try:
                    accepted = worker.accept(request)
                except WorkerRefusal as refusal:
                    # A refusal is an answer: the requester needs the reason, not a stack trace.
                    self._send(422, {"protocol": PROTOCOL, "machine": worker.name,
                                     "error": str(refusal), "status": "refused"})
                    return
                worker.stamp(accepted["job_id"], str(request.get("bundle_sha256")))
                self._send(200, accepted)
                return
            self._send(404, {"protocol": PROTOCOL, "error": f"no route for {self.path}"})

    return ThreadingHTTPServer((host, port), Handler)


def serve(*, host: str = "127.0.0.1", port: int = 9001, name: str | None = None,
          delay: float = 0.0, ready: Any = None) -> None:
    worker = Worker(name=name, delay=delay)
    server = make_server(worker, host=host, port=port)
    if ready is not None:  # pragma: no cover - used by the acceptance script
        ready(server)
    print(f"archx worker {worker.name} on http://{host}:{server.server_address[1]}"
          f" speaking {PROTOCOL}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        pass
    finally:
        server.server_close()
