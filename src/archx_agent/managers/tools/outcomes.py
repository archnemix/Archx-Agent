"""Outcomes operations for tool execution."""

from __future__ import annotations

from typing import Any

from archx_agent.managers.tools.records import ToolSpec


def _result_ok(spec: ToolSpec, result: dict[str, Any]) -> bool:
    if spec.name == "shell.run":
        return result.get("exit_code") == 0 and not result.get("timed_out")
    return True


def _failure_reason(spec: ToolSpec, result: dict[str, Any]) -> str:
    if spec.name == "shell.run":
        if result.get("timed_out"):
            return f"command timed out after {result.get('timeout_seconds')}s"
        return f"command exited with {result.get('exit_code')}"
    return "the tool reported a failure"


def _elapsed_ms(started_at: str, ended_at: str) -> float:
    from archx_agent.helpers.timeutil import parse_iso

    return round(
        (parse_iso(ended_at) - parse_iso(started_at)).total_seconds() * 1000, 3
    )
