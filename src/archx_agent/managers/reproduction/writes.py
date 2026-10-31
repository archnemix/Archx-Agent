"""ReproductionManager: writes operations."""

from __future__ import annotations
from typing import Any
from archx_agent.helpers.jsonio import json_text


class ReproductionManagerWritesMixin:
    def register_handlers(self) -> None:
        self.coordinator.register("reproduction.record", self._apply_record)

    def _apply_record(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        r = payload["repro"]
        tx.execute(
            "INSERT INTO reproduction_records(id, task_id, fidelity, blockers, environment,"
            " commands, created_at, app_version, recorded_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                r["id"],
                r["task_id"],
                r["fidelity"],
                json_text(r["issues"]),
                json_text(r["environment"]),
                json_text(r["commands"]),
                r["created_at"],
                r.get("app_version"),
                r.get("recorded_by"),
            ),
        )
        return {"id": r["id"], "fidelity": r["fidelity"]}
