"""Released migration 9: retrieval. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


RETRIEVAL_V9 = Migration(
    version=9,
    name="retrieval",
    statements=(
        "CREATE TABLE IF NOT EXISTS embeddings ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " owner_type TEXT NOT NULL,"
        " owner_id TEXT NOT NULL,"
        " model_id TEXT NOT NULL,"
        " dim INTEGER NOT NULL,"
        " vector BLOB NOT NULL,"
        " checksum TEXT NOT NULL,"
        " state TEXT NOT NULL DEFAULT 'embedded',"
        " created_at TEXT NOT NULL,"
        " UNIQUE(owner_type, owner_id, model_id))",
        "CREATE INDEX IF NOT EXISTS idx_embeddings_owner ON embeddings(owner_type, owner_id)",
        "CREATE TABLE IF NOT EXISTS retrieval_runs ("
        " id TEXT PRIMARY KEY,"
        " query TEXT NOT NULL,"
        " mode TEXT NOT NULL,"
        " model_id TEXT,"
        " results INTEGER NOT NULL,"
        " degraded INTEGER NOT NULL DEFAULT 0,"
        " notes TEXT,"
        " created_at TEXT NOT NULL)",
    ),
)
