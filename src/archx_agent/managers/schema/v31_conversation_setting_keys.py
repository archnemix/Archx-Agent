"""Upgrade conversation settings to independent keys, retaining legacy rows."""

from archx_agent.helpers.sqlite_store import Migration

CONVERSATION_SETTINGS_V31 = Migration(
    version=31,
    name="conversation_setting_keys",
    statements=(
        "ALTER TABLE conversation_settings RENAME TO conversation_settings_v1",
        "CREATE TABLE conversation_settings ("
        " conversation_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,"
        " PRIMARY KEY(conversation_id, key))",
        "INSERT INTO conversation_settings(conversation_id, key, value)"
        " SELECT conversation_id, key, value FROM conversation_settings_v1",
        "DROP TABLE conversation_settings_v1",
    ),
)
