"""Released migration 5: tasks_history. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


TASKS_V5 = Migration(
    version=5,
    name="tasks-history",
    statements=(
        "CREATE TABLE IF NOT EXISTS tasks ("
        " id TEXT PRIMARY KEY,"
        " type TEXT NOT NULL,"
        " title TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " conversation_id TEXT,"
        " project_id TEXT,"
        " parent_task_id TEXT,"
        " run_id TEXT,"
        " created_at TEXT NOT NULL,"
        " started_at TEXT,"
        " completed_at TEXT,"
        " model_id TEXT,"
        " agents TEXT,"
        " tools TEXT,"
        " resource_use TEXT,"
        " cost_estimate REAL,"
        " input_refs TEXT,"
        " output_refs TEXT,"
        " error TEXT,"
        " unresolved TEXT,"
        " trace_event_id TEXT,"
        " version_info TEXT,"
        " metadata TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_conversation ON tasks(conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)",
        "CREATE TABLE IF NOT EXISTS artifacts ("
        " id TEXT PRIMARY KEY,"
        " task_id TEXT,"
        " project_id TEXT,"
        " kind TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " path TEXT NOT NULL,"
        " rel_path TEXT,"
        " checksum TEXT,"
        " size INTEGER,"
        " mime TEXT,"
        " created_at TEXT NOT NULL,"
        " metadata TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id)",
        "CREATE TABLE IF NOT EXISTS version_records ("
        " id TEXT PRIMARY KEY,"
        " subject_type TEXT NOT NULL,"
        " subject_id TEXT NOT NULL,"
        " version TEXT NOT NULL,"
        " content TEXT NOT NULL,"
        " checksum TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " created_by TEXT,"
        " note TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_version_records_subject ON version_records(subject_type, subject_id)",
        "CREATE TABLE IF NOT EXISTS reproduction_records ("
        " id TEXT PRIMARY KEY,"
        " task_id TEXT NOT NULL,"
        " fidelity TEXT NOT NULL,"
        " blockers TEXT,"
        " environment TEXT,"
        " commands TEXT,"
        " created_at TEXT NOT NULL)",
    ),
)
