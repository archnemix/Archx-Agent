"""Local filesystem and process operations used by the built-in tools.

This module **executes**; it never decides whether it may. Every call is made by
``managers/tools.py`` *after* the permission centre said yes, and the only thing
keeping a path inside the sandbox is :func:`archx_agent.helpers.paths.resolve_within`
- not the caller's good manners.

Deliberate choices:

* No shell. ``shell.run`` splits its command with :func:`shlex.split` and calls
  :func:`subprocess.run` with ``shell=False``, so ``;`` and ``|`` are literal
  arguments rather than a second, unreviewed command line.
* A child process gets a minimal environment: ``PATH``, ``HOME`` (the Archx home,
  not the real one), ``LANG`` and ``TMPDIR``. Nothing else - no API keys, no
  ``ARCHX_*`` overrides, so a tool cannot read the agent's own credentials.
* Output is capped and marked truncated instead of being silently dropped.
* Every operation reports what it touched (path, bytes, hash) so the trace can
  answer "what exactly changed?".
"""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from archx_agent.helpers.exceptions import (
    PathError,
    PathEscapesRootError,
    ToolError,
    ToolTimeoutError,
    ToolValidationError,
)
from archx_agent.helpers.paths import resolve_within

_BINARY_SNIFF = 8192


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class LocalToolRuntime:
    """Runs local operations inside a fixed set of roots."""

    roots: tuple[str, ...]
    max_file_bytes: int = 2_000_000
    max_output_bytes: int = 200_000
    timeout_seconds: int = 60
    denylist: tuple[str, ...] = ()
    home: str | None = None

    def __post_init__(self) -> None:
        if not self.roots:
            raise ToolValidationError("tool runtime needs at least one root directory")
        self._resolved_roots = tuple(Path(r).expanduser().resolve() for r in self.roots)
        for root in self._resolved_roots:
            if not root.is_dir():
                raise ToolValidationError(f"tool root is not a directory: {root}")

    # -- path handling ----------------------------------------------------
    @property
    def resolved_roots(self) -> tuple[Path, ...]:
        return self._resolved_roots

    def resolve(self, path: str | os.PathLike[str]) -> Path:
        """Resolve ``path`` inside the roots, or refuse with the roots named."""
        candidate = str(path or "").strip()
        if not candidate:
            raise ToolValidationError("a path is required")
        if Path(candidate).expanduser().is_absolute():
            absolute = Path(candidate).expanduser()
            for root in self._resolved_roots:
                try:
                    return resolve_within(root, absolute)
                except PathEscapesRootError:
                    continue
            raise PathEscapesRootError(
                "path is outside every tool root",
                path=str(absolute),
                root=", ".join(str(r) for r in self._resolved_roots),
            )
        errors: list[str] = []
        for root in self._resolved_roots:
            try:
                return resolve_within(root, candidate)
            except PathEscapesRootError as exc:
                errors.append(exc.message)
            except PathError as exc:  # pragma: no cover - root missing at runtime
                errors.append(exc.message)
        raise PathEscapesRootError(
            "path is outside every tool root",
            path=candidate,
            root=", ".join(str(r) for r in self._resolved_roots),
        )

    def relative(self, path: Path) -> str:
        for root in self._resolved_roots:
            try:
                return str(path.relative_to(root)) or "."
            except ValueError:
                continue
        return str(path)  # pragma: no cover - resolve() guarantees containment

    # -- read -------------------------------------------------------------
    def read_text(self, path: str, *, start_line: int = 1, max_lines: int | None = None) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists():
            raise ToolError(f"no such file: {self.relative(target)}")
        if target.is_dir():
            raise ToolError(f"{self.relative(target)} is a directory (use fs.list)")
        size = target.stat().st_size
        with target.open("rb") as handle:
            head = handle.read(_BINARY_SNIFF)
            if b"\x00" in head:
                raise ToolError(f"{self.relative(target)} looks binary; refusing to read it as text")
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
        for child in sorted(target.iterdir(), key=lambda p: (p.is_dir() is False, p.name.lower())):
            try:
                stat = child.stat()
            except OSError:  # broken symlink
                entries.append({"name": child.name, "kind": "link", "size": 0, "modified_ms": None})
                continue
            entries.append(
                {
                    "name": child.name,
                    "kind": "dir" if child.is_dir() else ("link" if child.is_symlink() else "file"),
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

    # -- probe ------------------------------------------------------------
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

    # -- write ------------------------------------------------------------
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
                raise ToolError(f"parent directory does not exist: {self.relative(parent)}")
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
                raise ToolError(f"parent directory does not exist: {self.relative(parent)}")
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

    def stat(self, path: str) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists() and not target.is_symlink():
            return {"path": self.relative(target), "exists": False}
        info = target.lstat()
        return {
            "path": self.relative(target),
            "exists": True,
            "kind": "dir" if target.is_dir() else ("link" if target.is_symlink() else "file"),
            "bytes": info.st_size,
            "modified_ms": int(info.st_mtime * 1000),
        }

    # -- execute ----------------------------------------------------------
    def run(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        text = (command or "").strip()
        if not text:
            raise ToolValidationError("a command is required")
        try:
            argv = shlex.split(text)
        except ValueError as exc:
            raise ToolValidationError(f"cannot parse the command: {exc}") from exc
        if not argv:
            raise ToolValidationError("a command is required")
        program = Path(argv[0]).name
        if program in set(self.denylist):
            raise ToolError(
                f"{program!r} is on the shell denylist (tools.shell_denylist); "
                "remove it from the list deliberately if you really need it"
            )
        workdir = self.resolve(cwd or ".") if cwd else self._resolved_roots[0]
        if workdir.exists() and not workdir.is_dir():
            raise ToolError(f"cwd is not a directory: {self.relative(workdir)}")
        if not workdir.exists():
            workdir.mkdir(parents=True, exist_ok=True)
        executable = argv[0]
        if shutil.which(executable) is None and not Path(executable).exists():
            raise ToolError(f"command not found: {executable}")
        limit = int(timeout or self.timeout_seconds)
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": self.home or str(workdir),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TMPDIR": tempfile.gettempdir(),
        }
        started = time.perf_counter()
        timed_out = False
        try:
            completed = subprocess.run(  # noqa: S603 - argv list, no shell
                argv,
                cwd=str(workdir),
                env=env,
                capture_output=True,
                timeout=limit,
                check=False,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = None
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
        except OSError as exc:
            raise ToolError(f"could not start {executable!r}: {exc.strerror or exc}") from exc
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        out_text, out_truncated = _clip(stdout, self.max_output_bytes)
        err_text, err_truncated = _clip(stderr, self.max_output_bytes)
        if timed_out:
            stderr_tail = (err_text + f"\n[killed after {limit}s]").strip()
        else:
            stderr_tail = err_text
        return {
            "argv": argv,
            "cwd": self.relative(workdir),
            "exit_code": returncode,
            "stdout": out_text,
            "stderr": stderr_tail,
            "timed_out": timed_out,
            "timeout_seconds": limit,
            "duration_ms": duration_ms,
            "truncated": out_truncated or err_truncated,
        }

    def limits(self) -> dict[str, Any]:
        return {
            "roots": [str(r) for r in self._resolved_roots],
            "max_file_bytes": self.max_file_bytes,
            "max_output_bytes": self.max_output_bytes,
            "timeout_seconds": self.timeout_seconds,
            "shell_denylist": list(self.denylist),
        }


def _clip(raw: bytes | str, limit: int) -> tuple[str, bool]:
    if isinstance(raw, str):
        text = raw
        truncated = len(text.encode("utf-8")) > limit
        if truncated:
            text = text.encode("utf-8")[:limit].decode("utf-8", errors="replace")
        return text, truncated
    truncated = len(raw) > limit
    return raw[:limit].decode("utf-8", errors="replace"), truncated


def default_roots(*candidates: str | None) -> tuple[str, ...]:
    """First non-empty candidate wins; used to pick project root over home workspace."""
    for candidate in candidates:
        if candidate:
            return (str(candidate),)
    return ()


def ensure_roots(candidates: Iterable[str]) -> tuple[str, ...]:
    roots = []
    for candidate in candidates:
        path = Path(candidate).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        roots.append(str(path))
    return tuple(roots)


__all__ = ["LocalToolRuntime", "sha256_bytes", "default_roots", "ensure_roots"]
