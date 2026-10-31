"""Bounded text transfer and rooted path checks for the opt-in worker file API.

Preflight prevents malformed/escaping batches from making partial writes. Filesystem
errors during a valid batch are not transactionally rolled back. Resolved-path checks
are snapshots; they do not provide an OS jail or eliminate concurrent symlink races.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .protocol import PROTOCOL, _sha

MAX_FILE_BYTES = 2_000_000
MAX_TRANSFER_BYTES = 8_000_000
MAX_FILES = 500
MAX_SCAN_ENTRIES = 10_000


def _project_paths(base: Path):
    """Stream directory entries instead of materializing a whole scandir/rglob list."""
    pending = [base] if base.exists() else []
    count = 0
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > MAX_SCAN_ENTRIES:
                    raise ValueError("file scan entry budget exceeded")
                if entry.name.startswith("."):
                    continue
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                else:
                    yield path


class WorkerFilesMixin:
    def _inside(self, relative: str, *, create: bool = True) -> Path | None:
        if not isinstance(relative, str) or "\0" in relative:
            return None
        try:
            root = self.workdir.resolve()
            candidate = (root / relative).resolve()
            candidate.relative_to(root)
            if candidate.exists() and not candidate.is_dir():
                return None
            if create:
                candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except (OSError, ValueError, RuntimeError):
            return None

    def write_files(self, request: dict[str, Any]) -> dict[str, Any]:
        refusal = self.exec_refusal()
        if refusal:
            return {"refused": refusal}
        if not isinstance(request, dict) or not isinstance(request.get("files"), dict):
            return {
                "refused": "files request must contain an object of text paths and contents"
            }
        files = request["files"]
        if len(files) > MAX_FILES:
            return {"refused": f"file transfer exceeds {MAX_FILES} files"}
        root = request.get("root", "project")
        base = self._inside(root, create=False)
        if base is None:
            return {"refused": "the project root must stay inside the work directory"}
        prepared = []
        seen = set()
        total = 0
        for relative, content in files.items():
            if (
                not isinstance(relative, str)
                or not relative
                or not isinstance(content, str)
            ):
                return {"refused": "file names and contents must be strings"}
            try:
                target = (base / relative).resolve()
                target.relative_to(base)
                if (
                    target == base
                    or target in seen
                    or (target.exists() and not target.is_file())
                ):
                    return {
                        "refused": f"{relative} is not a unique regular file target"
                    }
                if any(parent in seen for parent in target.parents) or any(
                    target in prior.parents for prior in seen
                ):
                    return {
                        "refused": "file targets cannot overlap as parent and child"
                    }
                for parent in target.parents:
                    if parent == base:
                        break
                    if parent.exists() and not parent.is_dir():
                        return {"refused": f"{relative} has a non-directory parent"}
                data = content.encode("utf-8")
            except (ValueError, OSError, RuntimeError, UnicodeError):
                return {
                    "refused": f"{relative} would escape the project directory or is invalid text"
                }
            if len(data) > MAX_FILE_BYTES:
                return {"refused": f"{relative} exceeds {MAX_FILE_BYTES} bytes"}
            total += len(data)
            if total > MAX_TRANSFER_BYTES:
                return {"refused": f"transfer exceeds {MAX_TRANSFER_BYTES} bytes"}
            seen.add(target)
            prepared.append((relative, target, content, data))
        written = []
        try:
            for relative, target, content, data in sorted(prepared):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                written.append(
                    {"path": relative, "sha256": _sha(content), "bytes": len(data)}
                )
        except OSError as exc:
            return {
                "refused": f"file write failed: {type(exc).__name__}",
                "written": written,
            }
        return {
            "protocol": PROTOCOL,
            "machine": self.name,
            "root": root,
            "written": written,
        }

    def list_files(self, root: str = "project") -> dict[str, Any]:
        refusal = self.exec_refusal()
        if refusal:
            return {"refused": refusal}
        base = self._inside(root, create=False)
        if base is None:
            return {"refused": "the project root must stay inside the work directory"}
        files = []
        total = 0
        try:
            for path in _project_paths(base):
                resolved = path.resolve()
                try:
                    resolved.relative_to(base)
                except ValueError:
                    return {
                        "refused": f"{path.name} points outside the project directory"
                    }
                if not resolved.is_file():
                    continue
                if len(files) >= MAX_FILES:
                    return {"refused": f"file transfer exceeds {MAX_FILES} files"}
                with resolved.open("rb") as stream:
                    data = stream.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    return {"refused": f"{path.name} exceeds {MAX_FILE_BYTES} bytes"}
                total += len(data)
                if total > MAX_TRANSFER_BYTES:
                    return {"refused": f"transfer exceeds {MAX_TRANSFER_BYTES} bytes"}
                text = data.decode("utf-8")
                files.append(
                    {
                        "path": path.relative_to(base).as_posix(),
                        "sha256": _sha(text),
                        "bytes": len(data),
                        "content": text,
                    }
                )
        except (OSError, ValueError, RuntimeError) as exc:
            return {"refused": f"cannot read project files: {type(exc).__name__}"}
        files.sort(key=lambda item: item["path"])
        return {
            "protocol": PROTOCOL,
            "machine": self.name,
            "root": root,
            "files": files,
        }
