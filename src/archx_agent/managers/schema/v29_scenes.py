"""Released migration 29: scenes. Preserve its SQL and version."""

from archx_agent.helpers.sqlite_store import Migration


SCENES_V29 = Migration(
    version=29,
    name="scenes",
    statements=(
        # A scene is a document on disk plus the numbers computed from it. The document is the input
        # (objects, transforms, camera); every number beside it here was *derived* from the document
        # and can be recomputed - which is what `scene verify` does, out loud.
        "CREATE TABLE IF NOT EXISTS scenes ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL UNIQUE,"
        " path TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " checksum TEXT,"
        " objects INTEGER NOT NULL DEFAULT 0,"
        " vertices INTEGER NOT NULL DEFAULT 0,"
        " triangles INTEGER NOT NULL DEFAULT 0,"
        " surface_area REAL,"
        " volume REAL,"
        " bounding_box TEXT,"
        " camera TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " task_id TEXT)",
        # One row per object, because "which object is not watertight" is the question a scene raises
        # and a single scene-level flag cannot answer it.
        "CREATE TABLE IF NOT EXISTS scene_objects ("
        " id TEXT PRIMARY KEY,"
        " scene_id TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " primitive TEXT NOT NULL,"
        " params TEXT NOT NULL DEFAULT '{}',"
        " transform TEXT NOT NULL DEFAULT '{}',"
        " vertices INTEGER NOT NULL DEFAULT 0,"
        " faces INTEGER NOT NULL DEFAULT 0,"
        " triangles INTEGER NOT NULL DEFAULT 0,"
        " surface_area REAL,"
        " volume REAL,"
        " watertight INTEGER NOT NULL DEFAULT 0,"
        " open_edges INTEGER NOT NULL DEFAULT 0,"
        " bounding_box TEXT,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_scene_objects_scene ON scene_objects(scene_id)",
        # Everything a scene produced: the OBJ, the binary STL, the SVG preview, the Blender script
        # and - when a Blender exists - the render. Each with the hash of the bytes that were written,
        # so `scene verify` can disagree with a file that changed after the fact.
        "CREATE TABLE IF NOT EXISTS scene_outputs ("
        " id TEXT PRIMARY KEY,"
        " scene_id TEXT NOT NULL,"
        " kind TEXT NOT NULL,"
        " path TEXT,"
        " sha256 TEXT,"
        " bytes INTEGER,"
        " status TEXT NOT NULL,"
        " note TEXT,"
        " execution_run_id TEXT,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_scene_outputs_scene ON scene_outputs(scene_id)",
    ),
)
