"""Released migration 21: coding_workspace. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


CODING_V21 = Migration(
    version=21,
    name="coding-workspace",
    statements=(
        # A coding session is a directory, a task and a decision: the directory is what the file
        # and shell tools may touch, the task is the record of what happened in it, and the
        # decision is the user's, taken once rather than per keystroke.
        "CREATE TABLE IF NOT EXISTS code_sessions ("
        " id TEXT PRIMARY KEY,"
        " title TEXT NOT NULL,"
        " root TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " task_id TEXT,"
        " project_id TEXT,"
        " note TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " closed_at TEXT,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        # Every edit is a row with its own unified diff, before and after checksums. The file on
        # disk is the truth; this is the account of how it got there, and it is what makes an
        # edit reviewable after the fact.
        "CREATE TABLE IF NOT EXISTS code_changes ("
        " id TEXT PRIMARY KEY,"
        " session_id TEXT NOT NULL,"
        " path TEXT NOT NULL,"
        " action TEXT NOT NULL,"
        " before_sha TEXT,"
        " after_sha TEXT,"
        " added INTEGER NOT NULL DEFAULT 0,"
        " removed INTEGER NOT NULL DEFAULT 0,"
        " diff TEXT NOT NULL,"
        " artifact_id TEXT,"
        " tool_run_id TEXT,"
        " note TEXT,"
        " created_at TEXT NOT NULL)",
        # The runner's ledger: the command that was asked for, the argv that actually ran, where,
        # how long, what came back. A refusal is a row too - it is the evidence that the
        # permission centre was consulted, and by which tool.
        "CREATE TABLE IF NOT EXISTS code_runs ("
        " id TEXT PRIMARY KEY,"
        " session_id TEXT NOT NULL,"
        " check_name TEXT,"
        " command TEXT NOT NULL,"
        " argv TEXT,"
        " cwd TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " exit_code INTEGER,"
        " duration_ms REAL,"
        " timeout_seconds INTEGER,"
        " timed_out INTEGER NOT NULL DEFAULT 0,"
        " stdout TEXT,"
        " stderr TEXT,"
        " artifact_id TEXT,"
        " tool_run_id TEXT,"
        " replayed_from TEXT,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_code_changes_session ON code_changes(session_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_code_runs_session ON code_runs(session_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_code_sessions_status ON code_sessions(status, created_at)",
    ),
)
