"""Vocabulary and defaults for workflow definitions."""

from __future__ import annotations

import re
from typing import Any


WORKFLOW_TABLES = ("workflows", "workflow_steps")

STEP_KINDS = ("model", "tool", "memory", "note", "checkpoint", "subagent")

MODES = ("user", "ai")

STATUSES = ("proposed", "approved", "running", "completed", "failed", "cancelled")

TERMINAL = frozenset({"completed", "failed", "cancelled"})

MAX_DEPTH = 2

_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-]+)\s*\}\}")

_STEP_KEYS = {
    "kind",
    "title",
    "prompt",
    "tool",
    "args",
    "query",
    "text",
    "goal",
    "steps",
    "model",
    "continue_on_error",
    "limit",
}

TEMPLATES: dict[str, dict[str, Any]] = {
    "summarise-file": {
        "name": "summarise-file",
        "goal": "Read a file and summarise it",
        "mode": "user",
        "steps": [
            {
                "kind": "tool",
                "title": "read the file",
                "tool": "fs.read",
                "args": {"path": "{{input.path}}", "max_lines": 400},
            },
            {
                "kind": "model",
                "title": "summarise",
                "prompt": "Summarise the following file in three bullet points. Do not invent facts.\n\n{{step.1.output}}",
            },
            {"kind": "note", "title": "provenance", "text": "source: {{input.path}}"},
        ],
    },
    "check-and-report": {
        "name": "check-and-report",
        "goal": "Check the workspace facts and record a short report",
        "mode": "user",
        "steps": [
            {
                "kind": "tool",
                "title": "workspace facts",
                "tool": "archx.info",
                "args": {},
            },
            {
                "kind": "checkpoint",
                "title": "human gate",
                "text": "review the facts before reporting",
            },
            {
                "kind": "model",
                "title": "report",
                "prompt": "Write a five-line status report from these facts:\n{{step.1.output}}",
            },
        ],
    },
}
