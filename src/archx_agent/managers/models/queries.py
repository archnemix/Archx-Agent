"""ModelManager queries."""

from __future__ import annotations

from typing import Any, Sequence

from archx_agent.helpers.exceptions import NotFoundError
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.managers.models.records import ModelRecord, _from_row


class ModelManagerQueriesMixin:
    """Queries responsibility for ModelManager."""

    def get(self, model_id: str) -> Result[ModelRecord]:
        row = self.store.query_one("SELECT * FROM models WHERE id = ?", (model_id,))
        if row is None:
            return Err(NotFoundError(f"model {model_id} not found", id=model_id))
        return Ok(_from_row(row))

    def require(self, model_id: str) -> ModelRecord:
        return self.get(model_id).ok_or_raise()

    def by_name(self, name: str) -> Result[ModelRecord]:
        row = self.store.query_one("SELECT * FROM models WHERE name = ?", (name,))
        if row is None:
            return Err(NotFoundError(f"model {name!r} not found", name=name))
        return Ok(_from_row(row))

    def list(
        self,
        *,
        state: str | None = None,
        provider: str | None = None,
        runtime: str | None = None,
        capability: str | None = None,
        include_removed: bool = False,
        limit: int = 200,
    ) -> list[ModelRecord]:
        clauses, params = [], []
        if state:
            clauses.append("state = ?")
            params.append(state)
        if provider:
            clauses.append("provider = ?")
            params.append(provider)
        if runtime:
            clauses.append("runtime = ?")
            params.append(runtime)
        if not include_removed:
            clauses.append("state != 'removed'")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.store.query(
            f"SELECT * FROM models{where} ORDER BY name LIMIT ?", (*params, limit)
        )
        records = [_from_row(r) for r in rows]
        if capability:
            records = [r for r in records if r.supports(capability)]
        return records

    def preferred_for(self, task: str) -> ModelRecord | None:
        for record in self.list():
            if task in record.preferred_for():
                return record
        return None

    def compare(self, model_ids: Sequence[str]) -> list[dict[str, Any]]:
        out = []
        for model_id in model_ids:
            record = self.get(model_id)
            if record.is_err:
                continue
            m = record.value
            out.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "provider": m.provider,
                    "state": m.state,
                    "context_length": m.context_length,
                    "size_bytes": m.size_bytes,
                    "verified_capabilities": m.verified_capabilities,
                    "verification_state": m.verification_state,
                    "success_count": m.success_count,
                    "failure_count": m.failure_count,
                    "preferred_for": m.preferred_for(),
                }
            )
        return out

    def storage_summary(self) -> dict[str, Any]:
        rows = self.store.query(
            "SELECT provider, state, COUNT(*) n, COALESCE(SUM(size_bytes),0) bytes FROM models GROUP BY provider, state"
        )
        return {"groups": rows, "total_bytes": sum(r["bytes"] for r in rows)}
