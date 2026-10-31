"""Released migration 27: remote. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


REMOTE_V27 = Migration(
    version=27,
    name="remote",
    statements=(
        # `remote_jobs` was reserved in v8 (provider, status, config, estimate, actual, outputs,
        # approved_by). It is adopted with ALTER so a home that already has rows keeps them, and
        # gains what makes a remote result checkable: who computed it, at which endpoint, and a
        # hash that can be re-computed when the artifact comes back.
        "ALTER TABLE remote_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'training'",
        "ALTER TABLE remote_jobs ADD COLUMN dataset_id TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN endpoint TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN machine TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN protocol TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN bundle_sha256 TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN bundle_path TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN claimed_sha256 TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN received_sha256 TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN artifact_path TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN verified_at TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN verify_note TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN remote_job_id TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN received_at TEXT",
        "ALTER TABLE remote_jobs ADD COLUMN refusal TEXT",
        # One row per attempt to talk to an endpoint: a dispatch that never arrived is a finding,
        # in the same spirit as M34's refused probes and M36's refused runs.
        "CREATE TABLE IF NOT EXISTS remote_attempts ("
        " id TEXT PRIMARY KEY,"
        " job_id TEXT,"
        " action TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " detail TEXT,"
        " endpoint TEXT,"
        " created_at TEXT NOT NULL,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        "CREATE INDEX IF NOT EXISTS idx_remote_attempts_job ON remote_attempts(job_id)",
        "CREATE INDEX IF NOT EXISTS idx_remote_jobs_status ON remote_jobs(status)",
    ),
)
