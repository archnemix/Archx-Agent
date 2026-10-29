"""Durable explicit-tick automations. Scheduling enqueues; it never executes or grants authority.

Dispatch atomically inserts the job and occurrence and advances a revision. Missed intervals are
coalesced, not replayed as a backlog. Watches compare file hashes through the permissioned tools.
"""
from __future__ import annotations

import json
from datetime import timedelta, timezone

from archx_agent.helpers.exceptions import ArchxError, ValidationError, NotFoundError
from archx_agent.helpers.timeutil import iso_now, parse_iso, new_id
from archx_agent.managers.base import BaseManager
from archx_agent.managers.jobs import Job, DEFAULT_ESTIMATES
from archx_agent.managers.tools import ToolContext


def stamp(value=None):
    try:
        dt = parse_iso(value or iso_now())
        if dt.tzinfo is None:
            raise ValueError("timezone required")
        return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, TypeError) as exc:
        raise ValidationError("schedule time must be an ISO timestamp with timezone") from exc


class AutomationManager(BaseManager):
    tables = ("automations", "automation_runs")

    def __init__(self, store, coordinator, *, jobs, events=None):
        self.jobs = jobs
        super().__init__(store, coordinator, events=events)

    def register_handlers(self):
        self.coordinator.register("automation.create", self._create)
        self.coordinator.register("automation.enable", self._enable)
        self.coordinator.register("automation.dispatch", self._dispatch)

    def _create(self, tx, payload):
        item = payload["item"]
        if tx.query("SELECT id FROM automations WHERE name=?", (item["name"],)):
            raise ValidationError("automation name already exists")
        tx.execute("INSERT INTO automations(id,name,kind,schedule,enabled,config,created_at,updated_at,next_run_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   (item["id"], item["name"], "command", json.dumps(item["schedule"]), 0,
                    json.dumps(item["config"]), item["created_at"], item["created_at"], item["next_run_at"]))
        return {"id": item["id"]}

    def _enable(self, tx, payload):
        tx.execute("UPDATE automations SET enabled=?,revision=revision+1,updated_at=? WHERE id=?",
                   (int(payload["enabled"]), payload["now"], payload["id"]))
        return {"id": payload["id"]}

    def _dispatch(self, tx, payload):
        rows = tx.query("SELECT * FROM automations WHERE id=?", (payload["id"],))
        if not rows or not rows[0]["enabled"] or rows[0]["revision"] != payload["revision"]:
            return {"dispatched": False}
        row = rows[0]
        if tx.query("SELECT r.id FROM automation_runs r JOIN jobs j ON j.id=r.job_id WHERE r.automation_id=? AND j.status IN ('queued','running','paused') LIMIT 1", (row["id"],)):
            return {"dispatched": False}
        if row["next_run_at"] and row["next_run_at"] > payload["now"]:
            return {"dispatched": False}
        # Reuse the queue's transaction handler, not its public separately-committed enqueue.
        # Job, occurrence, next deadline and revision either all commit or all roll back.
        job_result = self.jobs._apply_enqueue(tx, {"job": payload["job"]})
        tx.execute("INSERT INTO automation_runs(id,automation_id,status,started_at,output,job_id) VALUES (?,?,?,?,?,?)",
                   (payload["run_id"], row["id"], "queued", payload["now"], json.dumps({"job_id": job_result["id"]}), job_result["id"]))
        tx.execute("UPDATE automations SET next_run_at=?,last_run_at=?,last_status='queued',config=?,enabled=?,revision=revision+1,updated_at=? WHERE id=?",
                   (payload["next"], payload["now"], json.dumps(payload["config"]), payload["enabled"], payload["now"], row["id"]))
        return {"dispatched": True, "run_id": payload["run_id"], "job_id": job_result["id"]}

    def get(self, wanted):
        row = self.store.query_one("SELECT * FROM automations WHERE id=? OR name=? ORDER BY rowid DESC LIMIT 1", (wanted, wanted))
        if not row:
            raise NotFoundError(f"unknown automation: {wanted}")
        return self.decode(row)

    @staticmethod
    def decode(row):
        data = dict(row)
        data["schedule"] = json.loads(data["schedule"])
        data["config"] = json.loads(data.get("config") or "{}")
        data["enabled"] = bool(data["enabled"])
        return data

    def list(self):
        return [self.decode(row) for row in self.store.query("SELECT * FROM automations ORDER BY rowid")]

    def runs(self, wanted=None):
        rows = self.store.query("SELECT * FROM automation_runs WHERE automation_id=? ORDER BY rowid DESC", (self.get(wanted)["id"],)) if wanted else self.store.query("SELECT * FROM automation_runs ORDER BY rowid DESC")
        result = []
        for row in rows:
            data = dict(row)
            job_id = json.loads(data.get("output") or "{}").get("job_id")
            if job_id:
                job = self.jobs.get(job_id)
                data.update(job_id=job_id, status=job.status, error=job.error, task_id=job.task_id)
            result.append(data)
        return result


class AutomationService:
    def __init__(self, ws):
        self.ws = ws
        self.manager = ws.automations

    def _hash(self, path):
        run = self.ws.tools.execute("fs.probe", {"path": path}, context=ToolContext(purpose="automation watch"), requester="automations")
        if run.status != "succeeded":
            raise ValidationError(run.error or "watch probe refused")
        if run.result.get("sha256_scope") != "whole file":
            raise ValidationError("watch requires a whole-file hash; file exceeds probe limit")
        return run.result["sha256"]

    def create(self, name, command, *, interval=None, at=None, watch=None, cwd=None, timeout=60):
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValidationError("automation needs a name of 1-120 characters")
        if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x or "\x00" in x for x in command):
            raise ValidationError("command must be a nonempty JSON argv array")
        if sum(value is not None for value in (interval, at, watch)) != 1:
            raise ValidationError("choose exactly one interval, at timestamp, or watch path")
        if type(timeout) is not int or not 1 <= timeout <= 86400:
            raise ValidationError("timeout must be an integer from 1 to 86400")
        root = str(self.ws.tools.runtime.resolve(cwd or str(self.ws.tools.roots()[0])))
        if not self.ws.tools.runtime.resolve(root).is_dir():
            raise ValidationError("automation cwd must be an existing directory")
        now = stamp()
        config = {"command": command, "cwd": root, "timeout": timeout}
        if interval is not None:
            if type(interval) is not int or not 1 <= interval <= 31536000:
                raise ValidationError("interval must be an integer from 1 to 31536000 seconds")
            schedule = {"mode": "interval", "seconds": interval}
            next_time = stamp((parse_iso(now) + timedelta(seconds=interval)).isoformat())
        elif at is not None:
            schedule, next_time = {"mode": "once"}, stamp(at)
        else:
            path = str(self.ws.tools.runtime.resolve(watch))
            config.update(watch=path, last_hash=self._hash(path))
            schedule, next_time = {"mode": "watch"}, None
        item = {"id": new_id("au_"), "name": name.strip(), "schedule": schedule,
                "config": config, "created_at": now, "next_run_at": next_time}
        self.manager._write("automation.create", {"item": item})
        return self.manager.get(item["id"])

    def enable(self, wanted, enabled):
        item = self.manager.get(wanted)
        self.manager._write("automation.enable", {"id": item["id"], "enabled": enabled, "now": stamp()})
        return self.manager.get(item["id"])

    def tick(self, *, now=None):
        now = stamp(now)
        dispatched, refused = [], []
        for item in self.manager.list():
            if not item["enabled"] or (item["next_run_at"] and item["next_run_at"] > now):
                continue
            try:
                config, schedule = dict(item["config"]), item["schedule"]
                mode = schedule["mode"]
                if mode == "watch":
                    digest = self._hash(config["watch"])
                    if digest == config["last_hash"]:
                        continue
                    config["last_hash"] = digest
                elif mode not in ("once", "interval"):
                    raise ValidationError("unsupported automation schedule")
                next_time = stamp((parse_iso(now) + timedelta(seconds=schedule["seconds"])).isoformat()) if mode == "interval" else None
                job = Job(id=new_id("jb_"), kind="command", title="automation: " + item["name"], status="queued", queue_seq=0,
                          payload={"command": config["command"], "cwd": config["cwd"], "automation_id": item["id"]},
                          created_at=now, timeout_seconds=config["timeout"], max_attempts=1, resource_estimate=DEFAULT_ESTIMATES["command"])
                result = self.manager._write("automation.dispatch", {"id": item["id"], "revision": item["revision"], "now": now,
                    "job": job.to_dict(), "run_id": new_id("ur_"), "next": next_time, "config": config, "enabled": mode != "once"})
                if result["dispatched"]:
                    dispatched.append(result)
            except ArchxError as exc:
                refused.append({"id": item["id"], "reason": str(exc)})
        return {"dispatched": dispatched, "refused": refused}

    def pump(self):
        result = self.tick()
        result["jobs"] = []
        for occurrence in self.manager.runs():
            if occurrence["status"] == "queued":
                job = self.ws.jobs.get(occurrence["job_id"])
                # Scope this worker to automation jobs only; ordinary queue work is untouched.
                if job.payload.get("automation_id"):
                    result["jobs"].append(self.ws.scheduler.execute(job).to_dict())
        return result
