"""ModelManager writes."""

from __future__ import annotations

import json
from typing import Any

from archx_agent.managers.models.files import file_changed

from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now


class ModelManagerWritesMixin:
    """Writes responsibility for ModelManager."""

    def register_handlers(self) -> None:
        self.coordinator.register(
            "model.file_observation", self._apply_file_observation
        )
        self.coordinator.register("model.register", self._apply_register)
        self.coordinator.register("model.update", self._apply_update)
        self.coordinator.register("model.delete", self._apply_delete)
        self.coordinator.register("model.usage", self._apply_usage)
        self.coordinator.register("model.capability_test", self._apply_capability_test)

    def _apply_register(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        m = payload["model"]
        existing = tx.query_one(
            "SELECT * FROM models WHERE provider=? AND COALESCE(path,'')=COALESCE(?,'')"
            " AND COALESCE(model_ref,'')=COALESCE(?,'')",
            (m["provider"], m.get("path"), m.get("model_ref")),
        )
        if existing:
            if m["provider"] == "local":
                self._apply_file_observation(
                    tx,
                    {
                        "id": existing["id"],
                        "observation": {
                            "facts": m["facts"],
                            "state": m["state"],
                            "error": m.get("last_error"),
                            "sha256": m.get("sha256"),
                        },
                    },
                )
            return {"id": existing["id"], "created": False}
        tx.execute(
            "INSERT INTO models(id, name, provider, runtime, path, model_ref, format, quantization, param_count,"
            " context_length, size_bytes, sha256, facts, claims, user_metadata, verified_capabilities,"
            " capability_basis, verification_state, state, tags, notes, success_count, failure_count,"
            " discovered_at, updated_at, last_used_at, last_error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,NULL,?)",
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
                m.get("last_error"),
            ),
        )
        return {"id": m["id"], "created": True}

    def _apply_file_observation(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        row = tx.query_one("SELECT * FROM models WHERE id = ?", (payload["id"],))
        if row is None:
            raise ValidationError("model no longer exists")
        observation = payload["observation"]
        previous_facts = json.loads(row["facts"] or "{}")
        facts = {**previous_facts, **observation["facts"]}
        disabled = (
            bool(previous_facts.get("user_disabled")) or row["state"] == "disabled"
        )
        facts["user_disabled"] = disabled
        state = (
            "disabled"
            if disabled and observation["state"] == "usable"
            else observation["state"]
        )
        digest = observation.get("sha256")
        # Re-discovery without hashing need not erase an existing digest if the
        # observed identity is unchanged. A changed identity never keeps that digest.
        if digest is None and previous_facts.get("file_signature") == facts.get(
            "file_signature"
        ):
            digest = row["sha256"]
        changed = file_changed(
            {"facts": previous_facts, "sha256": row["sha256"]},
            {**observation, "sha256": digest},
        )
        if changed:
            facts["capability_test_floor"] = int(
                tx.scalar(
                    "SELECT COALESCE(MAX(id), 0) FROM model_capability_tests WHERE model_id = ?",
                    (row["id"],),
                )
            )
        # A filesystem refresh must not erase an unrelated inference failure on
        # unchanged bytes. Clear old availability errors only when they recover.
        last_error = observation.get("error")
        if (
            not changed
            and row["state"] in ("usable", "disabled")
            and state in ("usable", "disabled")
        ):
            last_error = row["last_error"]
        # Historical tests remain queryable but cannot authorize replaced bytes.
        tx.execute(
            "UPDATE models SET state=?, facts=?, size_bytes=?, sha256=?, last_error=?, updated_at=?,"
            " verified_capabilities=?, capability_basis=?, verification_state=? WHERE id=?",
            (
                state,
                json_text(facts),
                facts["size_bytes"],
                digest,
                last_error,
                iso_now(),
                "[]" if changed else row["verified_capabilities"],
                "{}" if changed else row["capability_basis"],
                "unverified" if changed else row["verification_state"],
                row["id"],
            ),
        )
        return {"id": row["id"], "previous_state": row["state"], "state": state}

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
            "size_bytes",
            "sha256",
            # `facts` is how an endpoint is described (base_url, api_version). It was
            # readable but not writable, so `models add-gemini` could set a base_url once and
            # never correct it.
            "facts",
        }
        sets, params = [], []
        for key, value in payload["fields"].items():
            if key not in allowed:
                raise ValidationError(f"cannot update model field {key!r}")
            if key in {"user_metadata", "capability_basis", "facts"}:
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
        tx.execute(
            "DELETE FROM model_capability_tests WHERE model_id = ?", (payload["id"],)
        )
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
