"""Released migration 20: research_closure. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


RESEARCH_CLOSURE_V20 = Migration(
    version=20,
    name="research-closure",
    statements=(
        # A run's status describes what the runner did (completed / incomplete / failed). It
        # does not describe whether *you* are done with the question - and inferring that from
        # coverage is how a research tool starts flattering. Closure is a separate, explicit
        # fact: closed_at is set only by `research close`, never by the runner.
        "ALTER TABLE research_runs ADD COLUMN closed_at TEXT",
        "ALTER TABLE research_runs ADD COLUMN closed_note TEXT",
        "CREATE INDEX IF NOT EXISTS idx_research_runs_closed ON research_runs(closed_at)",
    ),
)
