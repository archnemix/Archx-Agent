"""Released migration 6: tools_permissions. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


TOOLS_V6 = Migration(
    version=6,
    name="tools-permissions",
    statements=(
        "CREATE TABLE IF NOT EXISTS permission_grants ("
        " id TEXT PRIMARY KEY,"
        " scope TEXT NOT NULL,"
        " capability TEXT NOT NULL,"
        " subject TEXT NOT NULL,"
        " constraints TEXT,"
        " duration TEXT NOT NULL,"
        " granted_by TEXT NOT NULL,"
        " reason TEXT,"
        " created_at TEXT NOT NULL,"
        " expires_at TEXT,"
        " revoked_at TEXT,"
        " revoked_by TEXT,"
        " conversation_id TEXT,"
        " task_id TEXT,"
        " project_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_perm_lookup ON permission_grants(capability, subject)",
        "CREATE INDEX IF NOT EXISTS idx_perm_scope ON permission_grants(scope, scope)",
        "CREATE TABLE IF NOT EXISTS tool_runs ("
        " id TEXT PRIMARY KEY,"
        " task_id TEXT,"
        " tool_name TEXT NOT NULL,"
        " arguments TEXT,"
        " status TEXT NOT NULL,"
        " result TEXT,"
        " started_at TEXT NOT NULL,"
        " ended_at TEXT,"
        " duration_ms REAL,"
        " error TEXT,"
        " permission_id TEXT,"
        " trace_event_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_tool_runs_tool ON tool_runs(tool_name, started_at)",
        "CREATE TABLE IF NOT EXISTS mcp_servers ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL UNIQUE,"
        " transport TEXT NOT NULL,"
        " command TEXT,"
        " args TEXT,"
        " url TEXT,"
        " env TEXT,"
        " enabled INTEGER NOT NULL DEFAULT 0,"
        " trusted INTEGER NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " last_connected_at TEXT,"
        " last_error TEXT)",
        "CREATE TABLE IF NOT EXISTS mcp_tools ("
        " server_id TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " description TEXT,"
        " schema TEXT,"
        " enabled INTEGER NOT NULL DEFAULT 0,"
        " discovered_at TEXT NOT NULL,"
        " PRIMARY KEY(server_id, name))",
        "CREATE TABLE IF NOT EXISTS extensions ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL UNIQUE,"
        " version TEXT NOT NULL,"
        " path TEXT,"
        " manifest TEXT NOT NULL,"
        " trust TEXT NOT NULL DEFAULT 'untrusted',"
        " enabled INTEGER NOT NULL DEFAULT 0,"
        " installed_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " last_error TEXT)",
    ),
)
