"""Released migration 30: automation_revisions. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


AUTOMATIONS_V30 = Migration(
    version=30,
    name="automation_revisions",
    statements=(
        "ALTER TABLE automations ADD COLUMN revision INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE automation_runs ADD COLUMN job_id TEXT",
        "CREATE INDEX idx_automation_runs_job ON automation_runs(job_id)",
    ),
)
