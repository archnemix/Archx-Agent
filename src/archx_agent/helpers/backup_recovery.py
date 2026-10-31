"""Backup, verification and restore.

Rules
-----
* Restore **never deletes**: the current database is renamed aside first.
* A restore is previewable and only proceeds when the backup passes an
  integrity check and its schema is not newer than this build.
* Every backup carries a manifest (sha256, size, schema version, table counts)
  so tampering or truncation is detectable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .exceptions import BackupError, RestoreError, SchemaVersionError, StorageError
from .jsonio import atomic_write_json, file_size, read_json, sha256_file
from .paths import ensure_directory, safe_filename
from .sqlite_store import SUPPORTED_SCHEMA_VERSION, SqliteStore
from .timeutil import iso_now

MANIFEST_SUFFIX = ".manifest.json"


@dataclass
class BackupInfo:
    path: Path
    label: str
    created_at: str
    size: int
    sha256: str
    schema_version: int
    tables: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "label": self.label,
            "created_at": self.created_at,
            "size": self.size,
            "sha256": self.sha256,
            "schema_version": self.schema_version,
            "tables": self.tables,
        }


def create_backup(
    db_path: str | os.PathLike[str],
    backup_dir: str | os.PathLike[str],
    *,
    label: str = "backup",
) -> BackupInfo:
    """Consistent online backup plus manifest."""
    src_path = Path(db_path).expanduser()
    if not src_path.exists():
        raise BackupError(f"database does not exist: {src_path}", path=str(src_path))
    directory = ensure_directory(backup_dir)
    stamp = iso_now().replace(":", "").replace("-", "").replace(".", "")
    name = f"{safe_filename(label)}_{stamp}.db"
    dest = directory / name
    store = SqliteStore(src_path)
    try:
        store.backup_to(dest)
        tables = store.table_counts()
        version = store.schema_version()
    finally:
        store.close()
    info = BackupInfo(
        path=dest,
        label=label,
        created_at=iso_now(),
        size=file_size(dest),
        sha256=sha256_file(dest),
        schema_version=version,
        tables=tables,
    )
    atomic_write_json(_manifest_path(dest), info.to_dict())
    return info


def _manifest_path(backup_path: Path) -> Path:
    return Path(str(backup_path) + MANIFEST_SUFFIX)


def verify_backup(backup_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Check integrity + manifest hash. Returns a report; never raises for a bad file."""
    path = Path(backup_path).expanduser()
    report: dict[str, Any] = {"path": str(path), "ok": False, "problems": []}
    if not path.exists():
        report["problems"].append("file missing")
        return report
    manifest_file = _manifest_path(path)
    manifest = read_json(manifest_file)
    if manifest is None:
        report["problems"].append("manifest missing")
    else:
        actual_hash = sha256_file(path)
        if manifest.get("sha256") != actual_hash:
            report["problems"].append("sha256 hash mismatch (file changed or truncated)")
        report["manifest"] = manifest
    store = SqliteStore(path)
    try:
        integrity = store.integrity_check()
        report["integrity"] = integrity
        if integrity != ["ok"]:
            report["problems"].append("sqlite integrity check failed")
        report["schema_version"] = store.schema_version()
        report["tables"] = store.table_counts()
        if report["schema_version"] > SUPPORTED_SCHEMA_VERSION:
            report["problems"].append(
                f"schema version {report['schema_version']} is newer than supported {SUPPORTED_SCHEMA_VERSION}"
            )
    except StorageError as exc:
        report["problems"].append(f"cannot read database: {exc.message}")
    finally:
        store.close()
    report["ok"] = not report["problems"]
    return report


def preview_restore(backup_path: str | os.PathLike[str], db_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Describe exactly what restoring will change. Deletes nothing."""
    backup = Path(backup_path).expanduser()
    current = Path(db_path).expanduser()
    report = verify_backup(backup)
    preview: dict[str, Any] = {
        "backup": str(backup),
        "database": str(current),
        "backup_ok": report["ok"],
        "problems": report["problems"],
        "current_exists": current.exists(),
    }
    if report["ok"]:
        preview["backup_schema_version"] = report.get("schema_version")
        preview["backup_tables"] = report.get("tables", {})
        if current.exists():
            store = SqliteStore(current)
            try:
                preview["current_schema_version"] = store.schema_version()
                preview["current_tables"] = store.table_counts()
            finally:
                store.close()
            cur = preview.get("current_tables", {})
            bak = preview.get("backup_tables", {})
            # positive delta = the restore adds rows, negative = it removes rows
            preview["row_deltas"] = {
                t: bak.get(t, 0) - cur.get(t, 0)
                for t in sorted(set(cur) | set(bak))
                if bak.get(t, 0) != cur.get(t, 0)
            }
            preview["aside_path"] = str(_aside_path(current))
    return preview


def _aside_path(db_path: Path) -> Path:
    stamp = iso_now().replace(":", "").replace("-", "")
    return db_path.with_name(f"{db_path.name}.replaced-{stamp}")


def restore_backup(
    backup_path: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Restore a verified backup, renaming the current database aside."""
    backup = Path(backup_path).expanduser()
    current = Path(db_path).expanduser()
    report = verify_backup(backup)
    if not report["ok"]:
        raise RestoreError("backup failed verification: " + "; ".join(report["problems"]), path=str(backup))
    if report["schema_version"] > SUPPORTED_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"backup schema {report['schema_version']} newer than supported {SUPPORTED_SCHEMA_VERSION}"
        )
    ensure_directory(current.parent)
    aside: Path | None = None
    if current.exists():
        # Always rename aside - a restore must never destroy the current data.
        aside = _aside_path(current)
        os.replace(current, aside)
        # Move the replaced database's WAL/SHM too so the restored file is authoritative.
        for suffix in ("-wal", "-shm"):
            side = Path(str(current) + suffix)
            if side.exists():
                os.replace(side, Path(str(aside) + suffix))
    tmp = current.with_name(current.name + ".restoring")
    with open(backup, "rb") as src, open(tmp, "wb") as dst:
        while True:
            block = src.read(1 << 20)
            if not block:
                break
            dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())
    manifest = report.get("manifest") or {}
    if manifest.get("sha256") and sha256_file(tmp) != manifest["sha256"]:
        os.unlink(tmp)
        raise RestoreError("copied backup hash mismatch", path=str(backup))
    os.replace(tmp, current)
    return {
        "restored_from": str(backup),
        "database": str(current),
        "aside": str(aside) if aside else None,
        "tables": report.get("tables", {}),
        "schema_version": report.get("schema_version"),
    }


def list_backups(backup_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    directory = Path(backup_dir).expanduser()
    if not directory.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.db")):
        manifest = read_json(_manifest_path(path)) or {}
        out.append(
            {
                "path": str(path),
                "size": file_size(path),
                "created_at": manifest.get("created_at"),
                "sha256": manifest.get("sha256"),
                "schema_version": manifest.get("schema_version"),
                "label": manifest.get("label"),
            }
        )
    out.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return out


def apply_retention(backup_dir: str | os.PathLike[str], *, keep: int = 10) -> list[str]:
    """Keep the newest ``keep`` backups; older ones are *moved* to a trash dir."""
    if keep < 1:
        raise BackupError("keep must be >= 1")
    backups = list_backups(backup_dir)
    removed: list[str] = []
    trash = ensure_directory(Path(backup_dir).expanduser() / "_retired")
    for entry in backups[keep:]:
        path = Path(entry["path"])
        target = trash / path.name
        os.replace(path, target)
        manifest = _manifest_path(path)
        if manifest.exists():
            os.replace(manifest, trash / manifest.name)
        removed.append(str(target))
    return removed


def prune_manifest_clock_skew(backup_dir: str | os.PathLike[str]) -> list[str]:
    """Detect manifests whose timestamp is in the future (clock problems)."""
    problems: list[str] = []
    now = iso_now()
    for entry in list_backups(backup_dir):
        created = entry.get("created_at")
        if created and created > now:
            problems.append(f"{entry['path']} has a future timestamp ({created})")
    return problems


__all__ = [
    "BackupInfo",
    "create_backup",
    "verify_backup",
    "preview_restore",
    "restore_backup",
    "list_backups",
    "apply_retention",
    "prune_manifest_clock_skew",
]
