"""Sync operations for execution targets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.application.execution.constants import (
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_BYTES,
)
from archx_agent.application.execution.hashing import _sha


class ExecutionServiceSyncMixin:
    """Sync responsibility for ExecutionService."""

    def _read_local(self, root: Path, limit: int) -> dict[str, str]:
        files: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue  # a project's .git is not what a sandbox needs
            if len(files) >= limit:
                break
            if path.stat().st_size > DEFAULT_MAX_BYTES:
                continue
            files[path.relative_to(root).as_posix()] = path.read_text(
                encoding="utf-8", errors="replace"
            )
        return files

    def push(
        self, target: str, *, root: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        """Send the project to the target, and record every file with its hash."""
        resolved = self._resolve(target)
        if resolved.kind != "remote":
            raise ValidationError(
                "only a remote target needs a push: a container, WSL or a VM reads the directory you "
                "mounted, so there is nothing to copy"
            )
        reasons = self.blockers(resolved)
        if reasons:
            raise ValidationError("; ".join(reasons))
        base = Path(
            root or str(self.ws.config.get("execution.project", "") or ".")
        ).resolve()
        if not base.is_dir():
            raise ValidationError(f"{base} is not a directory")
        files = self._read_local(base, int(limit or DEFAULT_MAX_FILES))
        if not files:
            raise ValidationError(f"there is nothing to push under {base}")
        answer = self._post(
            f"{self._endpoint(resolved)}/files",
            json.dumps(
                {"files": files, "root": resolved.spec.get("workdir") or "project"}
            ).encode(),
            timeout=float(self.ws.config.get("remote.timeout", 10) or 10) * 6,
        )
        written = {item["path"]: item for item in answer.get("written") or []}
        for relpath, text in sorted(files.items()):
            remote = written.get(relpath) or {}
            self.manager.record_file(
                path=relpath,
                direction="push",
                status="applied",
                target_id=resolved.id,
                sha256_local=_sha(text),
                sha256_remote=remote.get("sha256"),
                size=len(text.encode("utf-8")),
            )
        return {
            "target": resolved.name,
            "root": str(base),
            "files": len(files),
            "bytes": sum(len(text.encode("utf-8")) for text in files.values()),
            "paths": sorted(files),
        }

    def pull(
        self, target: str, *, root: str | None = None, force: bool = False
    ) -> dict[str, Any]:
        """Bring back what changed, and refuse to clobber an edit made here in the meantime."""
        resolved = self._resolve(target)
        if resolved.kind != "remote":
            raise ValidationError("only a remote target has files to pull back")
        reasons = self.blockers(resolved)
        if reasons:
            raise ValidationError("; ".join(reasons))
        base = Path(
            root or str(self.ws.config.get("execution.project", "") or ".")
        ).resolve()
        base.mkdir(parents=True, exist_ok=True)
        answer = self._get(
            f"{self._endpoint(resolved)}/files",
            timeout=float(self.ws.config.get("remote.timeout", 10) or 10) * 6,
        )
        remote_files = {item["path"]: item for item in answer.get("files") or []}
        applied: list[str] = []
        skipped: list[str] = []
        conflicts: list[str] = []
        for relpath, item in sorted(remote_files.items()):
            local_path = base / relpath
            local_text = (
                local_path.read_text(encoding="utf-8", errors="replace")
                if local_path.is_file()
                else None
            )
            local_sha = _sha(local_text) if local_text is not None else None
            remote_sha = str(item.get("sha256") or "")
            pushed = self.manager.last_push(resolved.id, relpath)
            base_sha = pushed.sha256_local if pushed else None
            if local_sha == remote_sha:
                self.manager.record_file(
                    path=relpath,
                    direction="pull",
                    status="unchanged",
                    target_id=resolved.id,
                    sha256_local=local_sha,
                    sha256_remote=remote_sha,
                    size=item.get("bytes"),
                )
                skipped.append(relpath)
                continue
            local_changed = (
                base_sha is not None and local_sha is not None and local_sha != base_sha
            )
            remote_changed = base_sha is None or remote_sha != base_sha
            if local_changed and remote_changed and not force:
                self.manager.record_file(
                    path=relpath,
                    direction="pull",
                    status="conflict",
                    target_id=resolved.id,
                    sha256_local=local_sha,
                    sha256_remote=remote_sha,
                    size=item.get("bytes"),
                    note=(
                        "changed here since it was pushed and changed on the target too; "
                        "not overwritten - `exec pull --force` replaces it, or merge by hand"
                    ),
                )
                conflicts.append(relpath)
                continue
            self._execute(
                "fs.write",
                {
                    "path": str(local_path),
                    "content": str(item.get("content") or ""),
                    "create_parents": True,
                },
                f"execution pull {relpath}",
            )
            self.manager.record_file(
                path=relpath,
                direction="pull",
                status="applied",
                target_id=resolved.id,
                sha256_local=_sha(str(item.get("content") or "")),
                sha256_remote=remote_sha,
                size=item.get("bytes"),
                note="moved here by force" if (local_changed and force) else None,
            )
            applied.append(relpath)
        return {
            "target": resolved.name,
            "root": str(base),
            "applied": applied,
            "skipped": skipped,
            "conflicts": conflicts,
            "files": len(remote_files),
        }
