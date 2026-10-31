"""Released migration 18: researcher_mode. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


RESEARCH_V18 = Migration(
    version=18,
    name="researcher-mode",
    statements=(
        # v8 reserved research_runs/research_sources. A research run needs more than a
        # question and a status: the plan it derived, what it could not establish, how much
        # of the question the evidence actually covered, and the report itself (so a report
        # is never only a file that may have been moved).
        "ALTER TABLE research_runs ADD COLUMN mode TEXT",
        "ALTER TABLE research_runs ADD COLUMN plan TEXT",
        "ALTER TABLE research_runs ADD COLUMN planned_by TEXT",
        "ALTER TABLE research_runs ADD COLUMN coverage REAL",
        "ALTER TABLE research_runs ADD COLUMN evidence_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE research_runs ADD COLUMN report TEXT",
        "ALTER TABLE research_runs ADD COLUMN error TEXT",
        "ALTER TABLE research_runs ADD COLUMN model_id TEXT",
        "ALTER TABLE research_runs ADD COLUMN settings TEXT",
        "ALTER TABLE research_runs ADD COLUMN updated_at TEXT",
        # A source is evidence or it is not. `kind`/`ref` say where it came from, `status`
        # says whether it was actually read, and the checksum makes the excerpt verifiable.
        "ALTER TABLE research_sources ADD COLUMN kind TEXT",
        "ALTER TABLE research_sources ADD COLUMN ref TEXT",
        "ALTER TABLE research_sources ADD COLUMN status TEXT",
        "ALTER TABLE research_sources ADD COLUMN error TEXT",
        "ALTER TABLE research_sources ADD COLUMN checksum TEXT",
        "ALTER TABLE research_sources ADD COLUMN bytes INTEGER",
        "ALTER TABLE research_sources ADD COLUMN relevance REAL",
        "ALTER TABLE research_sources ADD COLUMN credibility TEXT",
        "ALTER TABLE research_sources ADD COLUMN claims TEXT",
        "ALTER TABLE research_sources ADD COLUMN subquestion INTEGER",
        "CREATE INDEX IF NOT EXISTS idx_research_runs_status ON research_runs(status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_research_sources_run ON research_sources(run_id, id)",
    ),
)
