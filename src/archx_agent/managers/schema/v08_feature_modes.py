"""Released migration 8: feature_modes. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


FEATURES_V8 = Migration(
    version=8,
    name="feature-modes",
    statements=(
        "CREATE TABLE IF NOT EXISTS research_runs ("
        " id TEXT PRIMARY KEY, status TEXT NOT NULL, question TEXT NOT NULL,"
        " subquestions TEXT, report_path TEXT, report_format TEXT,"
        " created_at TEXT NOT NULL, completed_at TEXT, limitations TEXT, task_id TEXT)",
        "CREATE TABLE IF NOT EXISTS research_sources ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, url TEXT NOT NULL,"
        " title TEXT, publisher TEXT, retrieved_at TEXT NOT NULL, excerpt TEXT,"
        " subsection TEXT, limitations TEXT, stance TEXT)",
        "CREATE TABLE IF NOT EXISTS learning_goals ("
        " id TEXT PRIMARY KEY, title TEXT NOT NULL, objective TEXT NOT NULL, level TEXT,"
        " status TEXT NOT NULL, path TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS learning_lessons ("
        " id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, topic TEXT NOT NULL, subtopic TEXT,"
        " position INTEGER NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,"
        " best_score REAL, content TEXT, exercise TEXT, updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS experiments ("
        " id TEXT PRIMARY KEY, title TEXT NOT NULL, hypothesis TEXT, baseline TEXT,"
        " target TEXT, criteria TEXT, status TEXT NOT NULL, deadline TEXT,"
        " config TEXT, created_at TEXT NOT NULL, completed_at TEXT, report_path TEXT, task_id TEXT)",
        "CREATE TABLE IF NOT EXISTS experiment_steps ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT NOT NULL, kind TEXT NOT NULL,"
        " description TEXT, changes TEXT, measurement TEXT, result TEXT, created_at TEXT NOT NULL, seq INTEGER)",
        "CREATE TABLE IF NOT EXISTS games ("
        " id TEXT PRIMARY KEY, game_type TEXT NOT NULL, status TEXT NOT NULL,"
        " state TEXT NOT NULL, config TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, winner TEXT)",
        "CREATE TABLE IF NOT EXISTS game_moves ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL, seq INTEGER NOT NULL,"
        " player TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL, legal INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS media_jobs ("
        " id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, prompt TEXT,"
        " model_id TEXT, output_path TEXT, metadata TEXT, created_at TEXT NOT NULL, completed_at TEXT, error TEXT, task_id TEXT)",
        "CREATE TABLE IF NOT EXISTS datasets ("
        " id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL, revision TEXT,"
        " license TEXT, format TEXT, record_count INTEGER, path TEXT, checksum TEXT,"
        " created_at TEXT NOT NULL, task_id TEXT, metadata TEXT)",
        "CREATE TABLE IF NOT EXISTS dataset_transforms ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, dataset_id TEXT NOT NULL, seq INTEGER NOT NULL,"
        " kind TEXT NOT NULL, config TEXT NOT NULL, records_in INTEGER, records_out INTEGER,"
        " created_at TEXT NOT NULL, output_path TEXT, report TEXT)",
        "CREATE TABLE IF NOT EXISTS training_jobs ("
        " id TEXT PRIMARY KEY, method TEXT NOT NULL, base_model TEXT, dataset_id TEXT,"
        " status TEXT NOT NULL, config TEXT, preflight TEXT, metrics TEXT, checkpoints TEXT,"
        " created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, error TEXT, task_id TEXT)",
        "CREATE TABLE IF NOT EXISTS remote_jobs ("
        " id TEXT PRIMARY KEY, provider TEXT NOT NULL, status TEXT NOT NULL, config TEXT,"
        " estimate TEXT, actual TEXT, outputs TEXT, created_at TEXT NOT NULL,"
        " completed_at TEXT, error TEXT, approved_by TEXT, task_id TEXT)",
        "CREATE TABLE IF NOT EXISTS automations ("
        " id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, schedule TEXT NOT NULL,"
        " enabled INTEGER NOT NULL DEFAULT 1, config TEXT, permissions TEXT,"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_run_at TEXT,"
        " next_run_at TEXT, last_status TEXT, retry_policy TEXT)",
        "CREATE TABLE IF NOT EXISTS automation_runs ("
        " id TEXT PRIMARY KEY, automation_id TEXT NOT NULL, status TEXT NOT NULL,"
        " started_at TEXT NOT NULL, ended_at TEXT, output TEXT, error TEXT, task_id TEXT)",
    ),
)
