"""Remote training jobs, identity and lifecycle; jobs are in-memory, not durable."""

from __future__ import annotations
import socket, tempfile, threading, time, uuid
import json
from pathlib import Path
from typing import Any
from archx_agent.application.training import train_records
from .protocol import PROTOCOL, WorkerRefusal, WorkerBusy, check_bundle, _sha, _canonical
from .policy import validate_token
from archx_agent.helpers.processes import positive_integer
from .files import WorkerFilesMixin
from .execution import WorkerExecutionMixin


class Worker(WorkerFilesMixin, WorkerExecutionMixin):
    def __init__(
        self,
        *,
        name: str | None = None,
        delay: float = 0.0,
        allow_exec: bool = False,
        token: str | None = None,
        workdir: str | None = None,
        max_running_jobs: int = 4,
        max_jobs: int = 128,
    ) -> None:
        token = validate_token(token)
        self.max_running_jobs = positive_integer(max_running_jobs, "max_running_jobs")
        self.max_jobs = positive_integer(max_jobs, "max_jobs")
        self.name = name or socket.gethostname()
        self.delay = float(delay)
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        # Command execution is opt-in on the *worker's* side, because the person who starts the
        # worker is the person whose machine a command can damage. A bundle is data; /exec is not.
        self.allow_exec = bool(allow_exec)
        self.token = token
        self.workdir = Path(workdir or tempfile.mkdtemp(prefix="archx-worker-"))
        self.workdir.mkdir(parents=True, exist_ok=True)

    def capacity(self) -> dict[str, int]:
        """Report admission arithmetic without exposing credentials or job contents."""
        with self.lock:
            return {
                "running_jobs": sum(job["status"] == "running" for job in self.jobs.values()),
                "retained_jobs": len(self.jobs),
                "max_running_jobs": self.max_running_jobs,
                "max_jobs": self.max_jobs,
            }

    def accept(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            request = json.loads(_canonical(request))
        except (ValueError, TypeError, RecursionError) as exc:
            raise WorkerRefusal("worker request must contain JSON data") from exc
        bundle = check_bundle(request)
        job_id = f"rj_worker_{uuid.uuid4().hex[:12]}"
        with self.lock:
            if len(self.jobs) >= self.max_jobs:
                raise WorkerBusy("worker result capacity reached; collect results before a planned restart")
            if sum(job["status"] == "running" for job in self.jobs.values()) >= self.max_running_jobs:
                raise WorkerBusy("worker training capacity reached; retry after running jobs finish")
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": "running",
                "bundle_sha256": request["bundle_sha256"],
                "started_at": time.time(),
            }
        try:
            thread = threading.Thread(target=self._run, args=(job_id, bundle), daemon=True)
            thread.start()
        except Exception as exc:
            with self.lock:
                self.jobs.pop(job_id, None)
            raise WorkerBusy("worker could not start a training thread; retry later") from exc
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
            # Bind accepted input identity before computing the result digest; no
            # post-acceptance callback must race the background training thread.
            with self.lock:
                artifact["bundle_sha256"] = self.jobs[job_id]["bundle_sha256"]
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
                            "seconds": round(
                                time.time() - self.jobs[job_id]["started_at"], 3
                            ),
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
        """Compatibility check; accepted input identity cannot be rewritten later."""
        with self.lock:
            job = self.jobs.get(job_id)
            if job is not None and job["bundle_sha256"] != bundle_sha256:
                raise WorkerRefusal("cannot change an accepted job's bundle identity")
