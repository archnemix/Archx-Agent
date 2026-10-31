"""Vocabulary and defaults for context windows."""

from __future__ import annotations

from typing import Callable, Sequence

from archx_agent.managers.conversation import Message


CONTEXT_TABLES = ("context_manifests", "summaries")

STRATEGIES = ("oldest_first", "summarize", "ai_select", "manual", "ai_proposed")

Summarizer = Callable[[Sequence[Message], str], str]
