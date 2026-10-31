"""Released migration 13: tool_permissions. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


PERMISSIONS_V13 = Migration(
    version=13,
    name="tool-permissions",
    statements=(
        # v6 created permission_grants/tool_runs. Extending the same tables keeps one
        # source of truth for authority: a second grant table would be a second answer
        # to "is this allowed?".
        "ALTER TABLE permission_grants ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE permission_grants ADD COLUMN last_used_at TEXT",
        "ALTER TABLE permission_grants ADD COLUMN approval_id TEXT",
        "ALTER TABLE permission_grants ADD COLUMN notes TEXT",
        "CREATE INDEX IF NOT EXISTS idx_perm_grant_lookup"
        " ON permission_grants(capability, subject, revoked_at)",
        "ALTER TABLE tool_runs ADD COLUMN approval_id TEXT",
        "ALTER TABLE tool_runs ADD COLUMN dry_run INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tool_runs ADD COLUMN truncated INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tool_runs ADD COLUMN seq INTEGER",
        "CREATE INDEX IF NOT EXISTS idx_tool_runs_seq ON tool_runs(seq)",
        # An approval is a *request* for one capability on one subject in one scope.
        # Approving it can only mint exactly that grant: there is no field a caller
        # could use to widen it.
        "CREATE TABLE IF NOT EXISTS approval_requests ("
        " id TEXT PRIMARY KEY,"
        " capability TEXT NOT NULL,"
        " subject TEXT NOT NULL,"
        " scope TEXT NOT NULL,"
        " conversation_id TEXT,"
        " task_id TEXT,"
        " project_id TEXT,"
        " requested_by TEXT NOT NULL,"
        " purpose TEXT,"
        " payload TEXT,"
        " status TEXT NOT NULL,"  # pending | approved | denied | expired
        " created_at TEXT NOT NULL,"
        " expires_at TEXT,"
        " decided_at TEXT,"
        " decided_by TEXT,"
        " decision_reason TEXT,"
        " grant_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_approval_lookup"
        " ON approval_requests(capability, subject, status)",
    ),
)
