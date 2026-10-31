"""Remote compute and portability: hand work to another machine, and check what comes back.

The hard part of "remote compute" is not the request; it is believing the answer. A result that
arrives over a socket is a claim by a machine you are not sitting at, and every dishonest version of
this feature is the same shape: take the number, print it, and never ask whether the far end ran
anything at all.

So the mode is built around four things that can be checked:

**The input is a bundle.** :meth:`RemoteService.export` writes one JSON document - the dataset's
manifest, the trainer's declared config, the seed, this build's version and schema version - and
hashes it. A result is traceable to *that* bundle rather than to "the dataset, probably". The bundle
goes through ``fs.write`` like every other write here.

**The endpoint is named on the record.** Protocol version, machine, and address are stored before
anything is sent, and a worker that speaks another protocol version is refused rather than guessed
at.

**The artifact is hashed twice.** The far end reports a sha256; this machine recomputes it on
arrival and the two are stored in separate columns. A disagreement marks the job ``received`` with a
failing note, never ``verified`` - a remote result that cannot be checked is not a result.

**A job that never arrives is a row.** Dispatch failures, timeouts and refusals are recorded as
``remote_attempts``, in the same spirit as M34's refused probes and M36's refused runs.

What this does not do is claim to have reached a cloud. A worker here is a second process, usually on
the same machine, that speaks the documented protocol and runs the same trainers; the record says
exactly that, because "the endpoint at 127.0.0.1:9001 computed this" is a true sentence and "the
cloud computed this" would not be.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from archx_agent import __version__
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.remote import PROTOCOL, RemoteJob
from archx_agent.managers.schema import SCHEMA_VERSION
from archx_agent.managers.tools import ToolContext


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RemoteService:
    """Export a portable bundle, dispatch it, and check what comes back."""

    def __init__(self, ws) -> None:
        self.ws = ws

    # -- plumbing ---------------------------------------------------------
    @property
    def manager(self):
        return self.ws.remote

    def _execute(self, name: str, arguments: dict[str, Any], context: ToolContext):
        run = self.ws.tools.execute(name, arguments, context=context, requester="remote")
        if run.status == "denied":
            approval = getattr(run, "approval_id", None)
            if approval:
                raise ApprovalRequiredError(
                    f"{name} needs approval: approve {approval} or grant the capability",
                    approval_id=approval,
                )
            raise PermissionDeniedError(run.error or f"{name} was refused")
        if run.status == "failed":
            raise ToolError(run.error or f"{name} failed")
        return run

    def _context(self, purpose: str) -> ToolContext:
        return ToolContext(purpose=purpose)

    def _artifacts_dir(self) -> Path:
        base = Path(self.ws.config.path("paths.artifacts")) / "remote"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _endpoint(self, wanted: str | None) -> str:
        endpoint = (wanted or str(self.ws.config.get("remote.endpoint", "") or "")).strip()
        return endpoint.rstrip("/")

    # -- the boundary -----------------------------------------------------
    def blockers(self, endpoint: str | None = None) -> list[str]:
        """Why nothing can be dispatched right now, in the order found."""
        reasons: list[str] = []
        if not self.ws.config.get("remote.enabled", False):
            reasons.append("remote compute is off: `archx-agent config set remote.enabled true`")
        target = self._endpoint(endpoint)
        if not target:
            reasons.append(
                "no endpoint is configured: `archx-agent config set remote.endpoint http://…`"
            )
        elif not target.startswith(("http://", "https://")):
            reasons.append(f"the endpoint {target!r} is not an http(s) URL")
        reasons.append(
            "no cloud provider is reachable from this build: a worker is a second machine (or a "
            "second process) running `archx-agent remote worker`, and nothing here talks to a "
            "vendor's compute service"
        )
        return reasons

    # -- the bundle -------------------------------------------------------
    def export(
        self,
        dataset: str,
        *,
        method: str = "ngram",
        order: int = 3,
        smoothing: float = 0.1,
        seed: int = 0,
        label_source: str = "record",
    ) -> dict[str, Any]:
        """Write one portable document: the corpus, its digests, and the declared run.

        The corpus travels with the bundle, because a bundle that named only paths would be portable
        only between two machines that already share a filesystem - which is not portability, it is a
        shared disk. Each record's text is re-hashed against the digest M35 recorded when the dataset
        was built, so a file edited after the build cannot enter a bundle silently.
        """
        view = self.ws.data.view(dataset)
        if not view.get("checksum"):
            raise ValidationError(
                "this dataset has no manifest yet: run `dataset build` first, because a bundle "
                "whose input cannot be named cannot be checked when the result comes back"
            )
        records = self.ws.data.records(view["id"], status="kept", limit=100_000)
        if not records:
            raise ValidationError("there is nothing to send: no record survived cleaning")
        entries: list[dict[str, Any]] = []
        total = 0
        for record in records:
            # The *file's* digest is measured with `fs.probe`, which hashes bytes; the *text* is
            # read with `fs.read`, which is what the trainer sees. They are hashed separately and
            # recorded separately, because `fs.read` trims surrounding whitespace and a bundle that
            # pretended the two were the same bytes would be wrong about small files and lying
            # about large ones.
            probe = self._execute(
                "fs.probe", {"path": record["path"]},
                self._context(f"remote measure {record['path']}"),
            )
            measured = str((probe.result or {}).get("sha256") or "")
            if measured != record["sha256"]:
                raise ValidationError(
                    f"{record['path']} no longer hashes to what the dataset recorded, so a result "
                    "could not be traced to a known input: rebuild or re-add the dataset first"
                )
            text = self._read_text(record["path"])
            entries.append(
                {
                    "path": record["path"],
                    "split": record["split"] or "train",
                    "label": record.get("label"),
                    "file_sha256": measured,
                    "file_bytes": int(record["bytes"]),
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "text": text,
                }
            )
            total += len(text)
        limit = int(self.ws.config.get("remote.max_chars", 200_000) or 200_000)
        if total > limit:
            raise ValidationError(
                f"this dataset is {total} characters and remote.max_chars is {limit}: shipping it "
                "would be a transfer nobody asked for, so nothing was exported"
            )
        manifest = self.ws.data.manifest(view["id"])
        bundle = {
            "protocol": PROTOCOL,
            "archx_version": __version__,
            "schema_version": SCHEMA_VERSION,
            "created_at": iso_now(),
            "dataset": {
                "id": view["id"],
                "name": view["name"],
                "license": view["license"],
                "seed": view["seed"],
                "records": view["counts"]["kept"],
                "by_split": view["counts"]["by_split"],
                "manifest_checksum": manifest["checksum"],
                "manifest_lines": manifest["lines"],
                "text_scope": "as `fs.read` returns it - surrounding whitespace trimmed",
                "entries": entries,
            },
            "run": {
                "method": method,
                "order": int(order),
                "smoothing": float(smoothing),
                "seed": int(seed),
                "label_source": label_source,
            },
        }
        body = json.dumps(bundle, indent=2, sort_keys=True)
        digest = _sha(body)
        target = f"{view['name'].replace('/', '_') or 'bundle'}.{digest[:12]}.bundle.json"
        written = self._execute(
            "fs.write", {"path": target, "content": body, "create_parents": True},
            self._context(f"remote bundle {target}"),
        )
        output = dict(written.result or {})
        local = self._artifacts_dir() / Path(target).name
        local.write_text(body, encoding="utf-8")
        job = self.manager.create(
            provider="worker",
            kind="training",
            dataset_id=view["id"],
            bundle_sha256=digest,
            bundle_path=output.get("path") or target,
            config={"run": bundle["run"]},
        )
        payload = self.view(job.id)
        payload["bundle_sha256"] = digest
        payload["chars"] = total
        payload["records"] = len(entries)
        payload["local_copy"] = str(local)
        return payload

    def _read_text(self, path: str) -> str:
        read = self._execute("fs.read", {"path": path}, self._context(f"remote read {path}"))
        return str((read.result or {}).get("content") or "")

    def approve(self, job_id: str, *, by: str = "user") -> dict[str, Any]:
        """Say out loud that this bundle may leave the machine.

        `remote.require_approval` defaults to true, so a dispatch without this is refused with the
        command that would grant it - the setting would be a lie otherwise.
        """
        job = self.manager.get(job_id)
        approved = self.manager.update(job.id, status=job.status, approved_by=f"user:{by}")
        self.manager.record_attempt(
            action="approve", status="ok", job_id=job.id, detail=f"approved by {by}",
            endpoint=job.endpoint,
        )
        return self.view(approved.id)

    # -- dispatch ---------------------------------------------------------
    def dispatch(self, job_id: str, *, endpoint: str | None = None, timeout: float = 10.0) -> dict[str, Any]:
        job = self.manager.get(job_id)
        reasons = self.blockers(endpoint)
        if self.ws.config.get("remote.require_approval", True) and not job.approved_by:
            reasons.insert(
                0,
                f"remote.require_approval is on and {job.id} has not been approved: "
                f"`archx-agent remote approve {job.id}`",
            )
            refused = self.manager.update(
                job.id, status="refused", refusal="; ".join(reasons), completed_at=iso_now()
            )
            self.manager.record_attempt(
                action="dispatch", status="refused", job_id=job.id,
                detail=reasons[0], endpoint=endpoint,
            )
            payload = self.view(refused.id)
            payload["reasons"] = reasons
            return payload
        if not self.ws.config.get("remote.enabled", False) or not self._endpoint(endpoint):
            refused = self.manager.update(
                job.id, status="refused", refusal="; ".join(reasons), completed_at=iso_now()
            )
            self.manager.record_attempt(
                action="dispatch", status="refused", job_id=job.id,
                detail=reasons[0], endpoint=endpoint,
            )
            payload = self.view(refused.id)
            payload["reasons"] = reasons
            return payload

        target = self._endpoint(endpoint)
        bundle = self._load_bundle(job)
        request = json.dumps({
            "protocol": PROTOCOL,
            "bundle": bundle,
            "bundle_sha256": job.bundle_sha256,
            "requester": "archx-agent",
        }).encode("utf-8")
        try:
            response = self._post(f"{target}/jobs", request, timeout=timeout)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # A dispatch that never arrived is a finding, not a stack trace.
            failed = self.manager.update(
                job.id, status="failed", error=str(exc), completed_at=iso_now()
            )
            self.manager.record_attempt(
                action="dispatch", status="failed", job_id=job.id, detail=str(exc), endpoint=target,
            )
            payload = self.view(failed.id)
            payload["reasons"] = [f"the endpoint {target} could not be reached: {exc}"]
            return payload

        if response.get("protocol") != PROTOCOL:
            detail = (
                f"the worker speaks {response.get('protocol')!r}, this build speaks {PROTOCOL!r}"
            )
            refused = self.manager.update(
                job.id, status="refused", refusal=detail, endpoint=target,
                machine=response.get("machine"), protocol=response.get("protocol"),
                completed_at=iso_now(),
            )
            self.manager.record_attempt(
                action="dispatch", status="refused", job_id=job.id, detail=detail, endpoint=target,
            )
            payload = self.view(refused.id)
            payload["reasons"] = [detail]
            return payload

        sent = self.manager.update(
            job.id,
            status="dispatched",
            endpoint=target,
            machine=response.get("machine"),
            protocol=response.get("protocol"),
            remote_job_id=response.get("job_id"),
            approved_by=response.get("approved_by") or "endpoint",
        )
        self.manager.record_attempt(
            action="dispatch", status="ok", job_id=job.id,
            detail=f"accepted as {response.get('job_id')}", endpoint=target,
            metadata={"machine": response.get("machine")},
        )
        return self.view(sent.id)

    def _headers(self) -> dict[str, str]:
        """A worker may require a bearer token; the bundle and the exec route use the same one."""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token = str(self.ws.config.get("remote.worker_token", "") or "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _post(self, url: str, body: bytes, *, timeout: float) -> dict[str, Any]:
        request = urllib.request.Request(url, data=body, method="POST", headers=self._headers())
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - http(s)
            return json.loads(response.read().decode("utf-8"))

    def _get(self, url: str, *, timeout: float) -> dict[str, Any]:
        request = urllib.request.Request(url, method="GET", headers=self._headers())
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def _load_bundle(self, job: RemoteJob) -> dict[str, Any]:
        if not job.bundle_path:
            raise NotFoundError(f"{job.id} has no bundle recorded")
        raw = self._execute(
            "fs.read", {"path": job.bundle_path}, self._context(f"remote bundle {job.bundle_path}")
        )
        text = str((raw.result or {}).get("content") or "")
        bundle = json.loads(text)
        # The bundle is re-hashed before it is sent: sending a file whose hash does not match the
        # row would make every later claim about the input unverifiable.
        if _sha(json.dumps(bundle, indent=2, sort_keys=True)) != job.bundle_sha256:
            raise ValidationError(
                f"{job.bundle_path} no longer hashes to {job.bundle_sha256}: the bundle changed "
                "after it was recorded, so a result could not be traced to it"
            )
        return bundle

    # -- collecting -------------------------------------------------------
    def collect(self, job_id: str, *, timeout: float = 10.0) -> dict[str, Any]:
        """Fetch the artifact, recompute its hash, and only then call the job verified."""
        job = self.manager.get(job_id)
        if not job.endpoint or not job.remote_job_id:
            raise ValidationError(f"{job.id} was never dispatched, so there is nothing to collect")
        try:
            response = self._get(f"{job.endpoint}/jobs/{job.remote_job_id}", timeout=timeout)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.manager.record_attempt(
                action="collect", status="failed", job_id=job.id, detail=str(exc),
                endpoint=job.endpoint,
            )
            raise ValidationError(f"could not reach {job.endpoint}: {exc}") from exc

        state = response.get("status")
        if state != "completed":
            received = self.manager.update(job.id, status="running", actual={"state": state})
            self.manager.record_attempt(
                action="collect", status="pending", job_id=job.id, detail=f"the worker says {state}",
                endpoint=job.endpoint,
            )
            payload = self.view(received.id)
            payload["reasons"] = [f"the worker has not finished: it says {state!r}"]
            return payload

        artifact = response.get("artifact")
        if not isinstance(artifact, dict):
            raise ValidationError("the worker reported completion without an artifact")
        body = json.dumps(artifact, indent=2, sort_keys=True)
        measured = _sha(body)
        claimed = str(response.get("artifact_sha256") or "")
        path = f"{job.id}.remote.json"
        written = self._execute(
            "fs.write", {"path": path, "content": body, "create_parents": True},
            self._context(f"remote artifact {path}"),
        )
        output = dict(written.result or {})
        local = self._artifacts_dir() / Path(path).name
        local.write_text(body, encoding="utf-8")

        agrees = bool(claimed) and claimed == measured
        received = self.manager.update(
            job.id,
            status="received",
            claimed_sha256=claimed or None,
            received_sha256=measured,
            artifact_path=output.get("path") or path,
            received_at=iso_now(),
            actual=dict(response.get("actual") or {}),
            outputs={
                "artifact_kind": artifact.get("kind"),
                "bytes": len(body.encode("utf-8")),
                # The numbers the worker reported, kept with the row rather than only in the
                # artifact: a metric nobody can query is a metric nobody can compare.
                "metrics": dict(response.get("metrics") or {}),
                "computed_by": artifact.get("computed_by"),
            },
            verify_note=(
                "the artifact hashes to what the worker said it would"
                if agrees
                else f"the worker claimed {claimed or '(nothing)'} but the bytes hash to {measured}"
            ),
        )
        self.manager.record_attempt(
            action="collect", status="ok" if agrees else "mismatch", job_id=job.id,
            detail="hash agrees" if agrees else "hash mismatch", endpoint=job.endpoint,
            metadata={"claimed": claimed, "measured": measured},
        )
        if agrees:
            return self.verify(job.id)
        payload = self.view(received.id)
        payload["reasons"] = [received.verify_note or "the artifact did not match"]
        return payload

    def verify(self, job_id: str) -> dict[str, Any]:
        """Re-read the stored artifact and compare it with the row, again."""
        job = self.manager.get(job_id)
        if not job.artifact_path:
            raise ValidationError(f"{job.id} has no artifact to verify")
        raw = self._execute(
            "fs.read", {"path": job.artifact_path}, self._context(f"remote verify {job.artifact_path}")
        )
        text = str((raw.result or {}).get("content") or "")
        measured = hashlib.sha256(text.encode("utf-8")).hexdigest()
        on_disk = measured == job.received_sha256
        # A second opinion on the file is not enough: if the worker's claim and this machine's
        # measurement never agreed, re-reading the file cannot make them agree.
        claim_agrees = not job.claimed_sha256 or job.claimed_sha256 == job.received_sha256
        agrees = on_disk and claim_agrees
        if not on_disk:
            note = f"the artifact on disk hashes to {measured}, not {job.received_sha256}"
        elif not claim_agrees:
            note = (
                f"the worker claimed {job.claimed_sha256} and this machine measured "
                f"{job.received_sha256}; re-reading the file does not settle that"
            )
        else:
            note = "the artifact on disk still hashes to what was received"
        verified = self.manager.update(
            job.id,
            status="verified" if agrees else "received",
            verified_at=iso_now() if agrees else None,
            verify_note=note,
        )
        payload = self.view(verified.id)
        payload["agrees"] = agrees
        payload["reasons"] = [] if agrees else [note]
        if not agrees:
            payload["status"] = "received"
        return payload

    # -- reading ----------------------------------------------------------
    def view(self, wanted: str) -> dict[str, Any]:
        job = self.manager.get(wanted)
        payload = job.to_dict()
        payload["attempts"] = [
            attempt.to_dict() for attempt in self.manager.attempts(job_id=job.id)
        ]
        payload["sentence"] = self._sentence(job)
        payload["reasons"] = [] if job.status != "refused" else [
            part.strip() for part in (job.refusal or "").split("; ") if part.strip()
        ]
        return payload

    @staticmethod
    def _sentence(job: RemoteJob) -> str:
        if job.status == "verified":
            return (
                f"{job.endpoint} computed this from bundle {str(job.bundle_sha256)[:12]} and the "
                f"artifact's hash was checked here"
            )
        if job.status == "received":
            return f"{job.endpoint} returned an artifact, but its hash did not match the claim"
        if job.status == "dispatched":
            return f"sent to {job.endpoint} as {job.remote_job_id}; nothing has come back yet"
        if job.status == "running":
            return f"{job.endpoint} has the job and has not finished"
        if job.status == "failed":
            return f"the dispatch to {job.endpoint} failed: {job.error}"
        if job.status == "refused":
            return f"nothing was sent: {job.refusal}"
        return f"{job.id} is {job.status}"

    def jobs(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [job.to_dict() for job in self.manager.jobs(status=status, limit=limit)]

    def attempts(self, *, job_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [
            attempt.to_dict() for attempt in self.manager.attempts(job_id=job_id, limit=limit)
        ]

    def stats(self) -> dict[str, Any]:
        base = self.manager.stats()
        base["enabled"] = bool(self.ws.config.get("remote.enabled", False))
        base["endpoint"] = self._endpoint(None)
        base["why_not"] = self.blockers()
        return base
