"""Vocabulary and defaults for task history."""

from __future__ import annotations


TASK_TABLES = ("tasks", "task_log", "artifacts")

TASK_TYPES = (
    "chat",
    "tool",
    "memory",
    "context",
    "agent",
    "research",
    "coding",
    "learning",
    "experiment",
    "training",
    "dataset",
    "game",
    "automation",
    "maintenance",
    "system",
)

TASK_STATUSES = ("queued", "running", "completed", "failed", "cancelled", "interrupted")

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})

_LIST_COLUMNS = {"agents", "tools", "input_refs", "output_refs", "unresolved"}

_JSON_COLUMNS = {"resource_use", "version_info", "metadata"}
