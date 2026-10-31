"""Released migration 26: training. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


TRAINING_V26 = Migration(
    version=26,
    name="training",
    statements=(
        # `training_jobs` was reserved in v8, so it is adopted with ALTER: the columns a home may
        # already have (method, base_model, dataset_id, status, metrics, checkpoints) keep their
        # meaning, and this milestone adds what a run needs to be checkable.
        "ALTER TABLE training_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'ngram'",
        "ALTER TABLE training_jobs ADD COLUMN seed INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE training_jobs ADD COLUMN artifact_path TEXT",
        "ALTER TABLE training_jobs ADD COLUMN artifact_sha256 TEXT",
        "ALTER TABLE training_jobs ADD COLUMN refusal TEXT",
        "ALTER TABLE training_jobs ADD COLUMN version_id TEXT",
        "ALTER TABLE training_jobs ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
        # Metrics are rows, not a JSON blob, so a comparison is a query and a missing number is
        # visible as a missing row rather than as a key nobody remembered to write.
        "CREATE TABLE IF NOT EXISTS training_metrics ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " job_id TEXT NOT NULL,"
        " split TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " value REAL,"
        " raw TEXT,"
        " step INTEGER,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_training_metrics_job ON training_metrics(job_id, split)",
        "CREATE INDEX IF NOT EXISTS idx_training_jobs_dataset ON training_jobs(dataset_id)",
    ),
)
