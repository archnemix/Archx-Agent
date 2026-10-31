"""Released migration 17: scheduler_claims. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


JOBS_V17 = Migration(
    version=17,
    name="scheduler-claims",
    statements=(
        # v7 created jobs. These columns are what a *worker* needs: who claimed the job,
        # which process is running it, how many attempts remain, and the queue index.
        "ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN timeout_seconds INTEGER",
        "ALTER TABLE jobs ADD COLUMN pid INTEGER",
        "ALTER TABLE jobs ADD COLUMN worker TEXT",
        "ALTER TABLE jobs ADD COLUMN requeued_at TEXT",
        "ALTER TABLE jobs ADD COLUMN control TEXT",
        "ALTER TABLE jobs ADD COLUMN cursor INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN dedupe_key TEXT",
        "CREATE INDEX IF NOT EXISTS idx_jobs_dedupe ON jobs(dedupe_key, status)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_queue"
        " ON jobs(status, priority DESC, queue_seq)",
    ),
)
