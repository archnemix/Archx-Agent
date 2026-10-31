"""Released migration 14: mcp_extensions. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


MCP_V14 = Migration(
    version=14,
    name="mcp-extensions",
    statements=(
        # v6 already has mcp_servers/mcp_tools/extensions; these columns extend the same
        # records so there is one answer to "what is this server and may it run?".
        "ALTER TABLE mcp_servers ADD COLUMN headers TEXT",
        "ALTER TABLE mcp_servers ADD COLUMN protocol_version TEXT",
        "ALTER TABLE mcp_servers ADD COLUMN last_status TEXT",
        "ALTER TABLE mcp_servers ADD COLUMN tools_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE mcp_servers ADD COLUMN last_error_at TEXT",
        "ALTER TABLE mcp_tools ADD COLUMN capability TEXT",
        "ALTER TABLE mcp_tools ADD COLUMN risk TEXT",
        "ALTER TABLE mcp_tools ADD COLUMN annotations TEXT",
        "ALTER TABLE mcp_tools ADD COLUMN last_synced_at TEXT",
        "CREATE INDEX IF NOT EXISTS idx_mcp_tools_name ON mcp_tools(name)",
        "ALTER TABLE extensions ADD COLUMN manifest_hash TEXT",
        "ALTER TABLE extensions ADD COLUMN trusted_by TEXT",
        "ALTER TABLE extensions ADD COLUMN trusted_at TEXT",
        "ALTER TABLE extensions ADD COLUMN notes TEXT",
        "CREATE TABLE IF NOT EXISTS extension_tools ("
        " id TEXT PRIMARY KEY,"
        " extension_id TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " description TEXT,"
        " capability TEXT,"
        " risk TEXT,"
        " schema TEXT,"
        " entry TEXT NOT NULL,"
        " enabled INTEGER NOT NULL DEFAULT 0,"
        " discovered_at TEXT NOT NULL,"
        " UNIQUE(extension_id, name))",
        "CREATE INDEX IF NOT EXISTS idx_extension_tools_name ON extension_tools(name)",
    ),
)
