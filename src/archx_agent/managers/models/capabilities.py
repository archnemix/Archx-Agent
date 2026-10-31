"""ModelManager capabilities."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.models.constants import RUNTIME_BASELINE_CAPABILITIES
from archx_agent.managers.models.records import ModelRecord


class ModelManagerCapabilitiesMixin:
    """Capabilities responsibility for ModelManager."""

    def record_capability_test(
        self,
        model_id: str,
        capability: str,
        outcome: str,
        *,
        detail: str | None = None,
        latency_ms: float | None = None,
        resources: dict[str, Any] | None = None,
    ) -> None:
        if outcome not in ("passed", "failed", "skipped"):
            raise ValidationError(f"unknown capability test outcome {outcome!r}")
        self._write(
            "model.capability_test",
            {
                "model_id": model_id,
                "capability": capability,
                "outcome": outcome,
                "detail": detail,
                "latency_ms": latency_ms,
                "resources": resources or {},
                "run_at": iso_now(),
            },
        )

    def latest_tests(self, model_id: str) -> dict[str, dict[str, Any]]:
        """Most recent capability test per capability (latest row wins)."""
        record = self.require(model_id)
        floor = int(record.facts.get("capability_test_floor") or 0)
        rows = self.store.query(
            "SELECT capability, outcome, detail, latency_ms, run_at FROM model_capability_tests"
            " WHERE model_id = ? AND id > ? ORDER BY id DESC",
            (model_id, floor),
        )
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest.setdefault(row["capability"], row)
        return latest

    def capability_state(self, record: ModelRecord, capability: str) -> dict[str, Any]:
        """Classify one capability of one model, with the evidence behind it.

        Precedence (strongest first): a recorded probe, then the runtime baseline,
        then the declared basis, then "no evidence". A failed probe beats everything
        else - once we have measured a capability as broken, claims cannot override it.
        """
        if not record.is_usable:
            return {
                "state": "unavailable",
                "basis": f"model state is {record.state}",
                "detail": record.last_error,
            }
        tests = self.latest_tests(record.id)
        test = tests.get(capability)
        if test and test["outcome"] == "failed":
            return {
                "state": "unsupported",
                "basis": "probe failed",
                "detail": test.get("detail"),
                "tested_at": test.get("run_at"),
            }
        if test and test["outcome"] == "passed":
            return {
                "state": "verified",
                "basis": "probe passed",
                "detail": test.get("detail"),
                "tested_at": test.get("run_at"),
                "latency_ms": test.get("latency_ms"),
            }
        declared = (record.capability_basis or {}).get(capability)
        if capability in RUNTIME_BASELINE_CAPABILITIES.get(record.runtime, frozenset()):
            return {
                "state": "inferred",
                "basis": f"the {record.runtime} adapter implements {capability}",
                "detail": None,
            }
        if declared == "verified":
            # A human marked it verified without a probe; treat as inferred-by-user.
            return {
                "state": "inferred",
                "basis": "recorded by the user",
                "detail": None,
            }
        if declared == "unsupported":
            return {
                "state": "unsupported",
                "basis": "recorded as unsupported",
                "detail": None,
            }
        if declared == "unavailable":
            return {
                "state": "unavailable",
                "basis": "recorded as unavailable",
                "detail": None,
            }
        if capability in (record.verified_capabilities or []) or declared:
            return {
                "state": "unverified",
                "basis": declared or "claimed",
                "detail": None,
            }
        return {"state": "unverified", "basis": "no evidence", "detail": None}

    def capability_matrix(self, model_id: str) -> dict[str, dict[str, Any]]:
        record = self.require(model_id)
        declared = set(record.verified_capabilities or []) | set(
            record.capability_basis or {}
        )
        baseline = set(RUNTIME_BASELINE_CAPABILITIES.get(record.runtime, frozenset()))
        tested = set(self.latest_tests(record.id))
        capabilities = sorted(declared | baseline | tested)
        return {cap: self.capability_state(record, cap) for cap in capabilities}

    def capability_history(self, model_id: str) -> list[dict[str, Any]]:
        return self.store.query(
            "SELECT capability, outcome, detail, latency_ms, run_at FROM model_capability_tests"
            " WHERE model_id = ? ORDER BY id DESC",
            (model_id,),
        )
