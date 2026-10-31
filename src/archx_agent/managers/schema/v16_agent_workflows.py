"""Released migration 16: agent_workflows. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


WORKFLOWS_V16 = Migration(
    version=16,
    name="agent-workflows",
    statements=(
        # A workflow is a *definition* (data) plus ordered step records. It cannot grant
        # anything: every step that touches the machine goes through the tool registry and
        # therefore through the permission centre.
        "CREATE TABLE IF NOT EXISTS workflows ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " mode TEXT NOT NULL,"  # user | ai
        " status TEXT NOT NULL,"  # proposed | approved | running | completed | failed | cancelled
        " goal TEXT,"
        " definition TEXT NOT NULL,"
        " model_id TEXT,"
        " task_id TEXT,"
        " conversation_id TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " started_at TEXT,"
        " finished_at TEXT,"
        " error TEXT,"
        " metadata TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status, created_at)",
        "CREATE TABLE IF NOT EXISTS workflow_steps ("
        " id TEXT PRIMARY KEY,"
        " workflow_id TEXT NOT NULL,"
        " seq INTEGER NOT NULL,"
        " kind TEXT NOT NULL,"
        " title TEXT,"
        " spec TEXT,"
        " status TEXT NOT NULL,"
        " started_at TEXT,"
        " ended_at TEXT,"
        " output TEXT,"
        " error TEXT,"
        " task_id TEXT,"
        " tokens INTEGER NOT NULL DEFAULT 0,"
        " metadata TEXT,"
        " UNIQUE(workflow_id, seq))",
        "CREATE INDEX IF NOT EXISTS idx_workflow_steps ON workflow_steps(workflow_id, seq)",
    ),
)
