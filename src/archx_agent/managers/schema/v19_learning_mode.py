"""Released migration 19: learning_mode. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


LEARNING_V19 = Migration(
    version=19,
    name="learning-mode",
    statements=(
        # v8 reserved learning_goals/learning_lessons. M30 makes them real: a goal is a
        # promise with criteria, and a lesson is a *reviewable item* with its own schedule.
        "ALTER TABLE learning_goals ADD COLUMN topic TEXT",
        "ALTER TABLE learning_goals ADD COLUMN success_criteria TEXT",
        "ALTER TABLE learning_goals ADD COLUMN priority INTEGER NOT NULL DEFAULT 5",
        "ALTER TABLE learning_goals ADD COLUMN target_date TEXT",
        "ALTER TABLE learning_goals ADD COLUMN task_id TEXT",
        "ALTER TABLE learning_goals ADD COLUMN settings TEXT",
        "ALTER TABLE learning_goals ADD COLUMN completed_at TEXT",
        "ALTER TABLE learning_goals ADD COLUMN planned_by TEXT",
        "ALTER TABLE learning_goals ADD COLUMN source TEXT",
        # An item that cannot be scheduled cannot be reviewed. The interval, the ease and
        # the due date are stored, not recomputed from vibes at read time.
        "ALTER TABLE learning_lessons ADD COLUMN expected TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN hints TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN explanation TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN ease REAL NOT NULL DEFAULT 2.5",
        "ALTER TABLE learning_lessons ADD COLUMN interval_days REAL NOT NULL DEFAULT 0",
        "ALTER TABLE learning_lessons ADD COLUMN streak INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE learning_lessons ADD COLUMN lapses INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE learning_lessons ADD COLUMN correct_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE learning_lessons ADD COLUMN due_at TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN last_reviewed_at TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN created_at TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN source TEXT",
        "CREATE TABLE IF NOT EXISTS learning_sessions ("
        " id TEXT PRIMARY KEY,"
        " goal_id TEXT NOT NULL,"
        " task_id TEXT,"
        " mode TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " started_at TEXT NOT NULL,"
        " ended_at TEXT,"
        " items_attempted INTEGER NOT NULL DEFAULT 0,"
        " items_correct INTEGER NOT NULL DEFAULT 0,"
        " hints_used INTEGER NOT NULL DEFAULT 0,"
        " graded_by TEXT,"
        " summary TEXT,"
        " created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS learning_attempts ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " session_id TEXT,"
        " goal_id TEXT NOT NULL,"
        " item_id TEXT NOT NULL,"
        " answer TEXT,"
        " correct INTEGER NOT NULL DEFAULT 0,"
        " graded_by TEXT NOT NULL,"
        " self_rating INTEGER,"
        " hints_used INTEGER NOT NULL DEFAULT 0,"
        " feedback TEXT,"
        " interval_days REAL,"
        " due_at TEXT,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_learning_items_goal ON learning_lessons(goal_id, position)",
        "CREATE INDEX IF NOT EXISTS idx_learning_items_due ON learning_lessons(goal_id, due_at)",
        "CREATE INDEX IF NOT EXISTS idx_learning_sessions_goal ON learning_sessions(goal_id, started_at)",
        "CREATE INDEX IF NOT EXISTS idx_learning_attempts_item ON learning_attempts(item_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_learning_attempts_session ON learning_attempts(session_id, id)",
    ),
)
