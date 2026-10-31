"""Vocabulary and defaults for memory governance."""

from __future__ import annotations

import re


MEMORY_TABLES = (
    "memories",
    "memory_history",
    "memory_sources",
    "memory_retrievals",
    "learning_events",
)

KINDS = ("active", "permanent", "archival", "project", "solution", "learning")

SCOPES = ("global", "project", "conversation", "task", "learner")

CATEGORIES = (
    "goal",
    "constraint",
    "pending_step",
    "decision",
    "temporary_decision",
    "preference",
    "fact",
    "instruction",
    "history",
    "architecture",
    "requirement",
    "known_issue",
    "build_command",
    "test_command",
    "accepted_decision",
    "solution",
    "finding",
    "progress",
    "mistake",
    "strength",
    "unresolved_concept",
    "recommendation",
    "tool_state",
    "note",
)

VERIFICATION_STATES = ("verified", "reported", "unverified", "failed", "retired")

SOURCE_TYPES = (
    "user",
    "model",
    "tool",
    "import",
    "system",
    "experiment",
    "document",
    "web",
)

NEVER_INJECTED = ("archival",)

INJECTABLE = ("active", "permanent", "project", "solution", "learning")

MAX_TITLE = 300

MAX_CONTENT = 200_000

_WORD_RE = re.compile(r"[a-z0-9_]{2,}", re.IGNORECASE)

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "your",
    "you",
    "are",
    "was",
    "were",
    "has",
    "have",
    "had",
    "not",
    "but",
    "all",
    "any",
    "can",
    "will",
    "would",
    "should",
    "there",
    "their",
    "them",
    "then",
    "than",
    "when",
    "what",
    "which",
    "while",
    "about",
    "also",
    "使用",
    "und",
    "der",
    "die",
    "das",
}
