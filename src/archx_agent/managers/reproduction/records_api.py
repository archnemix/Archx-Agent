"""ReproductionManager: records api operations."""

from __future__ import annotations
from typing import Any
from archx_agent.helpers.exceptions import NotFoundError
from archx_agent.helpers.result import Result
from archx_agent.helpers.timeutil import iso_now, new_id
from .records import _RANK, Reproduction, _from_row


class ReproductionManagerRecordsApiMixin:
    def capture(
        self,
        task_id: str,
        *,
        recorded_by: str = "user:cli",
    ) -> Reproduction:
        planned = self.assess(task_id)
        repro = Reproduction(
            id=new_id("rp_"),
            task_id=task_id,
            fidelity=planned["fidelity"],
            issues=planned["issues"],
            environment=planned["environment"],
            commands=planned["commands"],
            created_at=iso_now(),
            app_version=self.app_version,
            recorded_by=recorded_by,
        )
        self._write("reproduction.record", {"repro": repro.to_dict()})
        self.trace(
            "task",
            "task.reproduction",
            status="ok" if repro.fidelity != "impossible" else "warning",
            task_id=task_id,
            payload={
                "reproduction_id": repro.id,
                "fidelity": repro.fidelity,
                "blockers": [b["code"] for b in repro.blockers],
            },
        )
        return repro

    def records(
        self, task_id: str | None = None, *, limit: int = 20
    ) -> list[Reproduction]:
        if task_id:
            rows = self.store.query(
                "SELECT * FROM reproduction_records WHERE task_id = ?"
                " ORDER BY rowid DESC LIMIT ?",
                (task_id, int(limit)),
            )
        else:
            rows = self.store.query(
                "SELECT * FROM reproduction_records ORDER BY rowid DESC LIMIT ?",
                (int(limit),),
            )
        return [_from_row(row) for row in rows]

    def latest(self, task_id: str) -> Reproduction | None:
        rows = self.records(task_id, limit=1)
        return rows[0] if rows else None

    def get(self, repro_id: str) -> Result[Reproduction]:
        row = self.store.query_one(
            "SELECT * FROM reproduction_records WHERE id = ?", (repro_id,)
        )
        if row is None:
            return Result.err(NotFoundError(f"no reproduction record {repro_id}"))
        return Result.ok(_from_row(row))

    def verify(self, repro_id: str) -> dict[str, Any]:
        """Re-derive the fidelity now and compare it with the record."""
        record = self.get(repro_id).ok_or_raise()
        current = self.assess(record.task_id)
        recorded_codes = {issue["code"] for issue in record.issues}
        current_codes = {issue["code"] for issue in current["issues"]}
        settings = record.environment.get("settings") or {}
        settings_now = current["environment"]["settings"]
        changed_settings = {
            key: {"recorded": settings.get(key), "now": settings_now.get(key)}
            for key in set(settings) | set(settings_now)
            if settings.get(key) != settings_now.get(key)
        }
        return {
            "reproduction_id": record.id,
            "task_id": record.task_id,
            "recorded": record.fidelity,
            "current": current["fidelity"],
            "changed": _RANK[current["fidelity"]] > _RANK[record.fidelity],
            "improved": _RANK[current["fidelity"]] < _RANK[record.fidelity],
            "new_blockers": sorted(current_codes - recorded_codes),
            "resolved": sorted(recorded_codes - current_codes),
            "changed_settings": changed_settings,
            "issues": current["issues"],
            "commands": current["commands"],
        }

    def stats(self) -> dict[str, Any]:
        rows = self.store.query(
            "SELECT fidelity, COUNT(*) AS n FROM reproduction_records GROUP BY fidelity",
            (),
        )
        return {
            "total": sum(int(row["n"]) for row in rows),
            "by_fidelity": {row["fidelity"]: int(row["n"]) for row in rows},
        }
