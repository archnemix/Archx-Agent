"""Released migration 11: context_proposals. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


CONTEXT_PROPOSALS_V11 = Migration(
    version=11,
    name="context-proposals",
    statements=(
        "CREATE TABLE IF NOT EXISTS context_proposals ("
        " id TEXT PRIMARY KEY,"
        " conversation_id TEXT NOT NULL,"
        " strategy TEXT NOT NULL,"
        " payload TEXT NOT NULL,"
        " rationale TEXT,"
        " estimated_tokens INTEGER,"
        " created_at TEXT NOT NULL,"
        " approved_at TEXT,"
        " applied_manifest_id TEXT,"
        " rejected_at TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_context_proposals_conversation ON context_proposals(conversation_id)",
    ),
)
