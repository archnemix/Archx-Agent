"""Released migration 3: memory. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


MEMORY_V3 = Migration(
    version=3,
    name="memory",
    statements=(
        "CREATE TABLE IF NOT EXISTS memories ("
        " id TEXT PRIMARY KEY,"
        " kind TEXT NOT NULL,"
        " scope TEXT NOT NULL,"
        " scope_id TEXT,"
        " slot TEXT,"
        " title TEXT NOT NULL,"
        " content TEXT NOT NULL,"
        " summary TEXT,"
        " category TEXT NOT NULL,"
        " project_id TEXT,"
        " conversation_id TEXT,"
        " task_id TEXT,"
        " source TEXT NOT NULL,"
        " provenance TEXT NOT NULL,"
        " confidence REAL NOT NULL DEFAULT 0.8,"
        " status TEXT NOT NULL DEFAULT 'active',"
        " pinned INTEGER NOT NULL DEFAULT 0,"
        " tags TEXT,"
        " details TEXT,"
        " evidence TEXT,"
        " verification TEXT,"
        " environment TEXT,"
        " limitations TEXT,"
        " worked INTEGER,"
        " expires_at TEXT,"
        " last_accessed_at TEXT,"
        " access_count INTEGER NOT NULL DEFAULT 0,"
        " duplicate_of TEXT,"
        " supersedes TEXT,"
        " version INTEGER NOT NULL DEFAULT 1,"
        " embedding_state TEXT NOT NULL DEFAULT 'awaiting',"
        " embedding_ref TEXT,"
        " artifact_path TEXT,"
        " checksum TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " deleted_at TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_memories_kind_scope ON memories(kind, scope, scope_id)",
        "CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)",
        "CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)",
        "CREATE TABLE IF NOT EXISTS memory_history ("
        " hid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " memory_id TEXT NOT NULL,"
        " version INTEGER NOT NULL,"
        " change TEXT NOT NULL,"
        " snapshot TEXT NOT NULL,"
        " changed_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_memory_history_memory ON memory_history(memory_id, version)",
        "CREATE TABLE IF NOT EXISTS memory_sources ("
        " sid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " memory_id TEXT NOT NULL,"
        " source_type TEXT NOT NULL,"
        " reference TEXT,"
        " excerpt TEXT,"
        " retrieved_at TEXT NOT NULL,"
        " checksum TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_memory_sources_memory ON memory_sources(memory_id)",
        "CREATE TABLE IF NOT EXISTS memory_retrievals ("
        " rid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " memory_id TEXT NOT NULL,"
        " used_at TEXT NOT NULL,"
        " reason TEXT,"
        " budget_tokens INTEGER,"
        " consumed_tokens INTEGER,"
        " conversation_id TEXT,"
        " task_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_memory_retrievals_memory ON memory_retrievals(memory_id)",
        "CREATE TABLE IF NOT EXISTS learning_events ("
        " id TEXT PRIMARY KEY,"
        " goal_id TEXT,"
        " topic TEXT NOT NULL,"
        " outcome TEXT NOT NULL,"
        " attempts INTEGER NOT NULL DEFAULT 1,"
        " mistakes TEXT,"
        " duration_seconds INTEGER,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_learning_events_topic ON learning_events(topic)",
    ),
)
