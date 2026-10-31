"""Released migration 12: provider_privacy. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


PROVIDERS_V12 = Migration(
    version=12,
    name="provider-privacy",
    statements=(
        # v10 already created `providers` and `provider_usage`. Extending them is the
        # only honest option: a second catalogue would be a second source of truth.
        # `privacy` (v10) holds vendor *claims*; `privacy_confirmed` holds what the
        # user confirmed. They are separate columns on purpose.
        "ALTER TABLE providers ADD COLUMN slug TEXT",
        "ALTER TABLE providers ADD COLUMN api_style TEXT",
        "ALTER TABLE providers ADD COLUMN is_local INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE providers ADD COLUMN model_family TEXT",
        "ALTER TABLE providers ADD COLUMN privacy_confirmed TEXT",
        "ALTER TABLE providers ADD COLUMN claim_source TEXT",
        "ALTER TABLE providers ADD COLUMN price_in_per_1k REAL",
        "ALTER TABLE providers ADD COLUMN price_out_per_1k REAL",
        "ALTER TABLE providers ADD COLUMN currency TEXT",
        "ALTER TABLE providers ADD COLUMN notes TEXT",
        "ALTER TABLE providers ADD COLUMN consent_at TEXT",
        "ALTER TABLE providers ADD COLUMN consent_version TEXT",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_providers_slug ON providers(slug)",
        "CREATE INDEX IF NOT EXISTS idx_providers_kind ON providers(kind)",
        "CREATE TABLE IF NOT EXISTS provider_checks ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " provider_id TEXT NOT NULL,"
        " checked_at TEXT NOT NULL,"
        " status TEXT NOT NULL,"  # reachable | auth_failed | unreachable | model_missing | rate_limited
        " latency_ms REAL,"
        " detail TEXT,"
        " models_seen INTEGER)",
        "CREATE INDEX IF NOT EXISTS idx_provider_checks_provider ON provider_checks(provider_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_provider_usage_time ON provider_usage(provider, occurred_at)",
    ),
)
