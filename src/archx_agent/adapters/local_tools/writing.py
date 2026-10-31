"""LocalToolRuntime writing."""

from __future__ import annotations

from typing import Any

from archx_agent.helpers.exceptions import (
    ToolError,
)
from archx_agent.adapters.local_tools.hashing import sha256_bytes


class LocalToolRuntimeWritingMixin:
    """Writing responsibility for LocalToolRuntime."""

    def write_bytes(
        self,
        path: str,
        payload: bytes,
        *,
        create_parents: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Write bytes exactly as given.

        ``write_text`` encodes its argument as UTF-8, which is right for a document and wrong for a
        container: a binary STL is 80 header bytes, a count and 50 bytes per triangle, and turning it
        into text produces a different file with the same name. Same resolution rules, same size
        limit, same dry-run - only the encoding step is gone.
        """
        target = self.resolve(path)
        if target.exists() and target.is_dir():
            raise ToolError(f"{self.relative(target)} is a directory")
        if len(payload) > self.max_file_bytes:
            raise ToolError(
                f"refusing to write {len(payload)} bytes; tools.max_file_bytes is "
                f"{self.max_file_bytes}"
            )
        existed = target.exists()
        previous_bytes = 0
        previous_sha = None
        if existed:
            previous = target.read_bytes()
            previous_bytes = len(previous)
            previous_sha = sha256_bytes(previous)
        parent = target.parent
        if not parent.is_dir():
            if not create_parents:
                raise ToolError(
                    f"parent directory does not exist: {self.relative(parent)}"
                )
            if not dry_run:
                parent.mkdir(parents=True, exist_ok=True)
        digest = sha256_bytes(payload)
        if not dry_run:
            target.write_bytes(payload)
            final_size = target.stat().st_size
        else:
            final_size = len(payload)
        return {
            "path": self.relative(target),
            "bytes_written": len(payload),
            "bytes_after": final_size,
            "sha256": digest,
            "existed": existed,
            "previous_bytes": previous_bytes,
            "previous_sha256": previous_sha,
            "dry_run": dry_run,
        }

    def write_text(
        self,
        path: str,
        content: str,
        *,
        create_parents: bool = True,
        append: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        target = self.resolve(path)
        if target.exists() and target.is_dir():
            raise ToolError(f"{self.relative(target)} is a directory")
        encoded = content.encode("utf-8")
        if len(encoded) > self.max_file_bytes:
            raise ToolError(
                f"refusing to write {len(encoded)} bytes; tools.max_file_bytes is {self.max_file_bytes}"
            )
        existed = target.exists()
        previous_sha = None
        previous_bytes = 0
        if existed:
            previous = target.read_bytes()
            previous_bytes = len(previous)
            previous_sha = sha256_bytes(previous)
        parent = target.parent
        if not parent.is_dir():
            if not create_parents:
                raise ToolError(
                    f"parent directory does not exist: {self.relative(parent)}"
                )
            if dry_run:
                pass  # reported below, not created
            else:
                parent.mkdir(parents=True, exist_ok=True)
        digest = sha256_bytes(encoded)
        if not dry_run:
            mode = "ab" if append else "wb"
            with target.open(mode) as handle:
                handle.write(encoded)
            final_size = target.stat().st_size
        else:
            final_size = (previous_bytes if append else 0) + len(encoded)
        return {
            "path": self.relative(target),
            "bytes_written": len(encoded),
            "bytes_after": final_size,
            "sha256": digest,
            "existed": existed,
            "previous_sha256": previous_sha,
            "previous_bytes": previous_bytes,
            "append": append,
            "dry_run": dry_run,
        }

    def delete(self, path: str, *, dry_run: bool = False) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists() and not target.is_symlink():
            raise ToolError(f"no such file: {self.relative(target)}")
        if target.is_dir():
            raise ToolError(
                f"{self.relative(target)} is a directory; recursive deletion is not implemented "
                "(delete files individually)"
            )
        size = target.stat().st_size
        digest = sha256_bytes(target.read_bytes()[: self.max_file_bytes])
        if not dry_run:
            target.unlink()
        return {
            "path": self.relative(target),
            "bytes": size,
            "sha256": digest,
            "deleted": not dry_run,
            "dry_run": dry_run,
        }
