"""Independent conversation keys, additive upgrade and real workspace replay."""

from __future__ import annotations

import json
from contextlib import closing

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.sqlite_store import SqliteStore
from archx_agent.managers.schema import MIGRATIONS, SCHEMA_VERSION


def test_multiple_keys_are_independent_and_conversation_scoped(domain):
    manager = domain.conversations
    first, second = manager.create("first"), manager.create("second")
    manager.set_setting(first.id, "temperature", 0.3)
    manager.set_setting(first.id, "language", "Urdu")
    manager.set_setting(second.id, "temperature", 0.7)
    manager.set_setting(first.id, "temperature", 0.1)
    assert manager.settings(first.id) == {"temperature": 0.1, "language": "Urdu"}
    assert manager.get_setting(second.id, "temperature") == 0.7
    assert manager.get_setting(first.id, "missing", "default") == "default"
    assert (
        sum(
            row["kind"] == "conversation.setting"
            for row in domain.coordinator.journal()
        )
        == 4
    )


@pytest.mark.parametrize("value", [None, False, 0, [], {}, {"nested": ["اردو", 2]}])
def test_json_values_round_trip(domain, value):
    conv = domain.conversations.create()
    domain.conversations.set_setting(conv.id, "value", value)
    assert domain.conversations.get_setting(conv.id, "value", "missing") == value


@pytest.mark.parametrize("key", ["", "  ", None, 5])
def test_invalid_keys_refused_without_side_effect(domain, key):
    conv = domain.conversations.create()
    with pytest.raises(ValidationError):
        domain.conversations.set_setting(conv.id, key, "bad")
    assert domain.conversations.settings(conv.id) == {}


def test_unserializable_value_and_missing_conversation_refused(domain):
    conv = domain.conversations.create()
    with pytest.raises(ValidationError):
        domain.conversations.set_setting(conv.id, "bad", object())
    with pytest.raises(NotFoundError):
        domain.conversations.set_setting("missing", "key", 1)
    domain.conversations.delete(conv.id)
    with pytest.raises(NotFoundError):
        domain.conversations.set_setting(conv.id, "key", 1)


def test_upgrade_v30_retains_legacy_values_and_is_idempotent(tmp_path):
    path = tmp_path / "upgrade.db"
    with closing(SqliteStore(path)) as store:
        store.migrate(MIGRATIONS[:30])
        with store.write_tx() as tx:
            # Legacy orphan rows are retained as well; do not silently discard data.
            tx.execute(
                "INSERT INTO conversation_settings VALUES (?,?,?)",
                ("old", "language", '"Urdu"'),
            )
        assert store.migrate(MIGRATIONS) == SCHEMA_VERSION == 31
        with store.write_tx() as tx:
            tx.execute(
                "INSERT INTO conversation_settings VALUES (?,?,?)",
                ("old", "theme", '"dark"'),
            )
        assert store.migrate(MIGRATIONS) == SCHEMA_VERSION
        assert (
            len(
                store.query(
                    "SELECT * FROM conversation_settings WHERE conversation_id='old'"
                )
            )
            == 2
        )
        assert store.integrity_check() == ["ok"]
    with closing(SqliteStore(path)) as reopened:
        assert (
            json.loads(
                reopened.scalar(
                    "SELECT value FROM conversation_settings WHERE key='language'"
                )
            )
            == "Urdu"
        )


def test_real_workspace_restart_replays_unfinished_setting_once(tmp_path):
    home = tmp_path / "home"
    with open_workspace(home=home) as ws:
        conv = ws.conversations.create("restart")
        ws.conversations.set_setting(conv.id, "first", 1)
        op_id = ws.coordinator.begin_durable(
            "conversation.setting",
            {
                "conversation_id": conv.id,
                "key": "second",
                "value": json.dumps({"nested": True}),
            },
        )
    with open_workspace(home=home) as ws:
        assert ws.conversations.settings(conv.id) == {
            "first": 1,
            "second": {"nested": True},
        }
        assert ws.coordinator.replay() == 0
        assert (
            ws.store.scalar(
                "SELECT COUNT(*) FROM applied_writes WHERE op_id=?", (op_id,)
            )
            == 1
        )
        assert any("replayed 1 interrupted write" in item for item in ws.warnings)


def test_pending_setting_cannot_recreate_deleted_conversation_state(tmp_path):
    with open_workspace(home=tmp_path / "home") as ws:
        conv = ws.conversations.create()
        ws.coordinator.begin_durable(
            "conversation.setting",
            {
                "conversation_id": conv.id,
                "key": "x",
                "value": "1",
            },
        )
        ws.conversations.delete(conv.id, hard=True, confirm=True)
    with open_workspace(home=tmp_path / "home") as ws:
        assert ws.conversations.settings(conv.id) == {}


def test_upgrade_runs_through_workspace_and_creates_backup(tmp_path):
    from archx_agent.helpers.config import load_config

    home = tmp_path / "home"
    cfg = load_config(home=home, env={}, create=True)
    cfg.ensure_dirs()
    with closing(SqliteStore(cfg.path("storage.db_path"))) as store:
        store.migrate(MIGRATIONS[:30])
        with store.write_tx() as tx:
            tx.execute(
                "INSERT INTO conversation_settings VALUES (?,?,?)",
                ("legacy", "key", "3"),
            )
    with open_workspace(home=home) as ws:
        assert ws.store.schema_version() == 31
        assert ws.conversations.get_setting("legacy", "key") == 3
        assert any("backed up v30 database" in item for item in ws.warnings)
        assert list(cfg.path("paths.backups").iterdir())


def test_failed_upgrade_rolls_back_rename_and_keeps_legacy_data(tmp_path):
    from archx_agent.helpers.exceptions import StorageError
    from archx_agent.helpers.sqlite_store import Migration

    with closing(SqliteStore(tmp_path / "rollback.db")) as store:
        store.migrate(MIGRATIONS[:30])
        with store.write_tx() as tx:
            tx.execute(
                "INSERT INTO conversation_settings VALUES (?,?,?)", ("old", "key", "5")
            )
        broken = Migration(
            version=31,
            name="injected_failure",
            statements=(
                MIGRATIONS[-1].statements[0],
                "THIS IS NOT SQL",
            ),
        )
        with pytest.raises(StorageError):
            store.migrate((*MIGRATIONS[:30], broken))
        assert store.schema_version() == 30
        assert (
            store.scalar(
                "SELECT value FROM conversation_settings WHERE conversation_id='old'"
            )
            == "5"
        )
        assert not store.table_exists("conversation_settings_v1")
