"""Released migration 23: play. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


PLAY_V23 = Migration(
    version=23,
    name="play",
    statements=(
        # `games` and `game_moves` were reserved for this milestone in v8, so they are adopted
        # rather than redefined: ALTER keeps whatever a home already has, where CREATE TABLE IF
        # NOT EXISTS would silently leave the old shape in place (D157).
        "ALTER TABLE games ADD COLUMN seed INTEGER",
        "ALTER TABLE games ADD COLUMN move_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE games ADD COLUMN task_id TEXT",
        "ALTER TABLE games ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'",
        # Why a move was refused is evidence, not a detail: the illegal attempt is the record.
        "ALTER TABLE game_moves ADD COLUMN reason TEXT",
        "ALTER TABLE game_moves ADD COLUMN state_hash TEXT",
        # A simulation is a record of a deterministic run: the parameters, the series, and the
        # hash of the final grid, so `play sim replay` can disagree with it if it is wrong.
        "CREATE TABLE IF NOT EXISTS play_sims ("
        " id TEXT PRIMARY KEY,"
        " kind TEXT NOT NULL,"
        " width INTEGER NOT NULL,"
        " height INTEGER NOT NULL,"
        " steps INTEGER NOT NULL,"
        " seed INTEGER NOT NULL,"
        " density REAL NOT NULL DEFAULT 0.3,"
        " status TEXT NOT NULL,"
        " final_hash TEXT,"
        " alive INTEGER,"
        " series TEXT NOT NULL DEFAULT '[]',"
        " rows TEXT NOT NULL DEFAULT '[]',"
        " task_id TEXT,"
        " created_at TEXT NOT NULL,"
        " completed_at TEXT,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        "CREATE INDEX IF NOT EXISTS idx_game_moves_game ON game_moves(game_id, seq)",
        "CREATE INDEX IF NOT EXISTS idx_play_sims_created ON play_sims(created_at)",
    ),
)
