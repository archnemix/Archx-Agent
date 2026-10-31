"""Released migration 24: media. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


MEDIA_V24 = Migration(
    version=24,
    name="media",
    statements=(
        # What a file *is*, measured from its own bytes. The row keeps the measurement and the
        # name's claim separately, because a `.png` that is really a JPEG is a finding.
        "CREATE TABLE IF NOT EXISTS media_assets ("
        " id TEXT PRIMARY KEY,"
        " kind TEXT NOT NULL,"
        " format TEXT NOT NULL,"
        " path TEXT NOT NULL,"
        " sha256 TEXT NOT NULL,"
        " bytes INTEGER NOT NULL,"
        " width INTEGER,"
        " height INTEGER,"
        " duration_ms INTEGER,"
        " sample_rate INTEGER,"
        " channels INTEGER,"
        " bits_per_sample INTEGER,"
        " name_claim TEXT,"
        " name_mismatch TEXT,"
        " facts TEXT NOT NULL DEFAULT '{}',"
        " task_id TEXT,"
        " created_at TEXT NOT NULL,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        # Every attempt to hear or speak is a row - including the ones this build must refuse,
        # because "there is no speech model here" is the most useful thing it can record.
        "CREATE TABLE IF NOT EXISTS voice_attempts ("
        " id TEXT PRIMARY KEY,"
        " asset_id TEXT,"
        " action TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " reason TEXT,"
        " engine TEXT,"
        " chars INTEGER,"
        " task_id TEXT,"
        " created_at TEXT NOT NULL,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        # A transcript says where it came from. Today the only honest source is a person.
        "CREATE TABLE IF NOT EXISTS voice_transcripts ("
        " id TEXT PRIMARY KEY,"
        " asset_id TEXT NOT NULL,"
        " text TEXT NOT NULL,"
        # A CHECK, not a convention: no speech model exists in this build, so the only honest
        # source is a person, and a row that claims otherwise cannot be written - not even by
        # hand, not even by a future migration that forgets to look.
        " source TEXT NOT NULL CHECK (source IN ('human')),"
        " created_at TEXT NOT NULL,"
        " task_id TEXT,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        "CREATE INDEX IF NOT EXISTS idx_media_sha ON media_assets(sha256)",
        "CREATE INDEX IF NOT EXISTS idx_media_created ON media_assets(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_voice_attempts_asset ON voice_attempts(asset_id)",
        "CREATE INDEX IF NOT EXISTS idx_voice_transcripts_asset ON voice_transcripts(asset_id)",
    ),
)
