"""Transactional write handlers for memory governance."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text


class MemoryManagerWritesMixin:
    """Writes responsibility for MemoryManager."""

    def register_handlers(self) -> None:
        self.coordinator.register("memory.add", self._apply_add)
        self.coordinator.register("memory.update", self._apply_update)
        self.coordinator.register("memory.status", self._apply_status)
        self.coordinator.register("memory.delete", self._apply_delete)
        self.coordinator.register("memory.source", self._apply_source)
        self.coordinator.register("memory.artifact", self._apply_artifact)

    def _apply_add(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        m = payload["memory"]
        superseded = payload.get("supersede_ids") or []
        for old_id in superseded:
            tx.execute(
                "UPDATE memories SET status='superseded', updated_at=? WHERE id=?",
                (m["created_at"], old_id),
            )
            tx.execute(
                "INSERT INTO memory_history(memory_id, version, change, snapshot, changed_at)"
                " SELECT id, version, 'superseded', '{}', ? FROM memories WHERE id=?",
                (m["created_at"], old_id),
            )
        tx.execute(
            "INSERT INTO memories(id, kind, scope, scope_id, slot, title, content, summary, category,"
            " project_id, conversation_id, task_id, source, provenance, confidence, status, pinned, tags,"
            " details, evidence, verification, environment, limitations, worked, expires_at,"
            " last_accessed_at, access_count, duplicate_of, supersedes, version, embedding_state,"
            " embedding_ref, artifact_path, checksum, created_at, updated_at, deleted_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                m["id"],
                m["kind"],
                m["scope"],
                m.get("scope_id"),
                m.get("slot"),
                m["title"],
                m["content"],
                m.get("summary"),
                m["category"],
                m.get("project_id"),
                m.get("conversation_id"),
                m.get("task_id"),
                m["source"],
                json_text(m.get("provenance") or {}),
                m.get("confidence", 0.8),
                m.get("status", "active"),
                int(bool(m.get("pinned"))),
                json_text(m.get("tags") or []),
                json_text(m.get("details") or {}),
                json_text(m.get("evidence") or []),
                m.get("verification"),
                m.get("environment"),
                m.get("limitations"),
                None if m.get("worked") is None else int(bool(m["worked"])),
                m.get("expires_at"),
                None,
                0,
                m.get("duplicate_of"),
                m.get("supersedes"),
                1,
                m.get("embedding_state", "awaiting"),
                None,
                m.get("artifact_path"),
                m.get("checksum"),
                m["created_at"],
                m["updated_at"],
                None,
            ),
        )
        return {"id": m["id"], "superseded": superseded}

    def _apply_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        memory_id = payload["id"]
        fields = payload["fields"]
        row = tx.query_one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        if row is None:
            raise NotFoundError(f"memory {memory_id} not found", id=memory_id)
        tx.execute(
            "INSERT INTO memory_history(memory_id, version, change, snapshot, changed_at) VALUES (?,?,?,?,?)",
            (
                memory_id,
                row["version"],
                payload.get("change", "update"),
                json_text(row),
                payload["now"],
            ),
        )
        allowed = {
            "title",
            "content",
            "summary",
            "category",
            "status",
            "pinned",
            "tags",
            "details",
            "evidence",
            "verification",
            "environment",
            "limitations",
            "worked",
            "expires_at",
            "confidence",
            "slot",
            "checksum",
            "embedding_state",
            "embedding_ref",
        }
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValidationError(f"cannot update memory field {key!r}")
            if key in {"tags", "details", "evidence"}:
                value = json_text(value or ({} if key == "details" else []))
            elif key in {"pinned"}:
                value = int(bool(value))
            elif key == "worked":
                value = None if value is None else int(bool(value))
            sets.append(f"{key} = ?")
            params.append(value)
        sets.extend(["version = version + 1", "updated_at = ?"])
        params.append(payload["now"])
        params.append(memory_id)
        tx.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id = ?", params)
        return {"id": memory_id, "version": int(row["version"]) + 1}

    def _apply_status(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        for memory_id in payload["ids"]:
            row = tx.query_one(
                "SELECT version FROM memories WHERE id = ?", (memory_id,)
            )
            if row is None:
                continue
            tx.execute(
                "INSERT INTO memory_history(memory_id, version, change, snapshot, changed_at)"
                " SELECT id, version, ?, '{}', ? FROM memories WHERE id = ?",
                (payload["status"], payload["now"], memory_id),
            )
            tx.execute(
                "UPDATE memories SET status=?, updated_at=? WHERE id=?",
                (payload["status"], payload["now"], memory_id),
            )
        return {"updated": len(payload["ids"])}

    def _apply_delete(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        memory_id = payload["id"]
        if payload.get("hard"):
            tx.execute(
                "INSERT INTO memory_history(memory_id, version, change, snapshot, changed_at)"
                " SELECT id, version, 'hard_deleted', ?, ? FROM memories WHERE id = ?",
                (
                    json_text({"checksum": payload.get("checksum")}),
                    payload["now"],
                    memory_id,
                ),
            )
            tx.execute("DELETE FROM memory_sources WHERE memory_id = ?", (memory_id,))
            tx.execute(
                "DELETE FROM memory_retrievals WHERE memory_id = ?", (memory_id,)
            )
            tx.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return {"id": memory_id, "hard": True}
        tx.execute(
            "UPDATE memories SET status='deleted', deleted_at=?, updated_at=? WHERE id=?",
            (payload["now"], payload["now"], memory_id),
        )
        tx.execute(
            "INSERT INTO memory_history(memory_id, version, change, snapshot, changed_at)"
            " SELECT id, version, 'deleted', '{}', ? FROM memories WHERE id = ?",
            (payload["now"], memory_id),
        )
        return {"id": memory_id, "hard": False}

    def _apply_source(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "INSERT INTO memory_sources(memory_id, source_type, reference, excerpt, retrieved_at, checksum)"
            " VALUES (?,?,?,?,?,?)",
            (
                payload["memory_id"],
                payload["source_type"],
                payload.get("reference"),
                payload.get("excerpt"),
                payload["now"],
                payload.get("checksum"),
            ),
        )
        return {"memory_id": payload["memory_id"]}

    def _apply_artifact(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        tx.execute(
            "UPDATE memories SET artifact_path = ?, checksum = ?, updated_at = ? WHERE id = ?",
            (
                payload["path"],
                payload["checksum"],
                payload["now"],
                payload["memory_id"],
            ),
        )
        return {"memory_id": payload["memory_id"], "path": payload["path"]}
