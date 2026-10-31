"""ResearchManager: lifecycle operations."""

from __future__ import annotations

from typing import Any, Mapping, Sequence
from archx_agent.helpers.exceptions import ConflictError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .records import MODES, STATUSES, TERMINAL, PLANNERS, ResearchRun

class ResearchManagerLifecycleMixin:
    def create(
        self,
        question: str,
        *,
        mode: str = "local",
        plan: Sequence[Mapping[str, Any]] | None = None,
        planned_by: str = "rules",
        report_format: str = "markdown",
        model_id: str | None = None,
        settings: Mapping[str, Any] | None = None,
        task_id: str | None = None,
        status: str = "planning",
    ) -> ResearchRun:
        question = (question or "").strip()
        if len(question) < 4:
            raise ValidationError("a research question needs at least four characters")
        if mode not in MODES:
            raise ValidationError(f"mode must be one of {', '.join(MODES)}")
        if planned_by not in PLANNERS:
            raise ValidationError(f"planned_by must be one of {', '.join(PLANNERS)}")
        if status not in STATUSES:
            raise ValidationError(f"unknown research status {status!r}")
        run_id = new_id("rs_")
        now = iso_now()
        plan_list = [dict(item) for item in (plan or [])]
        self._write(
            "research.create",
            {
                "run": {
                    "id": run_id,
                    "question": question,
                    "status": status,
                    "mode": mode,
                    "plan": plan_list,
                    "subquestions": [item.get("question") for item in plan_list],
                    "planned_by": planned_by,
                    "report_format": report_format,
                    "model_id": model_id,
                    "settings": dict(settings or {}),
                    "task_id": task_id,
                    "created_at": now,
                    "updated_at": now,
                }
            },
        )
        self.trace(
            "research", "research.created", status="ok",
            payload={"run_id": run_id, "mode": mode, "planned_by": planned_by,
                     "subquestions": len(plan_list)},
        )
        return self.get(run_id)

    def update(self, run_id: str, **fields: Any) -> ResearchRun:
        run = self.get(run_id)
        if run.terminal:
            raise ConflictError(f"research run {run_id} is already {run.status}")
        allowed = {
            "status", "plan", "subquestions", "planned_by", "coverage", "evidence_count",
            "report", "report_path", "report_format", "limitations", "error", "model_id",
            "settings", "task_id", "completed_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValidationError(f"cannot update {', '.join(sorted(unknown))}")
        changes: dict[str, Any] = {}
        for name, value in fields.items():
            if name in {"plan", "subquestions", "limitations", "settings"}:
                changes[name] = json_text(value if value is not None else [])
            elif name == "coverage":
                changes[name] = float(value or 0.0)
            elif name == "evidence_count":
                changes[name] = int(value or 0)
            elif name == "status":
                if value not in STATUSES:
                    raise ValidationError(f"unknown research status {value!r}")
                changes[name] = value
            else:
                changes[name] = value
        changes["updated_at"] = iso_now()
        self._write("research.update", {"id": run_id, "fields": changes})
        return self.get(run_id)

    def finish(
        self,
        run_id: str,
        *,
        status: str = "completed",
        report: str | None = None,
        report_path: str | None = None,
        coverage: float | None = None,
        evidence_count: int | None = None,
        limitations: Sequence[str] | None = None,
        error: str | None = None,
    ) -> ResearchRun:
        if status not in TERMINAL:
            raise ValidationError(f"{status!r} is not a terminal research status")
        run = self.get(run_id)
        if run.terminal:
            raise ConflictError(f"research run {run_id} is already {run.status}")
        fields: dict[str, Any] = {
            "status": status,
            "completed_at": iso_now(),
            "report": report if report is not None else run.report,
            "report_path": report_path if report_path is not None else run.report_path,
            "coverage": coverage if coverage is not None else run.coverage,
            "evidence_count": evidence_count if evidence_count is not None else run.evidence_count,
            "limitations": list(limitations if limitations is not None else run.limitations),
            "error": error,
        }
        jsonish = {"limitations"}
        changes: dict[str, Any] = {}
        for name, value in fields.items():
            changes[name] = json_text(value) if name in jsonish else value
        changes["updated_at"] = iso_now()
        self._write("research.update", {"id": run_id, "fields": changes})
        self.trace(
            "research", "research.finished", status="ok" if status == "completed" else "warn",
            payload={"run_id": run_id, "status": status,
                     "coverage": float(coverage or 0.0),
                     "evidence": int(evidence_count or 0)},
        )
        return self.get(run_id)

    def close(self, run_id: str, *, note: str | None = None, by: str = "user:cli") -> ResearchRun:
        """Mark a question done. This is the user's call; the runner never sets it.

        The run's own status stays what the runner reported - closing records that *you* are
        finished with the question, whatever the coverage turned out to be.
        """
        run = self.get(run_id)
        if run.closed:
            raise ConflictError(f"research run {run_id} was already closed at {run.closed_at}")
        changes = {
            "closed_at": iso_now(),
            "closed_note": (note or "").strip() or None,
            "updated_at": iso_now(),
        }
        self._write("research.update", {"id": run_id, "fields": changes})
        self.trace(
            "research", "research.closed", status="ok",
            payload={"run_id": run_id, "by": by, "status": run.status,
                     "coverage": float(run.coverage or 0.0)},
        )
        return self.get(run_id)

    def reopen(self, run_id: str, *, by: str = "user:cli") -> ResearchRun:
        """Undo a close. A run that was never closed is a conflict, not a silent no-op."""
        run = self.get(run_id)
        if not run.closed:
            raise ConflictError(f"research run {run_id} is not closed")
        self._write("research.update", {
            "id": run_id,
            "fields": {"closed_at": None, "closed_note": None, "updated_at": iso_now()},
        })
        self.trace(
            "research", "research.reopened", status="ok",
            payload={"run_id": run_id, "by": by},
        )
        return self.get(run_id)

    def delete(self, run_id: str) -> dict[str, Any]:
        """Delete a run and its sources. Traces and the task record are left alone."""
        self.get(run_id)
        result = self._write("research.delete", {"id": run_id})
        self.trace("research", "research.deleted", status="ok", payload={"run_id": run_id})
        return result
