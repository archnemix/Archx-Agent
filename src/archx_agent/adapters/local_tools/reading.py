"""LocalToolRuntime reading."""

from __future__ import annotations

import hashlib
from typing import Any

from archx_agent.helpers.exceptions import (
    ToolError,
)
from archx_agent.adapters.local_tools.constants import _BINARY_SNIFF
from archx_agent.adapters.local_tools.hashing import sha256_bytes


class LocalToolRuntimeReadingMixin:
    """Reading responsibility for LocalToolRuntime."""

    def read_text(
        self, path: str, *, start_line: int = 1, max_lines: int | None = None
    ) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists():
            raise ToolError(f"no such file: {self.relative(target)}")
        if target.is_dir():
            raise ToolError(f"{self.relative(target)} is a directory (use fs.list)")
        size = target.stat().st_size
        with target.open("rb") as handle:
            head = handle.read(_BINARY_SNIFF)
            if b"\x00" in head:
                raise ToolError(
                    f"{self.relative(target)} looks binary; refusing to read it as text"
                )
            handle.seek(0)
            raw = handle.read(self.max_file_bytes + 1)
        truncated = len(raw) > self.max_file_bytes or size > self.max_file_bytes
        raw = raw[: self.max_file_bytes]
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total_lines = len(lines)
        if start_line > 1 or max_lines:
            start = max(1, start_line) - 1
            end = None if not max_lines else start + max(0, max_lines)
            lines = lines[start:end]
        return {
            "path": self.relative(target),
            "bytes": size,
            "sha256": sha256_bytes(raw),
            "truncated": truncated,
            "total_lines": total_lines,
            "line_count": len(lines),
            "content": "\n".join(lines),
        }

    def list_dir(self, path: str = ".", *, limit: int = 500) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists():
            raise ToolError(f"no such directory: {self.relative(target)}")
        if not target.is_dir():
            raise ToolError(f"{self.relative(target)} is not a directory")
        entries: list[dict[str, Any]] = []
        for child in sorted(
            target.iterdir(), key=lambda p: (p.is_dir() is False, p.name.lower())
        ):
            try:
                stat = child.stat()
            except OSError:  # broken symlink
                entries.append(
                    {"name": child.name, "kind": "link", "size": 0, "modified_ms": None}
                )
                continue
            entries.append(
                {
                    "name": child.name,
                    "kind": "dir"
                    if child.is_dir()
                    else ("link" if child.is_symlink() else "file"),
                    "size": stat.st_size if child.is_file() else None,
                    "modified_ms": int(stat.st_mtime * 1000),
                }
            )
        return {
            "path": self.relative(target),
            "count": len(entries),
            "truncated": len(entries) > limit,
            "entries": entries[:limit],
        }

    def probe_file(
        self, path: str, *, head_bytes: int = 4096, hash_limit: int = 64 * 1024 * 1024
    ) -> dict[str, Any]:
        """What a file *is*: its size, a hash, and the first bytes, without decoding it as text.

        `read_text` refuses a binary file on purpose - decoding a PNG as utf-8 and calling the
        result a document is how a media pipeline starts lying. This reads the head as bytes and
        hashes the file, so a caller can measure an image or a recording without the file ever
        being mistaken for text.
        """
        target = self.resolve(path)
        if not target.exists():
            raise ToolError(f"no such file: {self.relative(target)}")
        if target.is_dir():
            raise ToolError(f"{self.relative(target)} is a directory (use fs.list)")
        size = target.stat().st_size
        head_limit = max(1, min(int(head_bytes), 65_536))
        with target.open("rb") as handle:
            head = handle.read(head_limit)
            if size > hash_limit:
                # Hashing a huge file would mean reading all of it on every probe. The hash of
                # the head is still a hash; it is a different claim, and the result says which.
                digest = hashlib.sha256(head)
                scope = f"first {len(head)} bytes"
            else:
                digest = hashlib.sha256()
                handle.seek(0)
                remaining = size
                while remaining > 0:
                    block = handle.read(min(1_048_576, remaining))
                    if not block:
                        break
                    digest.update(block)
                    remaining -= len(block)
                scope = "whole file"
        return {
            "path": self.relative(target),
            "bytes": size,
            "sha256": digest.hexdigest(),
            "sha256_scope": scope,
            "head_hex": head.hex(" "),
            "head_bytes": len(head),
            "binary": b"\x00" in head[:1024],
        }

    def stat(self, path: str) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists() and not target.is_symlink():
            return {"path": self.relative(target), "exists": False}
        info = target.lstat()
        return {
            "path": self.relative(target),
            "exists": True,
            "kind": "dir"
            if target.is_dir()
            else ("link" if target.is_symlink() else "file"),
            "bytes": info.st_size,
            "modified_ms": int(info.st_mtime * 1000),
        }
