"""Real extension subprocess boundaries, without implying an OS sandbox."""

from __future__ import annotations

import os
import sys
import time

import pytest

from archx_agent.adapters.extension_runtime import ExtensionRuntime
from archx_agent.helpers.exceptions import (
    ExtensionError,
    ToolTimeoutError,
    ToolValidationError,
)


def run(runtime, tmp_path, code, **kwargs):
    return runtime.run([sys.executable, "-c", code], {}, cwd=str(tmp_path), **kwargs)


@pytest.mark.parametrize("field", ["max_output_bytes", "timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "3", None])
def test_invalid_constructor_limits(field, value):
    with pytest.raises(ToolValidationError):
        ExtensionRuntime(**{field: value})


@pytest.mark.parametrize("timeout", [0, -1, True, 1.5, "3"])
def test_invalid_call_timeout(tmp_path, timeout):
    with pytest.raises(ToolValidationError):
        run(ExtensionRuntime(), tmp_path, "print('{}')", timeout=timeout)


@pytest.mark.parametrize(
    "argv", [None, [], "python", [""], [9], [sys.executable, "\0"]]
)
def test_invalid_argv(tmp_path, argv):
    with pytest.raises(ToolValidationError):
        ExtensionRuntime().run(argv, {}, cwd=str(tmp_path))


@pytest.mark.parametrize("payload", [[], None, "text"])
def test_request_must_be_object(tmp_path, payload):
    with pytest.raises(ToolValidationError):
        ExtensionRuntime().run(
            [sys.executable, "-c", "print('{}')"], payload, cwd=str(tmp_path)
        )


@pytest.mark.parametrize(
    "environment", [{"BAD=KEY": "x"}, {"KEY": "\0"}, {"": "x"}, []]
)
def test_invalid_environment(tmp_path, environment):
    with pytest.raises(ToolValidationError):
        run(ExtensionRuntime(), tmp_path, "print('{}')", env_extra=environment)


def test_oversized_valid_json_prefix_cannot_be_accepted(tmp_path):
    with pytest.raises(ExtensionError, match="stdout exceeds 64 bytes"):
        run(
            ExtensionRuntime(max_output_bytes=64),
            tmp_path,
            "import sys; sys.stdout.write('{}'+' '*1000000)",
        )


def test_utf8_bytes_not_character_count(tmp_path):
    with pytest.raises(ExtensionError, match="stdout exceeds"):
        run(
            ExtensionRuntime(max_output_bytes=32),
            tmp_path,
            "print('{\"text\":\"'+'ا'*20+'\"}')",
        )


def test_invalid_utf8_is_domain_error(tmp_path):
    with pytest.raises(ExtensionError, match="UTF-8"):
        run(
            ExtensionRuntime(),
            tmp_path,
            "import sys; sys.stdout.buffer.write(b'\\xff')",
        )


def test_stderr_is_bounded_and_truncation_cannot_be_spoofed(tmp_path):
    result = run(
        ExtensionRuntime(max_output_bytes=128),
        tmp_path,
        "import sys; print('{\"ok\":true,\"stderr_truncated\":false}'); sys.stderr.write('x'*1000000)",
    )
    assert result["ok"] and result["stderr_truncated"] is True
    assert len(result["stderr"]) <= 128


def test_stdin_and_environment_and_empty_argv_argument(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHX_EXTENSION_SECRET", "not-inherited")
    result = ExtensionRuntime().run(
        [
            sys.executable,
            "-c",
            "import json,os,sys; x=json.load(sys.stdin); print(json.dumps({'value':x['value'],'arg':sys.argv[1],'secret':os.getenv('ARCHX_EXTENSION_SECRET')}))",
            "",
        ],
        {"value": "اردو"},
        cwd=str(tmp_path),
    )
    assert (
        result["value"] == "اردو" and result["arg"] == "" and result["secret"] is None
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup only")
def test_timeout_terminates_descendants_in_the_session(tmp_path):
    marker = tmp_path / "escaped"
    child = f"import time,pathlib;time.sleep(2);pathlib.Path({str(marker)!r}).write_text('escaped')"
    parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(20)"
    with pytest.raises(ToolTimeoutError):
        run(ExtensionRuntime(timeout_seconds=1), tmp_path, parent)
    time.sleep(2)
    assert not marker.exists()
