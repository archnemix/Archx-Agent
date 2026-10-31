"""Vocabulary and defaults for learning records."""

from __future__ import annotations


LEARNING_TABLES = (
    "learning_goals",
    "learning_lessons",
    "learning_sessions",
    "learning_attempts",
)

LEVELS = ("beginner", "intermediate", "advanced")

GOAL_STATUSES = ("active", "paused", "completed", "abandoned")

TERMINAL_GOALS = frozenset({"completed", "abandoned"})

ITEM_STATUSES = ("new", "learning", "review", "mastered")

SESSION_MODES = ("explain", "practice", "review")

SESSION_STATUSES = ("open", "closed")

GRADERS = ("exact", "self", "model")

PLANNERS = ("model", "rules", "user")

DEFAULT_MASTERY_STREAK = 4
