"""Shared CLI formatting, exit codes and permission-aware command helpers."""

from __future__ import annotations

import argparse


import sys


from typing import Any, Sequence


from archx_agent.application.workspace import Workspace, open_workspace


from archx_agent.helpers.exceptions import (
    ArchxError,
    PermissionDeniedError,
    PathEscapesRootError,
    ToolError,
    ToolValidationError,
    ValidationError,
)


from archx_agent.helpers.jsonio import json_text


EXIT_OK = 0


EXIT_ERROR = 1


EXIT_USAGE = 2


EXIT_DENIED = 4


EXIT_UNAVAILABLE = 5


EXIT_DEGRADED = 3  # the command ran but the thing it checked is not healthy


def emit(text: str = "") -> None:
    print(text)


def emit_json(data: Any) -> None:
    print(json_text(data))


def table(rows: Sequence[Sequence[Any]], headers: Sequence[str]) -> str:
    cells = [[str(c) for c in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in cells:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], min(len(cell), 60))
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    out.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in cells:
        out.append("  ".join(cell[:60].ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(out)


def fail(message: str, code: int = EXIT_ERROR) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def _is_loopback(url: str | None) -> bool:
    from archx_agent.managers.providers import is_loopback_url

    return is_loopback_url(url)


def _workspace(args: argparse.Namespace, *, create: bool = True) -> Workspace:
    return open_workspace(
        home=args.home,
        config_path=args.config,
        overrides=None,
        allow_test_double=getattr(args, "allow_simulated", False),
    )


def _require(simulated_ok: bool, allow: bool) -> bool:
    return bool(allow or simulated_ok)


def _parse_tool_args(pairs: Sequence[str] | None) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValidationError(f"--arg expects key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ValidationError(f"--arg expects a name before '=', got {pair!r}")
        if key in args:
            raise ValidationError(f"--arg {key} given twice")
        args[key] = value
    return args


def _execute_tool(
    ws, manager, name: str, arguments: dict[str, Any], args: argparse.Namespace
) -> int:
    """Run one tool through the registry and report the outcome consistently."""
    from archx_agent.managers.tools import ToolContext

    context = ToolContext(
        conversation_id=getattr(args, "conversation", None),
        task_id=getattr(args, "task", None),
        project_id=getattr(args, "project", None),
        purpose=getattr(args, "purpose", None) or "",
    )
    try:
        run = manager.execute(
            name,
            arguments,
            dry_run=bool(getattr(args, "dry_run", False)),
            context=context,
            requester="cli",
        )
    except (PermissionDeniedError, ToolError, ArchxError) as exc:
        payload = {
            "tool": name,
            "status": "denied" if isinstance(exc, PermissionDeniedError) else "error",
            "error": exc.message,
            "approval_id": getattr(exc, "approval_id", None),
            "capability": getattr(exc, "capability", None),
            "run": getattr(exc, "run", None).to_dict()
            if getattr(exc, "run", None)
            else None,
        }
        if args.json:
            emit_json(payload)
        else:
            print(f"{payload['status']}: {exc.message}", file=sys.stderr)
            if payload["approval_id"]:
                print(
                    f"approve with: archx-agent approvals approve {payload['approval_id']}",
                    file=sys.stderr,
                )
        if isinstance(exc, PermissionDeniedError):
            return EXIT_DENIED
        if isinstance(exc, PathEscapesRootError):
            return EXIT_DENIED
        if isinstance(exc, ToolValidationError):
            return EXIT_USAGE
        if isinstance(exc, ToolError):
            return EXIT_ERROR
        return EXIT_USAGE
    data = run.to_dict()
    if args.json:
        emit_json(data)
    else:
        if run.dry_run:
            emit("[dry run] nothing was changed on disk")
        emit(f"{run.tool} {run.status} in {run.duration_ms}ms  (run {run.id})")
        if run.result:
            emit_json(run.result)
        if run.error:
            emit(f"error: {run.error}")
    return EXIT_OK if run.ok else EXIT_ERROR


def _pairs(pairs: Sequence[str] | None, *, flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValidationError(f"{flag} expects key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        out[key.strip()] = value
    return out


def _metric(value: Any) -> str:
    """A count prints as a count; a measurement prints with four decimals."""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.4f}"
    return str(value)
