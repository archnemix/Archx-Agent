"""ModelManager metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.models.constants import VERIFICATION_STATES
from archx_agent.managers.models.files import observe_file
from archx_agent.managers.models.records import ModelRecord


class ModelManagerMetadataMixin:
    """Metadata responsibility for ModelManager."""

    def set_enabled(self, model_id: str, enabled: bool) -> ModelRecord:
        record = self.require(model_id)
        if record.provider == "local" and record.path:
            observation = observe_file(
                Path(record.path), hash_file=bool(record.sha256) or self.hash_files
            )
            self._write(
                "model.file_observation", {"id": record.id, "observation": observation}
            )
            record = self.require(model_id)
            if enabled and observation["state"] != "usable":
                raise ValidationError(f"cannot enable model: {observation['error']}")
            state = (
                ("usable" if enabled else "disabled")
                if observation["state"] == "usable"
                else observation["state"]
            )
            return self.update(
                model_id, state=state, facts={"user_disabled": not enabled}
            )
        if enabled and record.state in ("missing", "invalid", "removed"):
            raise ValidationError(
                f"cannot enable a model whose state is {record.state}"
            )
        return self.update(model_id, state="usable" if enabled else "disabled")

    def set_verified_capabilities(
        self,
        model_id: str,
        capabilities: Iterable[str],
        *,
        basis: str = "verified by capability test",
        verification_state: str = "verified",
    ) -> ModelRecord:
        if verification_state not in VERIFICATION_STATES:
            raise ValidationError(f"unknown verification state {verification_state!r}")
        caps = sorted({c for c in capabilities})
        record = self.require(model_id)
        new_basis = dict(record.capability_basis)
        for cap in caps:
            new_basis[cap] = basis
        return self.update(
            model_id,
            verified_capabilities=caps,
            capability_basis=new_basis,
            verification_state=verification_state,
        )

    def remove(self, model_id: str, *, delete_file: bool = False) -> str:
        record = self.require(model_id)
        if delete_file:
            if record.provider != "local" or not record.path:
                raise ValidationError("only local model files can be deleted")
            path = Path(record.path)
            if path.exists():
                path.unlink()
            self.trace("system", "models.file_deleted", payload={"path": str(path)})
        self._write("model.delete", {"id": model_id})
        self.trace(
            "system",
            "models.removed",
            payload={"id": model_id, "delete_file": delete_file},
        )
        return "removed"

    def update(self, model_id: str, **fields: Any) -> ModelRecord:
        """Change one model row. Nested metadata is *merged*, not replaced."""
        current = self.require(model_id)
        if "user_metadata" in fields and fields["user_metadata"] is not None:
            merged = dict(current.user_metadata)
            merged.update(fields["user_metadata"])
            fields["user_metadata"] = merged
        if "facts" in fields and fields["facts"] is not None:
            merged_facts = dict(current.facts or {})
            merged_facts.update(fields["facts"])
            fields["facts"] = merged_facts
        self._write("model.update", {"id": model_id, "fields": fields})
        return self.require(model_id)

    def set_preferred_for(self, model_id: str, tasks: Sequence[str]) -> ModelRecord:
        record = self.require(model_id)
        metadata = dict(record.user_metadata)
        metadata["preferred_for"] = list(tasks)
        return self.update(model_id, user_metadata=metadata)

    def record_usage(
        self, model_id: str, *, success: bool, error: str | None = None
    ) -> None:
        self._write(
            "model.usage",
            {"id": model_id, "success": success, "error": error, "at": iso_now()},
        )
