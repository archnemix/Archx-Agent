"""Real subprocess checks: bounded output reads, isolated environment, refusals."""

from __future__ import annotations

from dataclasses import is_dataclass
import os
import shlex
import sys

import pytest

from archx_agent.adapters.local_tools import LocalToolRuntime
from archx_agent.helpers.exceptions import (
    ToolError,
    ToolValidationError,
    PathEscapesRootError,
)


def command(code):
    return shlex.join([sys.executable, "-c", code])


@pytest.mark.parametrize(
    "field", ["max_output_bytes", "max_file_bytes", "timeout_seconds"]
)
@pytest.mark.parametrize("value", [0, -1, True, 1.2, "3"])
def test_positive_integer_limits(tmp_path, field, value):
    with pytest.raises(ToolValidationError):
        LocalToolRuntime((str(tmp_path),), **{field: value})


@pytest.mark.parametrize("timeout", [0, -1, True, 1.5, "2"])
def test_invalid_call_timeout(tmp_path, timeout):
    with pytest.raises(ToolValidationError):
        LocalToolRuntime((str(tmp_path),)).run(
            command("print('not run')"), timeout=timeout
        )


def test_spooled_output_and_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_TEST_SECRET", "do-not-inherit")
    runtime = LocalToolRuntime((str(tmp_path),), max_output_bytes=128)
    assert is_dataclass(runtime)
    result = runtime.run(
        command(
            "import os,sys; print(os.getenv('ARCHX_TEST_SECRET', 'absent')); print('x'*1000000); sys.stderr.write('e'*1000000)"
        )
    )
    assert result["exit_code"] == 0
    assert result["stdout"].startswith("absent\n")
    assert "do-not-inherit" not in result["stdout"]
    assert (
        result["truncated"]
        and len(result["stdout"]) < 256
        and len(result["stderr"]) < 256
    )


def test_command_and_path_refusals(tmp_path):
    runtime = LocalToolRuntime(
        (str(tmp_path),), denylist=(os.path.basename(sys.executable),)
    )
    with pytest.raises(ToolError, match="denylist"):
        runtime.run(command("print('not run')"))
    with pytest.raises(ToolError):
        runtime.run("missing-archx-command")
    with pytest.raises(PathEscapesRootError):
        # Root escape has a dedicated path-domain refusal.
        runtime.run("echo test", cwd="../outside")


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group contract")
def test_timeout_kills_child_group(tmp_path):
    # Without group termination the grandchild writes this marker after the parent dies.
    runtime = LocalToolRuntime((str(tmp_path),), timeout_seconds=1)
    marker = tmp_path / "escaped.txt"
    child = f"import time,pathlib; time.sleep(2); pathlib.Path({str(marker)!r}).write_text('escaped')"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); print('started',flush=True); time.sleep(20)"
    result = runtime.run(command(parent))
    assert result["timed_out"] and result["exit_code"] is None
    assert "started" in result["stdout"] and "killed after 1s" in result["stderr"]
    # A separate bounded command provides time for an escaped grandchild to finish.
    runtime.run(command("import time; time.sleep(2)"), timeout=4)
    assert not marker.exists()
