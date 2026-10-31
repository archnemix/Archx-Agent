"""Lifecycle operations for memory governance."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from archx_agent.helpers import redaction
from archx_agent.helpers.exceptions import NotFoundError, PathError, ValidationError
from archx_agent.helpers.jsonio import sha256_bytes, sha256_text
from archx_agent.helpers.paths import child_path, ensure_directory, safe_filename
from archx_agent.helpers.timeutil import iso_from_ts, iso_now
from archx_agent.managers.memory.constants import (
    VERIFICATION_STATES,
    SOURCE_TYPES,
    MAX_TITLE,
    MAX_CONTENT,
)
from archx_agent.managers.memory.records import Memory


class MemoryManagerLifecycleMixin:
    """Lifecycle responsibility for MemoryManager."""

    def update(
        self,
        memory_id: str,
        *,
        change: str = "update",
        **fields: Any,
    ) -> Memory:
        memory = self.require(memory_id)
        if "title" in fields and (
            not fields["title"] or len(fields["title"]) > MAX_TITLE
        ):
            raise ValidationError(f"memory title must be 1-{MAX_TITLE} characters")
        if "content" in fields:
            content = fields["content"]
            if (
                not isinstance(content, str)
                or not content.strip()
                or len(content) > MAX_CONTENT
            ):
                raise ValidationError(
                    f"memory content must be 1-{MAX_CONTENT} characters"
                )
            if redaction.looks_secret(content):
                raise ValidationError(
                    "refusing to store credential-shaped content in memory"
                )
        if (
            "verification" in fields
            and fields["verification"] not in VERIFICATION_STATES
        ):
            raise ValidationError(
                f"unknown verification state {fields['verification']!r}"
            )
        if memory.kind == "solution" and fields.get("verification") == "verified":
            evidence = fields.get("evidence", memory.evidence)
            details_evidence = (fields.get("details") or memory.details or {}).get(
                "evidence"
            )
            if not evidence and not details_evidence:
                raise ValidationError(
                    "cannot mark a solution verified without evidence"
                )
        if "content" in fields or "title" in fields:
            fields["checksum"] = self._checksum(
                memory.kind,
                memory.scope,
                memory.scope_id,
                fields.get("title", memory.title),
                fields.get("content", memory.content),
            )
        self._write(
            "memory.update",
            {"id": memory_id, "fields": fields, "change": change, "now": iso_now()},
        )
        updated = self.require(memory_id)
        self.trace(
            "memory",
            "memory.updated",
            project_id=updated.project_id,
            payload={
                "memory_id": memory_id,
                "fields": sorted(fields),
                "version": updated.version,
            },
        )
        return updated

    def set_status(self, memory_ids: Sequence[str], status: str) -> int:
        if not memory_ids:
            return 0
        result = self._write(
            "memory.status",
            {"ids": list(memory_ids), "status": status, "now": iso_now()},
        )
        self.trace(
            "memory",
            "memory.status_changed",
            payload={"ids": list(memory_ids), "status": status},
        )
        return int(result.get("updated", 0))

    def retire(self, memory_id: str, *, reason: str = "") -> Memory:
        memory = self.require(memory_id)
        if memory.kind not in ("solution", "learning", "archival", "project"):
            raise ValidationError(
                f"{memory.kind} memory cannot be retired (delete it instead)"
            )
        return self.update(
            memory_id,
            change="retire",
            status="retired",
            details={**memory.details, "retire_reason": reason},
        )

    def delete(self, memory_id: str, *, hard: bool = False) -> str:
        memory = self.require(memory_id)
        self._write(
            "memory.delete",
            {
                "id": memory_id,
                "hard": hard,
                "now": iso_now(),
                "checksum": memory.checksum,
            },
        )
        self.trace(
            "memory",
            "memory.deleted",
            payload={"memory_id": memory_id, "kind": memory.kind, "hard": hard},
        )
        return "hard_deleted" if hard else "deleted"

    def restore(self, memory_id: str) -> Memory:
        self.get(memory_id, include_deleted=True).ok_or_raise()
        self._write(
            "memory.update",
            {
                "id": memory_id,
                "fields": {"status": "active"},
                "change": "restore",
                "now": iso_now(),
            },
        )
        with self.store.write_tx() as tx:
            tx.execute(
                "UPDATE memories SET deleted_at = NULL WHERE id = ?", (memory_id,)
            )
        return self.require(memory_id)

    def add_source(
        self,
        memory_id: str,
        *,
        source_type: str,
        reference: str | None = None,
        excerpt: str | None = None,
    ) -> None:
        if source_type not in SOURCE_TYPES:
            raise ValidationError(f"unknown source type {source_type!r}")
        self.require(memory_id)
        self._write(
            "memory.source",
            {
                "memory_id": memory_id,
                "source_type": source_type,
                "reference": reference,
                "excerpt": excerpt[:2000] if excerpt else None,
                "now": iso_now(),
                "checksum": sha256_text(f"{reference or ''}\x1f{excerpt or ''}"),
            },
        )

    def sources(self, memory_id: str) -> list[dict[str, Any]]:
        return self.store.query(
            "SELECT source_type, reference, excerpt, retrieved_at, checksum FROM memory_sources"
            " WHERE memory_id = ? ORDER BY sid",
            (memory_id,),
        )

    def history(self, memory_id: str) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT version, change, changed_at, snapshot FROM memory_history WHERE memory_id = ? ORDER BY hid",
            (memory_id,),
        )
        out = []
        for row in rows:
            snapshot = json.loads(row["snapshot"]) if row["snapshot"] else {}
            out.append(
                {
                    "version": row["version"],
                    "change": row["change"],
                    "changed_at": row["changed_at"],
                    "snapshot": snapshot,
                }
            )
        return out

    def attach_artifact(
        self,
        memory_id: str,
        data: bytes,
        *,
        filename: str,
        mime: str | None = None,
    ) -> str:
        if self.artifacts_root is None:
            raise PathError("artifact storage is not configured for this workspace")
        memory = self.require(memory_id)
        if not isinstance(data, (bytes, bytearray)):
            raise ValidationError("artifact data must be bytes")
        root = ensure_directory(self.artifacts_root)
        directory = ensure_directory(child_path(root, "memory", memory.id))
        target = child_path(directory, safe_filename(filename))
        if target.exists():
            target = child_path(
                directory, f"{sha256_bytes(bytes(data))[:12]}_{safe_filename(filename)}"
            )
        target.write_bytes(bytes(data))
        checksum = sha256_bytes(bytes(data))
        self._write(
            "memory.artifact",
            {
                "memory_id": memory_id,
                "path": str(target),
                "checksum": checksum,
                "now": iso_now(),
            },
        )
        self.trace(
            "memory",
            "memory.artifact_attached",
            payload={"memory_id": memory_id, "bytes": len(data), "mime": mime},
        )
        return str(target)

    def read_artifact(self, memory_id: str) -> bytes:
        memory = self.require(memory_id)
        if not memory.artifact_path:
            raise NotFoundError(f"memory {memory_id} has no artifact")
        from pathlib import Path

        path = Path(memory.artifact_path)
        if not path.exists():
            raise PathError(f"artifact file is missing: {path}", path=str(path))
        data = path.read_bytes()
        if memory.checksum and sha256_bytes(data) != memory.checksum:
            raise ValidationError(
                "artifact checksum mismatch (file changed since it was recorded)"
            )
        return data

    def apply_retention(
        self, *, now: datetime | None = None, archival_retention_days: int = 365
    ) -> dict[str, int]:
        current = now or datetime.now(timezone.utc)
        now_iso = iso_from_ts(current.timestamp())
        expired_active = 0
        expired_archival = 0
        with self.store.write_tx() as tx:
            rows = tx.query(
                "SELECT id, expires_at FROM memories WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ?",
                (now_iso,),
            )
            for row in rows:
                tx.execute(
                    "UPDATE memories SET status='expired', updated_at=? WHERE id=?",
                    (now_iso, row["id"]),
                )
                expired_active += 1
            cutoff = iso_from_ts(
                (current - timedelta(days=archival_retention_days)).timestamp()
            )
            rows = tx.query(
                "SELECT id FROM memories WHERE kind='archival' AND status='active' AND created_at < ?",
                (cutoff,),
            )
            for row in rows:
                tx.execute(
                    "UPDATE memories SET status='expired', updated_at=? WHERE id=?",
                    (now_iso, row["id"]),
                )
                expired_archival += 1
        if expired_active or expired_archival:
            self.trace(
                "memory",
                "memory.retention_applied",
                level="summary",
                payload={
                    "expired_active": expired_active,
                    "expired_archival": expired_archival,
                },
            )
        return {"expired_active": expired_active, "expired_archival": expired_archival}

    def purge_deleted(
        self, *, older_than_days: int = 30, now: datetime | None = None
    ) -> int:
        current = now or datetime.now(timezone.utc)
        cutoff = iso_from_ts((current - timedelta(days=older_than_days)).timestamp())
        rows = self.store.query(
            "SELECT id FROM memories WHERE status='deleted' AND deleted_at < ?",
            (cutoff,),
        )
        for row in rows:
            self._write(
                "memory.delete",
                {
                    "id": row["id"],
                    "hard": True,
                    "now": iso_from_ts(current.timestamp()),
                    "checksum": None,
                },
            )
        return len(rows)
