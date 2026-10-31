"""Durable explicit-tick automations. Scheduling enqueues; it never executes or grants authority.

Dispatch atomically inserts the job and occurrence and advances a revision. Missed intervals are
coalesced, not replayed as a backlog. Watches compare file hashes through the permissioned tools.
"""
from __future__ import annotations

from archx_agent.managers.automations import AutomationManager as AutomationManager

from datetime import timedelta, timezone

from archx_agent.helpers.exceptions import ArchxError, ConflictError, ValidationError
from archx_agent.helpers.timeutil import iso_now, parse_iso, new_id
from archx_agent.managers.jobs import Job, DEFAULT_ESTIMATES
from archx_agent.managers.tools import ToolContext


def stamp(value=None):
    if value is not None and not isinstance(value, str):
        raise ValidationError("schedule time must be an ISO timestamp string")
    try:
        dt = parse_iso(iso_now() if value is None else value)
        if dt.tzinfo is None:
            raise ValueError("timezone required")
        return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, TypeError) as exc:
        raise ValidationError("schedule time must be an ISO timestamp with timezone") from exc




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
        if not isinstance(command, list) or not command or any(not isinstance(x, str) or "\x00" in x for x in command) or not command[0]:
            raise ValidationError("command must be a nonempty JSON argv array")
        if sum(value is not None for value in (interval, at, watch)) != 1:
            raise ValidationError("choose exactly one interval, at timestamp, or watch path")
        if type(timeout) is not int or not 1 <= timeout <= 86400:
            raise ValidationError("timeout must be an integer from 1 to 86400")
        if cwd is not None and not isinstance(cwd, str):
            raise ValidationError("cwd must be a tool-root directory path")
        if watch is not None and (not isinstance(watch, str) or not watch):
            raise ValidationError("watch must be a nonempty file path")
        if not self.ws.tools.roots():
            raise ValidationError("automations need a configured tool root")
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
        if not self.ws.config.get("automations.enabled", True):
            return {"dispatched": [], "refused": [{"id": None, "reason": "automations.enabled is false"}]}
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
        if not self.ws.config.get("automations.enabled", True):
            return result
        for occurrence in self.manager.runs():
            if occurrence["status"] == "queued":
                job = self.ws.jobs.get(occurrence["job_id"])
                # Scope this worker to automation jobs only; ordinary queue work is untouched.
                if job.payload.get("automation_id"):
                    try:
                        result["jobs"].append(self.ws.scheduler.execute(job).to_dict())
                    except ConflictError:
                        # Another worker claimed it after our snapshot. The queue owns the claim.
                        continue
        return result
