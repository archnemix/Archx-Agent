"""Released migration 28: execution. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


EXECUTION_V28 = Migration(
    version=28,
    name="execution",
    statements=(
        # Where a command may run. A target is a *recorded* choice, not an inference: the row says
        # which backend, which machine, and - when it cannot be used - why.
        "CREATE TABLE IF NOT EXISTS execution_targets ("
        " id TEXT PRIMARY KEY,"
        " kind TEXT NOT NULL,"
        " name TEXT NOT NULL UNIQUE,"
        " endpoint TEXT,"
        " spec TEXT NOT NULL DEFAULT '{}',"
        " status TEXT NOT NULL DEFAULT 'unknown',"
        " refusal TEXT,"
        " created_at TEXT NOT NULL,"
        " last_probe_at TEXT)",
        # One row per command, wherever it ran. stdout and stderr are stored both as text (for the
        # ledger to be readable) and as artifacts written through fs.write (so they can be kept).
        "CREATE TABLE IF NOT EXISTS execution_runs ("
        " id TEXT PRIMARY KEY,"
        " target_id TEXT,"
        " kind TEXT NOT NULL,"
        " command TEXT NOT NULL,"
        " invocation TEXT,"
        " cwd TEXT,"
        " status TEXT NOT NULL,"
        " exit_code INTEGER,"
        " duration_ms REAL,"
        " stdout TEXT,"
        " stderr TEXT,"
        " stdout_path TEXT,"
        " stderr_path TEXT,"
        " truncated INTEGER NOT NULL DEFAULT 0,"
        " detached INTEGER NOT NULL DEFAULT 0,"
        " note TEXT,"
        " remote_job_id TEXT,"
        " task_id TEXT,"
        " started_at TEXT NOT NULL,"
        " ended_at TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_execution_runs_target ON execution_runs(target_id)",
        # The file ledger: what went out and what came back, with both hashes, so a pull can refuse
        # to overwrite an edit that happened here while the work was happening there.
        "CREATE TABLE IF NOT EXISTS execution_files ("
        " id TEXT PRIMARY KEY,"
        " run_id TEXT,"
        " target_id TEXT,"
        " path TEXT NOT NULL,"
        " direction TEXT NOT NULL,"
        " sha256_local TEXT,"
        " sha256_remote TEXT,"
        " bytes INTEGER,"
        " status TEXT NOT NULL,"
        " note TEXT,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_execution_files_target ON execution_files(target_id)",
        # A training run can now name the machine it ran on: the user's own CPU, or a worker.
        "ALTER TABLE training_jobs ADD COLUMN target TEXT NOT NULL DEFAULT 'local'",
        "ALTER TABLE training_jobs ADD COLUMN remote_job_id TEXT",
    ),
)
