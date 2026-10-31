"""Released migration 25: datasets. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


DATASETS_V25 = Migration(
    version=25,
    name="datasets",
    statements=(
        # `datasets` and `dataset_transforms` were reserved for this milestone in v8, so they are
        # adopted with ALTER rather than redefined: a home that already has rows keeps them, where
        # CREATE TABLE IF NOT EXISTS would silently leave the old shape in place (D157/D160).
        "ALTER TABLE datasets ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'",
        "ALTER TABLE datasets ADD COLUMN seed TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE datasets ADD COLUMN splits TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE datasets ADD COLUMN dropped_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE datasets ADD COLUMN updated_at TEXT",
        # The manifest is the dataset's claim about itself; `checksum` (reserved in v8) holds the
        # hash over its sorted lines, so `dataset verify` can recompute and disagree.
        "ALTER TABLE dataset_transforms ADD COLUMN input_checksum TEXT",
        "ALTER TABLE dataset_transforms ADD COLUMN output_checksum TEXT",
        # One row per candidate, kept *or* dropped. A record that a cleaning rule removed keeps its
        # reason: a pipeline that deletes quietly cannot be audited, and "why is this file not in
        # my dataset" is the first question anyone asks.
        "CREATE TABLE IF NOT EXISTS dataset_records ("
        " id TEXT PRIMARY KEY,"
        " dataset_id TEXT NOT NULL,"
        " seq INTEGER NOT NULL,"
        " path TEXT NOT NULL,"
        " sha256 TEXT NOT NULL,"
        " bytes INTEGER NOT NULL,"
        " kind TEXT NOT NULL,"
        " chars INTEGER,"
        " lines INTEGER,"
        " split TEXT,"
        " status TEXT NOT NULL,"
        " reason TEXT,"
        " label TEXT,"
        " created_at TEXT NOT NULL,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        "CREATE INDEX IF NOT EXISTS idx_dataset_records_dataset"
        " ON dataset_records(dataset_id, status, seq)",
        "CREATE INDEX IF NOT EXISTS idx_dataset_records_sha ON dataset_records(dataset_id, sha256)",
        "CREATE INDEX IF NOT EXISTS idx_dataset_transforms_dataset"
        " ON dataset_transforms(dataset_id, seq)",
    ),
)
