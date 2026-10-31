"""Released migration 15: task_history. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


TASKS_V15 = Migration(
    version=15,
    name="task-history",
    statements=(
        # v5 created tasks/artifacts/version_records/reproduction_records. This block
        # adds the ordering and provenance those records need; it does not create a
        # second history. A task timeline is an explicit sequence, so it cannot
        # reorder itself when two steps happen inside the same millisecond.
        "CREATE TABLE IF NOT EXISTS task_log ("
        " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
        " task_id TEXT NOT NULL,"
        " at TEXT NOT NULL,"
        " kind TEXT NOT NULL,"
        " detail TEXT,"
        " event_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_task_log_task ON task_log(task_id, seq)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at)",
        "ALTER TABLE version_records ADD COLUMN ordinal INTEGER",
        "ALTER TABLE version_records ADD COLUMN size INTEGER",
        "ALTER TABLE version_records ADD COLUMN restored_from TEXT",
        "ALTER TABLE version_records ADD COLUMN subject_key TEXT",
        "ALTER TABLE version_records ADD COLUMN content_stored INTEGER NOT NULL DEFAULT 1",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_version_records_ordinal"
        " ON version_records(subject_type, subject_id, ordinal)",
        "CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_repro_task ON reproduction_records(task_id, created_at)",
        "ALTER TABLE reproduction_records ADD COLUMN app_version TEXT",
        "ALTER TABLE reproduction_records ADD COLUMN recorded_by TEXT",
    ),
)
