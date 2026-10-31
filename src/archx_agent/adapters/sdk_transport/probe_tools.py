"""Probe tools operations for vendor SDK transport."""

from __future__ import annotations


_OPENAI_PROBE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "record_value",
            "description": "Record one integer value.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
        },
    }
]
