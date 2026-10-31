"""Released migration 22: experiments. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


EXPERIMENTS_V22 = Migration(
    version=22,
    name="experiments",
    statements=(
        # An experiment is a question, a command and a declared way of reading the answer out of
        # it. The declaration is not decoration: it is what stops the tool inventing a metric.
        # The name is `experiment_specs`, not `experiments`: the v13 schema already has an
        # `experiments` table (a manual log with baseline/target/criteria that nothing reads), and
        # redefining a table someone might have rows in is not a migration, it is a surprise.
        "CREATE TABLE IF NOT EXISTS experiment_specs ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " hypothesis TEXT,"
        " command TEXT NOT NULL,"
        " root TEXT NOT NULL,"
        " params TEXT NOT NULL DEFAULT '[]',"
        " metrics_source TEXT NOT NULL DEFAULT '{}',"
        " status TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        # One row per execution: the parameters it actually ran with (after substitution), the
        # command it resolved to, and what came back. A failed run is a run, not an absence.
        "CREATE TABLE IF NOT EXISTS experiment_runs ("
        " id TEXT PRIMARY KEY,"
        " experiment_id TEXT NOT NULL,"
        " params TEXT NOT NULL DEFAULT '{}',"
        " command TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " exit_code INTEGER,"
        " duration_ms REAL,"
        " timeout_seconds INTEGER,"
        " metrics TEXT NOT NULL DEFAULT '{}',"
        " metrics_error TEXT,"
        " task_id TEXT,"
        " tool_run_id TEXT,"
        " artifact_id TEXT,"
        " seed TEXT,"
        " note TEXT,"
        " created_at TEXT NOT NULL)",
        # Metrics are rows so a comparison is a query, not a re-parse of every run's JSON.
        "CREATE TABLE IF NOT EXISTS experiment_metrics ("
        " run_id TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " value REAL,"
        " raw TEXT,"
        " PRIMARY KEY (run_id, name))",
        "CREATE INDEX IF NOT EXISTS idx_experiment_runs_experiment"
        " ON experiment_runs(experiment_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_experiment_metrics_name"
        " ON experiment_metrics(name, value)",
    ),
)
