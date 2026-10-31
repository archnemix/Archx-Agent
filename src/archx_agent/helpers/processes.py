"""Disk-spooled process execution with bounded output reads, not OS isolation.

Permission policy, environment construction and domain errors belong to callers.
Spools have no byte quota. Background/detached descendants can outlive the direct
process; Windows cleanup only kills that process, not an entire process tree.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import signal
import subprocess
import tempfile
import time
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    duration_ms: float


def positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _kill(process: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    process.wait()


def run_spooled(
    command: Sequence[str] | str,
    *,
    cwd: str,
    env: Mapping[str, str],
    timeout: int,
    max_output_bytes: int,
    input_bytes: bytes | None = None,
    shell: bool = False,
) -> ProcessResult:
    """Read at most cap+1 bytes per stream; the extra byte signals truncation.

    Use shell=True only for an explicitly trusted shell execution interface. Input
    is spooled too, avoiding a blocking stdin pipe outside the process deadline.
    Exceptions/caller cancellation terminate the same POSIX group before propagating.
    """
    positive_integer(timeout, "timeout")
    positive_integer(max_output_bytes, "max_output_bytes")
    if shell != isinstance(command, str):
        raise ValueError(
            "shell commands must be strings; argv commands must be sequences"
        )
    started = time.perf_counter()
    with (
        tempfile.TemporaryFile() as out,
        tempfile.TemporaryFile() as err,
        tempfile.TemporaryFile() as stdin,
    ):
        if input_bytes is not None:
            stdin.write(input_bytes)
            stdin.seek(0)
        process = subprocess.Popen(  # noqa: S603,S602 - explicit caller-controlled shell policy
            command,
            cwd=cwd,
            env=dict(env),
            shell=shell,
            stdin=stdin,
            stdout=out,
            stderr=err,
            start_new_session=os.name == "posix",
        )
        timed_out = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(process)
            code = None
        except BaseException:
            _kill(process)
            raise
        out.seek(0)
        err.seek(0)
        return ProcessResult(
            code,
            out.read(max_output_bytes + 1),
            err.read(max_output_bytes + 1),
            timed_out,
            round((time.perf_counter() - started) * 1000, 3),
        )
