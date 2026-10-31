"""Transactional write handlers for durable jobs."""

from __future__ import annotations

import os
import time
from typing import Any

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_from_ts, iso_now
from archx_agent.managers.jobs.constants import _UPDATE_COLUMNS, _JSON_COLUMNS
from archx_agent.managers.jobs.records import Job
from archx_agent.managers.jobs.validation import _json


class JobManagerWritesMixin:
    """Writes responsibility for JobManager."""

    def register_handlers(self) -> None:
        self.coordinator.register("job.enqueue", self._apply_enqueue)
        self.coordinator.register("job.claim", self._apply_claim)
        self.coordinator.register("job.update", self._apply_update)

    def _apply_enqueue(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        job = payload["job"]
        if job.get("dedupe_key"):
            existing = tx.query(
                "SELECT id, status FROM jobs WHERE dedupe_key = ? AND status IN"
                " ('queued', 'running', 'paused') ORDER BY queue_seq LIMIT 1",
                (job["dedupe_key"],),
            )
            if existing:
                return {
                    "id": existing[0]["id"],
                    "deduped": True,
                    "status": existing[0]["status"],
                }
        seq_row = tx.query("SELECT COALESCE(MAX(queue_seq), 0) + 1 AS next FROM jobs")
        queue_seq = int(seq_row[0]["next"]) if seq_row else 1
        tx.execute(
            "INSERT INTO jobs(id, kind, title, payload, status, priority, queue_seq, created_at,"
            " started_at, ended_at, deadline, progress, message, error, resource_estimate,"
            " resource_observed, result, task_id, project_id, cancelled, attempts, max_attempts,"
            " timeout_seconds, pid, worker, requeued_at, control, cursor, dedupe_key)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job["id"],
                job["kind"],
                job["title"],
                json_text(job.get("payload") or {}),
                job["status"],
                int(job["priority"]),
                queue_seq,
                job["created_at"],
                job.get("started_at"),
                job.get("ended_at"),
                job.get("deadline"),
                float(job.get("progress") or 0),
                job.get("message"),
                job.get("error"),
                json_text(job.get("resource_estimate") or {}),
                json_text(job.get("resource_observed") or {}),
                json_text(job["result"]) if job.get("result") else None,
                job.get("task_id"),
                job.get("project_id"),
                0,
                int(job.get("attempts") or 0),
                int(job.get("max_attempts") or 1),
                job.get("timeout_seconds"),
                job.get("pid"),
                job.get("worker"),
                job.get("requeued_at"),
                job.get("control"),
                int(job.get("cursor") or 0),
                job.get("dedupe_key"),
            ),
        )
        return {"id": job["id"], "queue_seq": queue_seq, "deduped": False}

    def _apply_claim(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        """Pick the best queued job that fits and mark it running - atomically."""
        if payload.get("job_id"):
            rows = tx.query(
                "SELECT * FROM jobs WHERE status = 'queued' AND id = ?",
                (payload["job_id"],),
            )
        else:
            rows = tx.query(
                "SELECT * FROM jobs WHERE status = 'queued'"
                " ORDER BY priority DESC, queue_seq ASC LIMIT 100"
            )
        cpu_free = float(payload.get("cpu_free", 100))
        mem_free = float(payload.get("memory_free", 10**6))
        kinds = payload.get("kinds")
        chosen = None
        for row in rows:
            if kinds and row["kind"] not in kinds:
                continue
            est = _json(row.get("resource_estimate"), {})
            if float(est.get("cpu_percent", 0)) > cpu_free:
                continue
            if float(est.get("memory_mb", 0)) > mem_free:
                continue
            chosen = row
            break
        if chosen is None:
            return {"job": None}
        timeout = chosen.get("timeout_seconds") or int(
            self._cfg("scheduler.job_timeout_seconds", 3600)
        )
        now = iso_now()
        attempts = int(chosen.get("attempts") or 0) + 1
        deadline = iso_from_ts(time.time() + float(timeout))
        tx.execute(
            "UPDATE jobs SET status = 'running', worker = ?, pid = ?, started_at = ?,"
            " deadline = ?, attempts = ?, control = NULL, ended_at = NULL, progress = 0"
            " WHERE id = ? AND status = 'queued'",
            (
                payload["worker"],
                os.getpid(),
                now,
                deadline,
                attempts,
                chosen["id"],
            ),
        )
        row = tx.query("SELECT * FROM jobs WHERE id = ?", (chosen["id"],))
        return {
            "job": dict(row[0]) if row else None,
            "attempts": attempts,
            "deadline": deadline,
        }

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        fields = dict(payload["fields"])
        unknown = set(fields) - _UPDATE_COLUMNS
        if unknown:  # pragma: no cover - guard against a typo becoming SQL
            raise ValidationError(
                f"cannot update job column(s): {', '.join(sorted(unknown))}"
            )
        for key in _JSON_COLUMNS & set(fields):
            fields[key] = json_text(fields[key] if fields[key] is not None else {})
        sets = ", ".join(f"{key} = ?" for key in fields) or "status = status"
        tx.execute(
            f"UPDATE jobs SET {sets} WHERE id = ?", [*fields.values(), payload["id"]]
        )
        return {"id": payload["id"], "updated": len(fields)}

    def _update(self, job_id: str, **fields: Any) -> Job:
        self.get(job_id)
        self._write("job.update", {"id": job_id, "fields": fields})
        return self.get(job_id)
