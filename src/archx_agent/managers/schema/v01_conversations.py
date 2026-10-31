"""Released migration 1: conversations. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


CONVERSATIONS_V1 = Migration(
    version=1,
    name="conversations",
    statements=(
        "CREATE TABLE IF NOT EXISTS conversations ("
        " id TEXT PRIMARY KEY,"
        " title TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " last_seq INTEGER NOT NULL DEFAULT 0,"
        " project_id TEXT,"
        " model_id TEXT,"
        " context_strategy TEXT,"
        " archived INTEGER NOT NULL DEFAULT 0,"
        " deleted_at TEXT,"
        " pinned INTEGER NOT NULL DEFAULT 0,"
        " metadata TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id)",
        "CREATE TABLE IF NOT EXISTS messages ("
        " id TEXT PRIMARY KEY,"
        " conversation_id TEXT NOT NULL,"
        " seq INTEGER NOT NULL,"
        " role TEXT NOT NULL,"
        " content TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " token_estimate INTEGER NOT NULL DEFAULT 0,"
        " pinned INTEGER NOT NULL DEFAULT 0,"
        " excluded INTEGER NOT NULL DEFAULT 0,"
        " tool_calls TEXT,"
        " tool_results TEXT,"
        " metadata TEXT,"
        " UNIQUE(conversation_id, seq))",
        "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, seq)",
        "CREATE TABLE IF NOT EXISTS conversation_settings ("
        " conversation_id TEXT PRIMARY KEY,"
        " key TEXT NOT NULL,"
        " value TEXT NOT NULL)",
    ),
)
