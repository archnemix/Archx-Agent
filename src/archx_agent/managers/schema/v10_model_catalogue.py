"""Released migration 10: model_catalogue. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


MODELS_V10 = Migration(
    version=10,
    name="model-catalogue",
    statements=(
        "CREATE TABLE IF NOT EXISTS models ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " provider TEXT NOT NULL,"
        " runtime TEXT NOT NULL,"
        " path TEXT,"
        " model_ref TEXT,"
        " format TEXT,"
        " quantization TEXT,"
        " param_count TEXT,"
        " context_length INTEGER,"
        " size_bytes INTEGER,"
        " sha256 TEXT,"
        " facts TEXT NOT NULL DEFAULT '{}',"
        " claims TEXT NOT NULL DEFAULT '{}',"
        " user_metadata TEXT NOT NULL DEFAULT '{}',"
        " verified_capabilities TEXT NOT NULL DEFAULT '[]',"
        " capability_basis TEXT NOT NULL DEFAULT '{}',"
        " verification_state TEXT NOT NULL DEFAULT 'unverified',"
        " state TEXT NOT NULL DEFAULT 'usable',"
        " tags TEXT NOT NULL DEFAULT '[]',"
        " notes TEXT,"
        " success_count INTEGER NOT NULL DEFAULT 0,"
        " failure_count INTEGER NOT NULL DEFAULT 0,"
        " discovered_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " last_used_at TEXT,"
        " last_error TEXT)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_models_identity"
        " ON models(provider, COALESCE(path,''), COALESCE(model_ref,''))",
        "CREATE INDEX IF NOT EXISTS idx_models_state ON models(state)",
        "CREATE INDEX IF NOT EXISTS idx_models_runtime ON models(runtime)",
        "CREATE TABLE IF NOT EXISTS model_capability_tests ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " model_id TEXT NOT NULL,"
        " capability TEXT NOT NULL,"
        " outcome TEXT NOT NULL,"
        " detail TEXT,"
        " latency_ms REAL,"
        " resources TEXT,"
        " run_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_cap_tests_model ON model_capability_tests(model_id, capability)",
        "CREATE TABLE IF NOT EXISTS providers ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL UNIQUE,"
        " kind TEXT NOT NULL,"
        " base_url TEXT,"
        " enabled INTEGER NOT NULL DEFAULT 0,"
        " requires_credential INTEGER NOT NULL DEFAULT 0,"
        " credential_ref TEXT,"
        " privacy TEXT NOT NULL DEFAULT '{}',"
        " quotas TEXT NOT NULL DEFAULT '{}',"
        " claims TEXT NOT NULL DEFAULT '{}',"
        " verified INTEGER NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " last_checked_at TEXT,"
        " last_status TEXT,"
        " last_error TEXT)",
        "CREATE TABLE IF NOT EXISTS provider_usage ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " provider TEXT NOT NULL,"
        " model_id TEXT,"
        " kind TEXT NOT NULL,"
        " prompt_tokens INTEGER NOT NULL DEFAULT 0,"
        " completion_tokens INTEGER NOT NULL DEFAULT 0,"
        " cost_estimate REAL,"
        " success INTEGER NOT NULL DEFAULT 1,"
        " error_code TEXT,"
        " occurred_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_provider_usage_provider ON provider_usage(provider, occurred_at)",
        "CREATE TABLE IF NOT EXISTS credentials ("
        " id TEXT PRIMARY KEY,"
        " provider TEXT NOT NULL,"
        " ref TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " last_checked_at TEXT,"
        " valid INTEGER)",
    ),
)
