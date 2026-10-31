"""Vocabulary and defaults for durable jobs."""

from __future__ import annotations


JOB_TABLES = ("jobs",)

JOB_KINDS = ("command", "workflow", "research")

PAUSABLE_KINDS = frozenset({"workflow"})

STATUSES = (
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
)

TERMINAL = frozenset({"completed", "failed", "cancelled"})

CONTROLS = ("pause", "cancel", None)

DEFAULT_ESTIMATES: dict[str, dict[str, int]] = {
    "command": {"cpu_percent": 25, "memory_mb": 256},
    "workflow": {"cpu_percent": 50, "memory_mb": 512},
    "research": {"cpu_percent": 25, "memory_mb": 512},
}

_UPDATE_COLUMNS = {
    "status",
    "message",
    "error",
    "progress",
    "result",
    "resource_observed",
    "resource_estimate",
    "task_id",
    "project_id",
    "control",
    "cursor",
    "attempts",
    "started_at",
    "ended_at",
    "deadline",
    "pid",
    "worker",
    "requeued_at",
    "cancelled",
    "max_attempts",
    "timeout_seconds",
    "priority",
    "payload",
}

_JSON_COLUMNS = {"payload", "result", "resource_estimate", "resource_observed"}
