"""ModelManager records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class ModelRecord:
    id: str
    name: str
    provider: str
    runtime: str
    path: str | None
    model_ref: str | None
    format: str | None
    quantization: str | None
    param_count: str | None
    context_length: int | None
    size_bytes: int | None
    sha256: str | None
    facts: dict[str, Any]
    claims: dict[str, Any]
    user_metadata: dict[str, Any]
    verified_capabilities: list[str]
    capability_basis: dict[str, str]
    verification_state: str
    state: str
    tags: list[str]
    notes: str | None
    success_count: int
    failure_count: int
    discovered_at: str
    updated_at: str
    last_used_at: str | None
    last_error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "runtime": self.runtime,
            "path": self.path,
            "model_ref": self.model_ref,
            "format": self.format,
            "quantization": self.quantization,
            "param_count": self.param_count,
            "context_length": self.context_length,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "facts": self.facts,
            "claims": self.claims,
            "user_metadata": self.user_metadata,
            "verified_capabilities": self.verified_capabilities,
            "capability_basis": self.capability_basis,
            "verification_state": self.verification_state,
            "state": self.state,
            "tags": self.tags,
            "notes": self.notes,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "discovered_at": self.discovered_at,
            "updated_at": self.updated_at,
            "last_used_at": self.last_used_at,
            "last_error": self.last_error,
        }

    @property
    def is_usable(self) -> bool:
        return self.state == "usable"

    def supports(self, capability: str) -> bool:
        return capability in self.verified_capabilities

    def preferred_for(self) -> list[str]:
        value = self.user_metadata.get("preferred_for") or []
        return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _from_row(row: dict[str, Any]) -> ModelRecord:
    return ModelRecord(
        id=row["id"],
        name=row["name"],
        provider=row["provider"],
        runtime=row["runtime"],
        path=row["path"],
        model_ref=row["model_ref"],
        format=row["format"],
        quantization=row["quantization"],
        param_count=row["param_count"],
        context_length=row["context_length"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        facts=json.loads(row["facts"]) if row["facts"] else {},
        claims=json.loads(row["claims"]) if row["claims"] else {},
        user_metadata=json.loads(row["user_metadata"]) if row["user_metadata"] else {},
        verified_capabilities=json.loads(row["verified_capabilities"])
        if row["verified_capabilities"]
        else [],
        capability_basis=json.loads(row["capability_basis"])
        if row["capability_basis"]
        else {},
        verification_state=row["verification_state"],
        state=row["state"],
        tags=json.loads(row["tags"]) if row["tags"] else [],
        notes=row["notes"],
        success_count=row["success_count"],
        failure_count=row["failure_count"],
        discovered_at=row["discovered_at"],
        updated_at=row["updated_at"],
        last_used_at=row["last_used_at"],
        last_error=row["last_error"],
    )
