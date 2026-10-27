"""Model catalogue (M15) and discovery.

Three kinds of information are stored **separately** and never conflated:

* ``facts`` - things we observed (file size, hash, path exists, a capability
  test that returned valid output);
* ``claims`` - things a model card, filename or provider says (unverified);
* ``user_metadata`` - what the user chose (preferred for task X, notes, tags).

A model is ``usable`` only when the file exists (local) or the endpoint is
configured (remote). Capabilities are ``verified`` only by a recorded test, or
``inferred`` from metadata, or ``unverified``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text, sha256_file
from archx_agent.helpers.paths import ensure_directory
from archx_agent.helpers.result import Err, Ok, Result
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

MODEL_TABLES = ("models", "model_capability_tests")

STATES = ("usable", "disabled", "missing", "invalid", "removed")
VERIFICATION_STATES = ("verified", "inferred", "unverified", "unsupported", "unavailable")

#: Capability states, strongest first. ``verified`` means a recorded probe of *this*
#: model succeeded; ``inferred`` means it follows from the adapter (a chat adapter
#: implements chat); ``unverified`` means it was claimed and never exercised;
#: ``unsupported`` means a probe ran and failed; ``unavailable`` means the artifact or
#: runtime needed for it is missing.
CAPABILITY_STATES = ("verified", "inferred", "unverified", "unsupported", "unavailable")

#: What a runtime adapter guarantees by construction. This is a statement about our own
#: code, not about a model: any runtime that implements ``chat`` can answer a chat.
RUNTIME_BASELINE_CAPABILITIES: dict[str, frozenset[str]] = {
    "llama-cpp": frozenset({"chat", "streaming"}),
    "openai-http": frozenset({"chat", "streaming"}),
    "http": frozenset({"chat", "streaming"}),
    "scripted": frozenset({"chat", "streaming"}),
}

_QUANT_RE = re.compile(r"(?i)\b(i?q\d(?:_[a-z0-9]+)*|f16|bf16|f32|q8_0|q4_k_m|q5_k_m)\b")
_PARAM_RE = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*[bBmM]\b")


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
        verified_capabilities=json.loads(row["verified_capabilities"]) if row["verified_capabilities"] else [],
        capability_basis=json.loads(row["capability_basis"]) if row["capability_basis"] else {},
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


def parse_gguf_name(filename: str) -> dict[str, Any]:
    """Extract *claims* from a filename. These are claims, never facts."""
    stem = Path(filename).stem
    claims: dict[str, Any] = {"source": "filename"}
    quant = _QUANT_RE.search(stem)
    if quant:
        claims["quantization"] = quant.group(1).upper()
    params = re.search(r"(?i)(\d+(?:\.\d+)?)\s*[bB](?![a-z])", stem)
    if params:
        claims["param_count"] = f"{params.group(1)}B"
    if re.search(r"(?i)instruct|chat|it\b", stem):
        claims["chat"] = True
    if re.search(r"(?i)vision|vl\b|llava", stem):
        claims["vision"] = "claimed"
    if re.search(r"(?i)embed|bge|gte", stem):
        claims["embeddings"] = "claimed"
    return claims


class ModelManager(BaseManager):
    tables = MODEL_TABLES

    def __init__(self, store, coordinator, *, events=None, models_root: str | None = None, hash_files: bool = False) -> None:
        self.models_root = models_root
        self.hash_files = hash_files
        super().__init__(store, coordinator, events=events)

    def register_handlers(self) -> None:
        self.coordinator.register("model.register", self._apply_register)
        self.coordinator.register("model.update", self._apply_update)
        self.coordinator.register("model.delete", self._apply_delete)
        self.coordinator.register("model.usage", self._apply_usage)
        self.coordinator.register("model.capability_test", self._apply_capability_test)

    # -- handlers ---------------------------------------------------------
    def _apply_register(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        m = payload["model"]
        existing = tx.query_one(
            "SELECT id, user_metadata FROM models WHERE provider=? AND COALESCE(path,'')=COALESCE(?,'')"
            " AND COALESCE(model_ref,'')=COALESCE(?,'')",
            (m["provider"], m.get("path"), m.get("model_ref")),
        )
        if existing:
            tx.execute(
                "UPDATE models SET name=?, runtime=?, format=?, quantization=?, param_count=?, context_length=?,"
                " size_bytes=?, sha256=?, facts=?, claims=?, state=?, updated_at=? WHERE id=?",
                (
                    m["name"],
                    m["runtime"],
                    m.get("format"),
                    m.get("quantization"),
                    m.get("param_count"),
                    m.get("context_length"),
                    m.get("size_bytes"),
                    m.get("sha256"),
                    json_text(m.get("facts") or {}),
                    json_text(m.get("claims") or {}),
                    m.get("state", "usable"),
                    m["updated_at"],
                    existing["id"],
                ),
            )
            return {"id": existing["id"], "created": False}
        tx.execute(
            "INSERT INTO models(id, name, provider, runtime, path, model_ref, format, quantization, param_count,"
            " context_length, size_bytes, sha256, facts, claims, user_metadata, verified_capabilities,"
            " capability_basis, verification_state, state, tags, notes, success_count, failure_count,"
            " discovered_at, updated_at, last_used_at, last_error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,NULL,NULL)",
            (
                m["id"],
                m["name"],
                m["provider"],
                m["runtime"],
                m.get("path"),
                m.get("model_ref"),
                m.get("format"),
                m.get("quantization"),
                m.get("param_count"),
                m.get("context_length"),
                m.get("size_bytes"),
                m.get("sha256"),
                json_text(m.get("facts") or {}),
                json_text(m.get("claims") or {}),
                json_text(m.get("user_metadata") or {}),
                json_text(m.get("verified_capabilities") or []),
                json_text(m.get("capability_basis") or {}),
                m.get("verification_state", "unverified"),
                m.get("state", "usable"),
                json_text(m.get("tags") or []),
                m.get("notes"),
                m["discovered_at"],
                m["updated_at"],
            ),
        )
        return {"id": m["id"], "created": True}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "name",
            "state",
            "context_length",
            "user_metadata",
            "verified_capabilities",
            "capability_basis",
            "verification_state",
            "tags",
            "notes",
            "path",
            "model_ref",
            "runtime",
            "provider",
            "last_error",
            "last_used_at",
        }
        sets, params = [], []
        for key, value in payload["fields"].items():
            if key not in allowed:
                raise ValidationError(f"cannot update model field {key!r}")
            if key in {"user_metadata", "capability_basis"}:
                value = json_text(value or {})
            elif key in {"verified_capabilities", "tags"}:
                value = json_text(value or [])
            sets.append(f"{key} = ?")
            params.append(value)
        sets.append("updated_at = ?")
        params.append(iso_now())
        params.append(payload["id"])
        tx.execute(f"UPDATE models SET {', '.join(sets)} WHERE id = ?", params)
        return {"id": payload["id"]}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute("DELETE FROM models WHERE id = ?", (payload["id"],))
        tx.execute("DELETE FROM model_capability_tests WHERE model_id = ?", (payload["id"],))
        return {"id": payload["id"]}

    def _apply_usage(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        column = "success_count" if payload["success"] else "failure_count"
        tx.execute(
            f"UPDATE models SET {column} = {column} + 1, last_used_at = ?, last_error = ? WHERE id = ?",
            (payload["at"], payload.get("error"), payload["id"]),
        )
        return {"id": payload["id"]}

    def _apply_capability_test(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "INSERT INTO model_capability_tests(model_id, capability, outcome, detail, latency_ms, resources, run_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                payload["model_id"],
                payload["capability"],
                payload["outcome"],
                payload.get("detail"),
                payload.get("latency_ms"),
                json_text(payload.get("resources") or {}),
                payload["run_at"],
            ),
        )
        return {"model_id": payload["model_id"]}

    # -- discovery --------------------------------------------------------
    def discover_local(self, directory: str | None = None, *, recursive: bool = True) -> list[ModelRecord]:
        """Scan a directory for GGUF/GGML files and register them as facts."""
        root = Path(directory or self.models_root or "").expanduser()
        if not root or not str(root) or not root.exists():
            return []
        pattern = "**/*.gguf" if recursive else "*.gguf"
        found: list[ModelRecord] = []
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            found.append(self.register_local_file(path))
        if found:
            self.trace("system", "models.discovered", payload={"count": len(found), "root": str(root)})
        return found

    def register_local_file(self, path: str | Path, *, hash_file: str | None = None) -> ModelRecord:
        p = Path(path)
        if not p.exists():
            raise NotFoundError(f"model file not found: {p}", path=str(p))
        size = p.stat().st_size
        state = "usable" if size > 1024 else "invalid"
        claims = parse_gguf_name(p.name)
        digest = None
        if hash_file == "always" or (hash_file is None and self.hash_files):
            digest = sha256_file(p)
        facts = {
            "exists": True,
            "size_bytes": size,
            "suffix": p.suffix.lower(),
            "mtime": iso_now() if False else None,
        }
        record = ModelRecord(
            id=new_id("mdl_"),
            name=p.stem,
            provider="local",
            runtime="llama-cpp",
            path=str(p.resolve()),
            model_ref=None,
            format="gguf" if p.suffix.lower() == ".gguf" else p.suffix.lstrip("."),
            quantization=claims.get("quantization"),
            param_count=claims.get("param_count"),
            context_length=2048,
            size_bytes=size,
            sha256=digest,
            facts=facts,
            claims=claims,
            user_metadata={},
            verified_capabilities=[],
            capability_basis={},
            verification_state="unverified",
            state=state,
            tags=[],
            notes=None,
            success_count=0,
            failure_count=0,
            discovered_at=iso_now(),
            updated_at=iso_now(),
            last_used_at=None,
            last_error=None if state == "usable" else "file too small to be a model",
        )
        result = self._write("model.register", {"model": record.to_dict()})
        return self.require(result["id"])

    # -- registration -----------------------------------------------------
    def register_remote(
        self,
        name: str,
        *,
        provider: str,
        runtime: str = "openai-http",
        model_ref: str | None = None,
        base_url: str | None = None,
        context_length: int = 8192,
        capabilities: Sequence[str] | None = None,
        verification: str = "inferred",
        claims: dict[str, Any] | None = None,
    ) -> ModelRecord:
        if not name.strip():
            raise ValidationError("model name must not be empty")
        if not model_ref:
            raise ValidationError("remote models require model_ref")
        # Identity for a remote model is (provider, model_ref). Registering the same
        # identity for a *different* endpoint used to silently overwrite the first entry,
        # which made two distinct services indistinguishable. Refuse instead.
        existing = self.store.query_one(
            "SELECT id, name, facts FROM models WHERE provider = ? AND path IS NULL AND model_ref = ?"
            " AND state != 'removed'",
            (provider, model_ref),
        )
        if existing is not None:
            previous = json.loads(existing["facts"] or "{}").get("base_url")
            if previous == base_url:
                return self.require(existing["id"])
            raise ConflictError(
                f"provider {provider!r} already has a model {existing['name']!r} with reference "
                f"{model_ref!r} at {previous!r}; keep the model reference unique per endpoint "
                "(or remove the old entry first)",
                model=existing["id"],
            )
        record = ModelRecord(
            id=new_id("mdl_"),
            name=name.strip(),
            provider=provider,
            runtime=runtime,
            path=None,
            model_ref=model_ref,
            format="http",
            quantization=None,
            param_count=None,
            context_length=context_length,
            size_bytes=None,
            sha256=None,
            facts={"configured": True, "base_url": base_url},
            claims=dict(claims or {}),
            user_metadata={},
            verified_capabilities=list(capabilities or []),
            capability_basis={c: verification for c in (capabilities or [])},
            verification_state=verification,
            state="usable",
            tags=[],
            notes=None,
            success_count=0,
            failure_count=0,
            discovered_at=iso_now(),
            updated_at=iso_now(),
            last_used_at=None,
            last_error=None,
        )
        result = self._write("model.register", {"model": record.to_dict()})
        return self.require(result["id"])

    # -- reads ------------------------------------------------------------
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
        rows = self.store.query(f"SELECT * FROM models{where} ORDER BY name LIMIT ?", (*params, limit))
        records = [_from_row(r) for r in rows]
        if capability:
            records = [r for r in records if r.supports(capability)]
        return records

    def refresh_states(self) -> dict[str, int]:
        """Re-check local files; a vanished file becomes ``missing``."""
        changed = {"missing": 0, "restored": 0}
        for record in self.list(state=None, include_removed=False):
            if record.provider != "local" or not record.path:
                continue
            exists = Path(record.path).exists()
            if not exists and record.state in ("usable", "disabled"):
                prior = record.state
                self._write(
                    "model.update",
                    {"id": record.id, "fields": {"state": "missing", "last_error": "model file disappeared"}},
                )
                if prior == "usable":
                    changed["missing"] += 1
            elif exists and record.state == "missing":
                self._write("model.update", {"id": record.id, "fields": {"state": "usable", "last_error": None}})
                changed["restored"] += 1
        return changed

    # -- management -------------------------------------------------------
    def set_enabled(self, model_id: str, enabled: bool) -> ModelRecord:
        record = self.require(model_id)
        if enabled and record.state == "missing":
            raise ValidationError("cannot enable a model whose file is missing")
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
        self.trace("system", "models.removed", payload={"id": model_id, "delete_file": delete_file})
        return "removed"

    def update(self, model_id: str, **fields: Any) -> ModelRecord:
        self.require(model_id)
        self._write("model.update", {"id": model_id, "fields": fields})
        return self.require(model_id)

    def set_preferred_for(self, model_id: str, tasks: Sequence[str]) -> ModelRecord:
        record = self.require(model_id)
        metadata = dict(record.user_metadata)
        metadata["preferred_for"] = list(tasks)
        return self.update(model_id, user_metadata=metadata)

    def preferred_for(self, task: str) -> ModelRecord | None:
        for record in self.list():
            if task in record.preferred_for():
                return record
        return None

    def record_usage(self, model_id: str, *, success: bool, error: str | None = None) -> None:
        self._write("model.usage", {"id": model_id, "success": success, "error": error, "at": iso_now()})

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
        rows = self.store.query(
            "SELECT capability, outcome, detail, latency_ms, run_at FROM model_capability_tests"
            " WHERE model_id = ? ORDER BY id DESC",
            (model_id,),
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
        if not record.is_usable:
            return {
                "state": "unavailable",
                "basis": f"model state is {record.state}",
                "detail": record.last_error,
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
            return {"state": "inferred", "basis": "recorded by the user", "detail": None}
        if declared == "unsupported":
            return {"state": "unsupported", "basis": "recorded as unsupported", "detail": None}
        if declared == "unavailable":
            return {"state": "unavailable", "basis": "recorded as unavailable", "detail": None}
        if capability in (record.verified_capabilities or []) or declared:
            return {"state": "unverified", "basis": declared or "claimed", "detail": None}
        return {"state": "unverified", "basis": "no evidence", "detail": None}

    def capability_matrix(self, model_id: str) -> dict[str, dict[str, Any]]:
        record = self.require(model_id)
        declared = set(record.verified_capabilities or []) | set(record.capability_basis or {})
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


__all__ = ["ModelManager", "ModelRecord", "parse_gguf_name", "STATES", "VERIFICATION_STATES"]
