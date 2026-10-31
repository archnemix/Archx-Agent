"""Vocabulary and defaults for tool execution."""

from __future__ import annotations

from archx_agent.managers.tools.records import ToolSpec


TOOL_TABLES = ("tool_runs",)

BUILTIN_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="fs.read",
        summary="read a text file inside the tool roots",
        capability="fs.read",
        risk="low",
        inputs={
            "path": "file path, relative to a tool root or absolute inside one",
            "start_line": "first line to return (1-based)",
            "max_lines": "how many lines to return",
        },
        required=("path",),
        types={"path": "str", "start_line": "int", "max_lines": "int"},
        side_effects="reads a file",
    ),
    ToolSpec(
        name="fs.list",
        summary="list a directory inside the tool roots",
        capability="fs.read",
        risk="low",
        inputs={"path": "directory path (default '.')", "limit": "maximum entries"},
        types={"path": "str", "limit": "int"},
        side_effects="reads a directory",
    ),
    ToolSpec(
        name="fs.probe",
        summary="measure a file's bytes - size, hash and container header - without reading it as text",
        capability="fs.read",
        risk="low",
        inputs={
            "path": "file path inside a tool root",
            "head_bytes": "how many leading bytes to return (default 4096, at most 65536)",
        },
        required=("path",),
        types={"path": "str", "head_bytes": "int"},
        side_effects="reads the first bytes of a file and hashes it",
    ),
    ToolSpec(
        name="fs.write",
        summary="create or modify a text file inside the tool roots",
        capability="fs.write",
        risk="medium",
        inputs={
            "path": "file path inside a tool root",
            "content": "text to write",
            "create_parents": "create missing parent directories",
            "append": "append instead of replacing",
        },
        required=("path", "content"),
        types={
            "path": "str",
            "content": "str",
            "create_parents": "bool",
            "append": "bool",
        },
        supports_dry_run=True,
        side_effects="writes a file",
    ),
    ToolSpec(
        name="fs.write_bytes",
        summary="write bytes exactly as given (a container, not a document) inside the tool roots",
        capability="fs.write",
        risk="medium",
        inputs={
            "path": "file path inside a tool root",
            "content_base64": "the bytes, base64-encoded (JSON has no byte string)",
            "create_parents": "create missing parent directories",
        },
        required=("path", "content_base64"),
        types={"path": "str", "content_base64": "str", "create_parents": "bool"},
        supports_dry_run=True,
        side_effects="writes a file",
    ),
    ToolSpec(
        name="fs.delete",
        summary="delete a file inside the tool roots",
        capability="fs.delete",
        risk="high",
        inputs={"path": "file path inside a tool root"},
        required=("path",),
        types={"path": "str"},
        supports_dry_run=True,
        side_effects="deletes a file",
    ),
    ToolSpec(
        name="shell.run",
        summary="run a local command (argv form, no shell)",
        capability="shell.run",
        risk="high",
        inputs={
            "command": "command line, split like a shell would but executed without a shell",
            "cwd": "working directory inside the tool roots (default: the first root)",
            "timeout": "seconds before the process is killed",
        },
        required=("command",),
        types={"command": "str", "cwd": "str", "timeout": "int"},
        side_effects="executes a process",
    ),
    ToolSpec(
        name="net.fetch",
        summary="fetch a text document from an http(s) URL",
        capability="net.fetch",
        risk="medium",
        inputs={
            "url": "http(s) URL to fetch",
            "timeout": "seconds before the request is abandoned",
            "max_bytes": "stop after this many bytes",
            "max_redirects": "how many redirects to follow",
            "allow_private_hosts": "permit private/loopback addresses (still needs the grant)",
        },
        required=("url",),
        types={
            "url": "str",
            "timeout": "int",
            "max_bytes": "int",
            "max_redirects": "int",
            "allow_private_hosts": "bool",
        },
        side_effects="reads a remote document; sends the request to that host",
    ),
    ToolSpec(
        name="archx.info",
        summary="report workspace size and tool roots (read-only, no permission needed)",
        capability=None,
        risk="low",
        inputs={},
        side_effects="none",
    ),
)

BUILTIN_TOOLS = {spec.name: spec for spec in BUILTIN_SPECS}
