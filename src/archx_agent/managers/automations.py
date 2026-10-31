"""Automation persistence: transactional definitions, occurrences and atomic job dispatch.

Scheduling and tool access belong to application.automations, not this manager.
"""

from __future__ import annotations

import json


from archx_agent.helpers.exceptions import ValidationError, NotFoundError


from archx_agent.managers.base import BaseManager


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
        tx.execute(
            "INSERT INTO automations(id,name,kind,schedule,enabled,config,created_at,updated_at,next_run_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                item["id"],
                item["name"],
                "command",
                json.dumps(item["schedule"]),
                0,
                json.dumps(item["config"]),
                item["created_at"],
                item["created_at"],
                item["next_run_at"],
            ),
        )
        return {"id": item["id"]}

    def _enable(self, tx, payload):
        tx.execute(
            "UPDATE automations SET enabled=?,revision=revision+1,updated_at=? WHERE id=?",
            (int(payload["enabled"]), payload["now"], payload["id"]),
        )
        return {"id": payload["id"]}

    def _dispatch(self, tx, payload):
        rows = tx.query("SELECT * FROM automations WHERE id=?", (payload["id"],))
        if (
            not rows
            or not rows[0]["enabled"]
            or rows[0]["revision"] != payload["revision"]
        ):
            return {"dispatched": False}
        row = rows[0]
        if tx.query(
            "SELECT r.id FROM automation_runs r JOIN jobs j ON j.id=r.job_id WHERE r.automation_id=? AND j.status IN ('queued','running','paused') LIMIT 1",
            (row["id"],),
        ):
            return {"dispatched": False}
        if row["next_run_at"] and row["next_run_at"] > payload["now"]:
            return {"dispatched": False}
        # Reuse the queue's transaction handler, not its public separately-committed enqueue.
        # Job, occurrence, next deadline and revision either all commit or all roll back.
        job_result = self.jobs._apply_enqueue(tx, {"job": payload["job"]})
        tx.execute(
            "INSERT INTO automation_runs(id,automation_id,status,started_at,output,job_id) VALUES (?,?,?,?,?,?)",
            (
                payload["run_id"],
                row["id"],
                "queued",
                payload["now"],
                json.dumps({"job_id": job_result["id"]}),
                job_result["id"],
            ),
        )
        tx.execute(
            "UPDATE automations SET next_run_at=?,last_run_at=?,last_status='queued',config=?,enabled=?,revision=revision+1,updated_at=? WHERE id=?",
            (
                payload["next"],
                payload["now"],
                json.dumps(payload["config"]),
                payload["enabled"],
                payload["now"],
                row["id"],
            ),
        )
        return {
            "dispatched": True,
            "run_id": payload["run_id"],
            "job_id": job_result["id"],
        }

    def get(self, wanted):
        row = self.store.query_one(
            "SELECT * FROM automations WHERE id=? OR name=? ORDER BY rowid DESC LIMIT 1",
            (wanted, wanted),
        )
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
        return [
            self.decode(row)
            for row in self.store.query("SELECT * FROM automations ORDER BY rowid")
        ]

    def runs(self, wanted=None):
        rows = (
            self.store.query(
                "SELECT * FROM automation_runs WHERE automation_id=? ORDER BY rowid DESC",
                (self.get(wanted)["id"],),
            )
            if wanted
            else self.store.query("SELECT * FROM automation_runs ORDER BY rowid DESC")
        )
        result = []
        for row in rows:
            data = dict(row)
            job_id = json.loads(data.get("output") or "{}").get("job_id")
            if job_id:
                job = self.jobs.get(job_id)
                data.update(
                    job_id=job_id,
                    status=job.status,
                    error=job.error,
                    task_id=job.task_id,
                )
            result.append(data)
        return result
