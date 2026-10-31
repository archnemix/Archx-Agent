"""Released migration 7: scheduler. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


JOBS_V7 = Migration(
    version=7,
    name="scheduler",
    statements=(
        "CREATE TABLE IF NOT EXISTS jobs ("
        " id TEXT PRIMARY KEY,"
        " kind TEXT NOT NULL,"
        " title TEXT NOT NULL,"
        " payload TEXT,"
        " status TEXT NOT NULL,"
        " priority INTEGER NOT NULL DEFAULT 5,"
        " queue_seq INTEGER NOT NULL,"
        " created_at TEXT NOT NULL,"
        " started_at TEXT,"
        " ended_at TEXT,"
        " deadline TEXT,"
        " progress REAL NOT NULL DEFAULT 0,"
        " message TEXT,"
        " error TEXT,"
        " resource_estimate TEXT,"
        " resource_observed TEXT,"
        " result TEXT,"
        " task_id TEXT,"
        " project_id TEXT,"
        " cancelled INTEGER NOT NULL DEFAULT 0)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, queue_seq)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_kind ON jobs(kind)",
    ),
)
