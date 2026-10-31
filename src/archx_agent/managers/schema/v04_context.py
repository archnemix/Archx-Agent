"""Released migration 4: context. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


CONTEXT_V4 = Migration(
    version=4,
    name="context",
    statements=(
        "CREATE TABLE IF NOT EXISTS context_manifests ("
        " id TEXT PRIMARY KEY,"
        " conversation_id TEXT NOT NULL,"
        " message_id TEXT,"
        " strategy TEXT NOT NULL,"
        " token_budget INTEGER NOT NULL,"
        " tokens_used INTEGER NOT NULL,"
        " omitted TEXT NOT NULL DEFAULT '[]',"
        " included TEXT NOT NULL DEFAULT '[]',"
        " notes TEXT,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_context_manifests_conversation ON context_manifests(conversation_id)",
        "CREATE TABLE IF NOT EXISTS summaries ("
        " id TEXT PRIMARY KEY,"
        " conversation_id TEXT NOT NULL,"
        " source_start_seq INTEGER NOT NULL,"
        " source_end_seq INTEGER NOT NULL,"
        " content TEXT NOT NULL,"
        " token_estimate INTEGER NOT NULL,"
        " generator TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " superseded_by TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_summaries_conversation ON summaries(conversation_id, source_start_seq)",
    ),
)
