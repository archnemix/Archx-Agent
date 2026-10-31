"""Learning goals, reviewable items, sessions and attempts.

Learning Mode is not "a chat with the word 'lesson' in it". It is four records that make
progress checkable:

``goal``
    what is being learned, why, and what would count as finished. A goal is never marked
    complete because time passed - the user closes it, against criteria they wrote.
``item``
    one thing worth being able to recall or do, with an optional expected answer, an ordered
    list of hints and an explanation. Each item carries its own *schedule*: interval, ease,
    streak, lapses and due date, all stored so a review can be explained rather than guessed.
``session``
    a sitting: which goal, which mode (explain / practice / review), what was attempted and by
    whom it was graded. A session is also a task, like every other piece of work in the app.
``attempt``
    one answer, the grade, who graded it, how many hints were used, and the schedule change it
    caused. This is the row that makes "you are improving" a claim with evidence.

The tables were reserved in v8; v19 added the columns and the two child tables. The rule is
unchanged: one store, one writer, journaled writes, and no derived truth that is not stored.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .manager import LearningManager as LearningManager
from .constants import (
    LEARNING_TABLES as LEARNING_TABLES,
    LEVELS as LEVELS,
    GOAL_STATUSES as GOAL_STATUSES,
    TERMINAL_GOALS as TERMINAL_GOALS,
    ITEM_STATUSES as ITEM_STATUSES,
    SESSION_MODES as SESSION_MODES,
    SESSION_STATUSES as SESSION_STATUSES,
    GRADERS as GRADERS,
    PLANNERS as PLANNERS,
    DEFAULT_MASTERY_STREAK as DEFAULT_MASTERY_STREAK,
)
from .records import (
    LearningGoal as LearningGoal,
    LearningItem as LearningItem,
    LearningSession as LearningSession,
    LearningAttempt as LearningAttempt,
    _goal_from_row as _goal_from_row,
    _item_from_row as _item_from_row,
    _session_from_row as _session_from_row,
    _attempt_from_row as _attempt_from_row,
)
from .formatting import _json as _json, _norm as _norm, due_in as due_in


__all__ = [
    "GRADERS",
    "GOAL_STATUSES",
    "ITEM_STATUSES",
    "LEARNING_TABLES",
    "LEVELS",
    "LearningAttempt",
    "LearningGoal",
    "LearningItem",
    "LearningManager",
    "LearningSession",
    "PLANNERS",
    "SESSION_MODES",
    "SESSION_STATUSES",
    "TERMINAL_GOALS",
    "due_in",
]
