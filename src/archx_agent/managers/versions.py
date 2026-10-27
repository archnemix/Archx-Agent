"""Content versions: what a document looked like, and how to get it back.

Every record belongs to a *subject* (``artifact``, ``project_file``, ``prompt``,
``memory``, ``document``, ``report``, ...). A subject id is whatever the caller uses to
name it - for an artifact that is the file's absolute path, so re-attaching the same file
continues the same history instead of starting a new one.

Rules:

* **Nothing is overwritten or deleted.** A new state is a new row with the next ordinal;
  ``restore`` writes a *new* version whose content equals an old one and records where it
  came from.
* **Unchanged content is not a version.** Recording identical content returns the
  existing version with ``created=False``; the history never fills with duplicates.
* **Ordinals are the sequence.** Versions are ordered by ``ordinal`` (1, 2, 3 ...), not by
  timestamps, and a unique index makes two versions with the same ordinal impossible.
* **Content may be absent, but never invented.** Above ``tasks.max_version_bytes`` the
  checksum and size are recorded and the content is not; ``content_stored`` says so
  explicitly so a reader cannot mistake an empty body for an empty file.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from archx_agent.helpers.exceptions import ConflictError, NotFoundError, ValidationError
from archx_agent.helpers.jsonio import sha256_bytes, sha256_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

VERSION_TABLES = ("version_records",)

SUBJECT_TYPES = (
    "artifact",
    "project_file",
    "prompt",
    "memory",
    "document",
    "report",
    "dataset",
    "config",
    "other",
)

_MAX_SUBJECT = 400


@dataclass
class Version:
    id: str
    subject_type: str
    subject_id: str
    version: str
    ordinal: int
    content: str
    checksum: str
    created_at: str
    created_by: str
    note: str
    size: int
    content_stored: bool = True
    restored_from: str | None = None

    def to_dict(self, *, with_content: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "version": self.version,
            "ordinal": self.ordinal,
            "checksum": self.checksum,
            "size": self.size,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "note": self.note,
            "restored_from": self.restored_from,
            "content_stored": self.content_stored,
        }
        if with_content:
            data["content"] = self.content
        return data


@dataclass
class VersionWrite:
    """The result of recording: the version to read plus whether a row was written."""

    version: Version
    created: bool
    reason: str

    def to_dict(self, *, with_content: bool = False) -> dict[str, Any]:
        return {
            "version": self.version.to_dict(with_content=with_content),
            "created": self.created,
            "reason": self.reason,
        }


def _from_row(row: dict[str, Any]) -> Version:
    return Version(
        id=row["id"],
        subject_type=row["subject_type"],
        subject_id=row["subject_id"],
        version=row["version"],
        ordinal=int(row.get("ordinal") or 0),
        content=row.get("content") or "",
        checksum=row["checksum"],
        created_at=row["created_at"],
        created_by=row.get("created_by") or "user",
        note=row.get("note") or "",
        size=int(row.get("size") or 0),
        content_stored=bool(row.get("content_stored", 1)),
        restored_from=row.get("restored_from"),
    )


class VersionManager(BaseManager):
    """Append-only content history with diffs and restores."""

    tables = VERSION_TABLES

    def __init__(self, store, coordinator, *, events=None, max_bytes: int = 1_048_576) -> None:
        self.max_bytes = int(max_bytes)
        super().__init__(store, coordinator, events=events)

    def register_handlers(self) -> None:
        self.coordinator.register("version.record", self._apply_record)

    def _apply_record(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        v = payload["version"]
        tx.execute(
            "INSERT INTO version_records(id, subject_type, subject_id, version, content,"
            " checksum, created_at, created_by, note, ordinal, size, restored_from,"
            " content_stored) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                v["id"], v["subject_type"], v["subject_id"], v["version"], v["content"],
                v["checksum"], v["created_at"], v["created_by"], v["note"], v["ordinal"],
                v["size"], v.get("restored_from"), 1 if v["content_stored"] else 0,
            ),
        )
        return {"id": v["id"], "ordinal": v["ordinal"], "version": v["version"]}

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _validate(subject_type: str, subject_id: str) -> tuple[str, str]:
        kind = (subject_type or "").strip().lower()
        if kind not in SUBJECT_TYPES:
            raise ValidationError(
                f"unknown version subject type {subject_type!r} (known: {', '.join(SUBJECT_TYPES)})"
            )
        ident = (subject_id or "").strip()
        if not ident:
            raise ValidationError("a version needs a subject id")
        if len(ident) > _MAX_SUBJECT:
            raise ValidationError(f"subject id is too long ({len(ident)} > {_MAX_SUBJECT} characters)")
        return kind, ident

    def _latest_row(self, subject_type: str, subject_id: str) -> dict[str, Any] | None:
        return self.store.query_one(
            "SELECT * FROM version_records WHERE subject_type = ? AND subject_id = ?"
            " ORDER BY ordinal DESC, rowid DESC LIMIT 1",
            (subject_type, subject_id),
        )

    # -- writes ------------------------------------------------------------
    def record(
        self,
        subject_type: str,
        subject_id: str,
        *,
        content: str | None = None,
        path: str | Path | None = None,
        note: str = "",
        created_by: str = "user",
        version: str | None = None,
        store_content: bool | None = None,
        force: bool = False,
        restored_from: str | None = None,
    ) -> VersionWrite:
        kind, ident = self._validate(subject_type, subject_id)
        if (content is None) == (path is None):
            raise ValidationError("record exactly one of content= or path=")
        if path is not None:
            file_path = Path(path).expanduser()
            if not file_path.is_file():
                raise NotFoundError(f"cannot version a missing file: {file_path}")
            raw = file_path.read_bytes()
            size = len(raw)
            checksum = sha256_bytes(raw)
            text: str | None = None
            if store_content is not False:
                try:
                    candidate = raw.decode("utf-8")
                    # A NUL byte is not text even when it happens to decode as UTF-8.
                    text = candidate if "\x00" not in candidate else None
                except UnicodeDecodeError:
                    text = None
                if text is not None and size > self.max_bytes:
                    text = None
            if store_content is None:
                # The file itself still exists, so recording only its checksum loses nothing.
                store_content = text is not None
            if store_content and text is None:
                raise ValidationError(
                    f"{file_path} is not text or is larger than tasks.max_version_bytes;"
                    " pass store_content=False to record only its checksum"
                )
        else:
            assert content is not None
            raw = content.encode("utf-8")
            size = len(raw)
            checksum = sha256_text(content)
            if store_content is None:
                store_content = True
            if store_content and size > self.max_bytes:
                # There is nowhere else to keep explicitly supplied content, so refusing is
                # honest; silently keeping a checksum of vanished text would not be.
                raise ValidationError(
                    f"content is {size} bytes, above tasks.max_version_bytes={self.max_bytes};"
                    " raise the setting, or record a file with store_content=False"
                )
            text = content if store_content else None

        latest = self._latest_row(kind, ident)
        if latest is not None and not force:
            latest_version = _from_row(latest)
            if latest_version.checksum == checksum and latest_version.content_stored == bool(store_content):
                return VersionWrite(
                    version=latest_version,
                    created=False,
                    reason=f"content is unchanged since {latest_version.version}",
                )

        ordinal = int(latest["ordinal"]) + 1 if latest and latest.get("ordinal") else 1
        label = (version or f"v{ordinal}").strip()
        if len(label) > 40:
            raise ValidationError("a version label must be 40 characters or fewer")
        if self.store.scalar(
            "SELECT COUNT(*) FROM version_records WHERE subject_type = ? AND subject_id = ? AND version = ?",
            (kind, ident, label),
        ):
            raise ConflictError(f"{kind} {ident} already has a version labelled {label!r}")

        record = Version(
            id=new_id("vr_"),
            subject_type=kind,
            subject_id=ident,
            version=label,
            ordinal=ordinal,
            content=text or "",
            checksum=checksum,
            created_at=iso_now(),
            created_by=created_by or "user",
            note=(note or "")[:2000],
            size=size,
            content_stored=bool(store_content),
            restored_from=restored_from,
        )
        self._write(
            "version.record",
            {
                "version": {
                    **record.to_dict(with_content=True),
                    "content_stored": record.content_stored,
                }
            },
        )
        self.trace(
            "artifact",
            "version.recorded",
            status="ok",
            payload={
                "subject_type": kind,
                "subject_id": ident,
                "version": label,
                "ordinal": ordinal,
                "checksum": checksum,
                "content_stored": record.content_stored,
            },
        )
        return VersionWrite(version=record, created=True, reason=f"recorded {label}")

    def restore(
        self,
        subject_type: str,
        subject_id: str,
        version: str,
        *,
        note: str = "",
        created_by: str = "user",
    ) -> VersionWrite:
        """Write a new version whose content equals ``version``.

        History is never rewritten: the restored state is a *new* version, and
        ``restored_from`` records which old version it came from.
        """
        source = self.at(subject_type, subject_id, version)
        if not source.content_stored:
            raise ValidationError(
                f"{source.version} has no stored content (only its checksum was recorded);"
                " it cannot be restored from the database"
            )
        write = self.record(
            subject_type,
            subject_id,
            content=source.content,
            note=note or f"restored from {source.version}",
            created_by=created_by,
            restored_from=source.version,
            force=True,
        )
        self.trace(
            "artifact",
            "version.restored",
            status="ok",
            payload={
                "subject_type": source.subject_type,
                "subject_id": source.subject_id,
                "from": source.version,
                "to": write.version.version,
            },
        )
        return write

    # -- reads -------------------------------------------------------------
    def latest(self, subject_type: str, subject_id: str):
        kind, ident = self._validate(subject_type, subject_id)
        row = self._latest_row(kind, ident)
        if row is None:
            return None
        return _from_row(row)

    def history(self, subject_type: str, subject_id: str) -> list[Version]:
        kind, ident = self._validate(subject_type, subject_id)
        rows = self.store.query(
            "SELECT * FROM version_records WHERE subject_type = ? AND subject_id = ?"
            " ORDER BY ordinal, rowid",
            (kind, ident),
        )
        return [_from_row(row) for row in rows]

    def at(self, subject_type: str, subject_id: str, version: str | None = None) -> Version:
        kind, ident = self._validate(subject_type, subject_id)
        if version in (None, "", "latest"):
            row = self._latest_row(kind, ident)
        else:
            row = self.store.query_one(
                "SELECT * FROM version_records WHERE subject_type = ? AND subject_id = ?"
                " AND (version = ? OR CAST(ordinal AS TEXT) = ?)",
                (kind, ident, str(version), str(version)),
            )
        if row is None:
            known = ", ".join(v.version for v in self.history(kind, ident)) or "none"
            raise NotFoundError(
                f"no version {version!r} of {kind} {ident} (known: {known})"
            )
        return _from_row(row)

    def diff(
        self,
        subject_type: str,
        subject_id: str,
        from_version: str | None = None,
        to_version: str | None = None,
        *,
        context: int = 3,
    ) -> dict[str, Any]:
        versions = self.history(subject_type, subject_id)
        if not versions:
            raise NotFoundError(f"{subject_type} {subject_id} has no versions")
        target = self.at(subject_type, subject_id, to_version) if to_version else versions[-1]
        if from_version:
            source = self.at(subject_type, subject_id, from_version)
        else:
            index = versions.index(target)
            if index == 0:
                source = Version(
                    id="", subject_type=target.subject_type, subject_id=target.subject_id,
                    version="(empty)", ordinal=0, content="", checksum="", created_at="",
                    created_by="", note="", size=0,
                )
            else:
                source = versions[index - 1]
        if source.subject_id and not source.content_stored:
            raise ValidationError(f"{source.version} has no stored content to diff")
        if not target.content_stored:
            raise ValidationError(f"{target.version} has no stored content to diff")
        lines = list(
            difflib.unified_diff(
                source.content.splitlines(),
                target.content.splitlines(),
                fromfile=f"{source.version}",
                tofile=f"{target.version}",
                lineterm="",
                n=context,
            )
        )
        added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        return {
            "subject_type": target.subject_type,
            "subject_id": target.subject_id,
            "from": source.version,
            "to": target.version,
            "from_checksum": source.checksum,
            "to_checksum": target.checksum,
            "added": added,
            "removed": removed,
            "identical": source.checksum == target.checksum,
            "text": "\n".join(lines),
        }

    def subjects(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT subject_type, subject_id, COUNT(*) AS versions,"
            " MAX(ordinal) AS latest_ordinal, MAX(created_at) AS last_recorded"
            " FROM version_records GROUP BY subject_type, subject_id"
            " ORDER BY last_recorded DESC LIMIT ?",
            (int(limit),),
        )
        return rows

    def count(self, subject_type: str | None = None) -> int:
        if subject_type:
            return int(
                self.store.scalar(
                    "SELECT COUNT(*) FROM version_records WHERE subject_type = ?",
                    (subject_type,),
                )
                or 0
            )
        return self.table_count("version_records")


__all__ = [
    "SUBJECT_TYPES",
    "VERSION_TABLES",
    "Version",
    "VersionManager",
    "VersionWrite",
]
