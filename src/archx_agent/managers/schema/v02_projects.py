"""Released migration 2: projects. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


PROJECTS_V2 = Migration(
    version=2,
    name="projects",
    statements=(
        "CREATE TABLE IF NOT EXISTS projects ("
        " id TEXT PRIMARY KEY,"
        " slug TEXT NOT NULL UNIQUE,"
        " name TEXT NOT NULL,"
        " root_path TEXT,"
        " description TEXT,"
        " status TEXT NOT NULL DEFAULT 'active',"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " metadata TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)",
    ),
)
