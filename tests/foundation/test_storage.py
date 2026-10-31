from __future__ import annotations

from tests.paths import SRC as SOURCE_ROOT

import json
import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from archx_agent.helpers.backup_recovery import (
    apply_retention,
    create_backup,
    list_backups,
    preview_restore,
    restore_backup,
    verify_backup,
)
from archx_agent.helpers.events import EventStore
from archx_agent.helpers.exceptions import SchemaVersionError, StorageError
from archx_agent.helpers.sqlite_store import Migration, SqliteStore
from archx_agent.helpers.write_coordinator import WriteCoordinator
from archx_agent.helpers.result import WriteOutcome

SRC = str(SOURCE_ROOT)

COUNTER_MIGRATION = Migration(
    version=1,
    name="counter",
    statements=(
        "CREATE TABLE IF NOT EXISTS counter (k TEXT PRIMARY KEY, v INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)",
    ),
)


def _bump(tx, payload):
    tx.execute("INSERT INTO counter(k, v) VALUES ('n', 0) ON CONFLICT(k) DO NOTHING")
    tx.execute("UPDATE counter SET v = v + 1 WHERE k='n'")
    return tx.scalar("SELECT v FROM counter WHERE k='n'")


def _add_item(tx, payload):
    tx.execute("INSERT INTO items(name) VALUES (?)", (payload["name"],))
    return {"name": payload["name"]}


class TestSqliteStore:
    def test_migrations_apply_once(self, tmp_path):
        store = SqliteStore(tmp_path / "a.db")
        assert store.schema_version() == 0
        assert store.migrate([COUNTER_MIGRATION]) == 1
        assert store.migrate([COUNTER_MIGRATION]) == 1
        assert store.table_counts()["counter"] == 0
        store.close()

    def test_newer_schema_rejected(self, tmp_path):
        store = SqliteStore(tmp_path / "b.db")
        store.migrate([COUNTER_MIGRATION])
        store.execute("INSERT INTO schema_migrations(version, name, applied_at) VALUES (99,'future','now')")
        with pytest.raises(SchemaVersionError):
            store.migrate([COUNTER_MIGRATION])
        store.close()

    def test_transaction_rolls_back(self, tmp_path):
        store = SqliteStore(tmp_path / "c.db")
        store.migrate([COUNTER_MIGRATION])
        with pytest.raises(RuntimeError):
            with store.write_tx() as tx:
                tx.execute("INSERT INTO items(name) VALUES ('x')")
                raise RuntimeError("boom")
        assert store.scalar("SELECT COUNT(*) FROM items") == 0
        store.close()

    def test_integrity_and_unicode(self, tmp_path):
        store = SqliteStore(tmp_path / "d.db")
        store.migrate([COUNTER_MIGRATION])
        store.execute("INSERT INTO items(name) VALUES (?)", ("名前/файл",))
        assert store.integrity_check() == ["ok"]
        assert store.query_one("SELECT name FROM items")["name"] == "名前/файл"
        store.close()

    def test_corrupt_database_detected(self, tmp_path):
        path = tmp_path / "e.db"
        store = SqliteStore(path)
        store.migrate([COUNTER_MIGRATION])
        store.close()
        with open(path, "r+b") as fh:
            fh.seek(0)
            fh.write(b"\xff" * 400)
        broken = SqliteStore(path)
        with pytest.raises(StorageError):
            broken.query("SELECT * FROM items")
        broken.close()

    def test_concurrent_processes_writing(self, tmp_path):
        path = str(tmp_path / "f.db")
        store = SqliteStore(path)
        store.migrate([COUNTER_MIGRATION])
        store.close()
        script = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {SRC!r})
            from archx_agent.helpers.sqlite_store import SqliteStore
            store = SqliteStore({path!r})
            for i in range(50):
                store.execute("INSERT INTO items(name) VALUES (?)", (f"{{sys.argv[1]}}-{{i}}",))
            store.close()
            """
        )
        procs = [subprocess.Popen([sys.executable, "-c", script, f"p{n}"]) for n in range(3)]
        assert all(p.wait(timeout=60) == 0 for p in procs)
        check = SqliteStore(path)
        assert check.scalar("SELECT COUNT(*) FROM items") == 150
        check.close()

    def test_unwritable_path_reports_cleanly(self, tmp_path):
        target = tmp_path / "ro" / "x.db"
        (tmp_path / "ro").mkdir()
        os.chmod(tmp_path / "ro", 0o500)
        try:
            with pytest.raises(Exception) as exc:
                store = SqliteStore(target)
                store.execute("CREATE TABLE t (a)")
            assert "ro" in str(exc.value) or "unable" in str(exc.value).lower() or "readonly" in str(exc.value).lower()
        finally:
            os.chmod(tmp_path / "ro", 0o700)


class TestWriteCoordinator:
    def test_committed_after_commit_only(self, store):
        store.migrate([COUNTER_MIGRATION])
        co = WriteCoordinator(store, name="t1")
        co.register("counter.bump", _bump)
        receipt = co.submit("counter.bump", {})
        assert receipt.outcome is WriteOutcome.COMMITTED
        assert receipt.value == 1
        assert co.applied_count() == 1
        co.stop()

    def test_exactly_once_same_op_id(self, store):
        store.migrate([COUNTER_MIGRATION])
        co = WriteCoordinator(store, name="t2")
        co.register("counter.bump", _bump)
        first = co.submit("counter.bump", {}, op_id="op-fixed")
        second = co.submit("counter.bump", {}, op_id="op-fixed")
        assert first.outcome is WriteOutcome.COMMITTED
        assert second.outcome is WriteOutcome.DUPLICATE
        assert store.scalar("SELECT v FROM counter") == 1
        co.stop()

    def test_duplicate_name_failure_is_reported(self, store):
        store.migrate([COUNTER_MIGRATION])
        co = WriteCoordinator(store, name="t3")
        co.register("item.add", _add_item)
        assert co.submit("item.add", {"name": "a"}).outcome is WriteOutcome.COMMITTED
        dup = co.submit("item.add", {"name": "a"})
        assert dup.outcome is WriteOutcome.FAILED
        assert dup.error is not None
        assert store.scalar("SELECT COUNT(*) FROM items") == 1
        co.stop()

    def test_unknown_kind_and_double_registration(self, store):
        co = WriteCoordinator(store, name="t4")
        with pytest.raises(StorageError):
            co.submit("nope", {})
        co.register("counter.bump", _bump)
        with pytest.raises(StorageError):
            co.register("counter.bump", _add_item)
        with pytest.raises(StorageError):
            co.register("bad kind!", _bump)
        co.stop()

    def test_backpressure_returns_pending_not_success(self, store):
        store.migrate([COUNTER_MIGRATION])

        def slow(tx, payload):
            time.sleep(0.05)
            return _bump(tx, payload)

        co = WriteCoordinator(store, name="t5", max_queue=1)
        co.register("counter.bump", slow)
        receipts = [co.submit("counter.bump", {}, wait=False) for _ in range(20)]
        outcomes = {r.outcome for r in receipts}
        assert WriteOutcome.PENDING in outcomes
        assert not any(r.committed for r in receipts if r.outcome is WriteOutcome.PENDING)
        co.stop()

    def test_durable_two_phase_and_replay(self, store):
        store.migrate([COUNTER_MIGRATION])
        co = WriteCoordinator(store, name="t6")
        co.register("counter.bump", _bump)
        co.begin_durable("counter.bump", {})
        # simulate a crash before completion
        assert store.scalar("SELECT v FROM counter") is None
        assert co.replay() == 1
        assert store.scalar("SELECT v FROM counter") == 1
        assert co.replay() == 0  # applied_writes prevents double apply
        co.stop()

    def test_graceful_stop_drains_queue(self, store):
        store.migrate([COUNTER_MIGRATION])
        co = WriteCoordinator(store, name="t7")
        co.register("counter.bump", _bump)
        for _ in range(30):
            co.submit("counter.bump", {}, wait=False)
        co.stop()
        assert store.scalar("SELECT v FROM counter") == 30

    def test_crash_mid_write_leaves_consistent_db(self, tmp_path):
        path = str(tmp_path / "crash.db")
        store = SqliteStore(path)
        store.migrate([COUNTER_MIGRATION])
        store.close()
        script = textwrap.dedent(
            f"""
            import sys, time
            sys.path.insert(0, {SRC!r})
            from archx_agent.helpers.sqlite_store import SqliteStore
            from archx_agent.helpers.write_coordinator import WriteCoordinator
            store = SqliteStore({path!r})
            co = WriteCoordinator(store, name="crash", start=False)
            def bump(tx, payload):
                tx.execute("INSERT INTO counter(k,v) VALUES ('n',0) ON CONFLICT(k) DO NOTHING")
                tx.execute("UPDATE counter SET v=v+1 WHERE k='n'")
                return None
            co.register("counter.bump", bump)
            print("ready", flush=True)
            i = 0
            while True:
                op = co.begin_durable("counter.bump", {{}}, op_id=f"op-{{i}}")
                co.complete_durable(op)
                i += 1
            """
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        try:
            line = proc.stdout.readline()
            assert "ready" in line
            time.sleep(0.4)
            os.kill(proc.pid, signal.SIGKILL)
        finally:
            proc.wait(timeout=30)
        check = SqliteStore(path)
        assert check.integrity_check() == ["ok"]
        journal = check.query("SELECT state, COUNT(*) n FROM write_journal GROUP BY state")
        states = {row["state"]: row["n"] for row in journal}
        applied = check.scalar("SELECT COUNT(*) FROM applied_writes")
        value = check.scalar("SELECT v FROM counter")
        # every applied write is a committed journal row and vice versa
        assert states.get("committed", 0) == applied
        assert value == applied
        # replay repairs any intent row that never completed
        co = WriteCoordinator(check, name="replay")
        co.register("counter.bump", lambda tx, p: tx.execute("UPDATE counter SET v=v+1 WHERE k='n'"))
        repaired = co.replay()
        assert check.scalar("SELECT v FROM counter") == applied + repaired
        co.stop()
        check.close()

    def test_multi_thread_write_safety(self, store):
        import threading

        store.migrate([COUNTER_MIGRATION])
        co = WriteCoordinator(store, name="mt")
        co.register("counter.bump", _bump)
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(25):
                    r = co.submit("counter.bump", {})
                    assert r.outcome is WriteOutcome.COMMITTED
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        assert not errors
        assert store.scalar("SELECT v FROM counter") == 100
        co.stop()


class TestEvents:
    def test_append_order_is_sequence_based(self, tmp_path):
        es = EventStore(tmp_path / "ev.db", capture_level="diagnostic")
        ids = [es.record("system", f"e{i}") for i in range(5)]
        es.flush()
        events = es.query(limit=10)
        assert [e.name for e in events] == [f"e{i}" for i in range(5)]
        assert [e.seq for e in events] == sorted(e.seq for e in events)
        assert all(ids)
        es.close()

    def test_capture_level_filters(self, tmp_path):
        es = EventStore(tmp_path / "ev2.db", capture_level="summary")
        assert es.record("system", "detail", level="detailed") is None
        assert es.record("system", "summary", level="summary") is not None
        assert es.record("system", "boom", level="diagnostic", status="error") is not None
        es.flush()
        assert es.count() == 2
        es.close()

    def test_unknown_kind_and_level_rejected(self, events):
        from archx_agent.helpers.exceptions import ValidationError

        with pytest.raises(ValidationError):
            events.record("not-a-kind", "x")
        with pytest.raises(ValidationError):
            events.record("system", "x", level="verbose")

    def test_secrets_redacted_on_write_and_export(self, tmp_path, monkeypatch):
        from archx_agent.helpers.redaction import register_secret

        secret = "sk-live-ABCDEFGHIJKLMNOPQRSTUV"
        register_secret(secret)
        es = EventStore(tmp_path / "ev3.db", capture_level="diagnostic")
        es.record("provider", "call", payload={"api_key": secret, "note": f"token {secret}"})
        es.flush()
        row = es.query(limit=1)[0]
        assert secret not in json.dumps(row.payload)
        out = es.export_jsonl(tmp_path / "export.jsonl")
        assert secret not in out.read_text()
        es.close()

    def test_causal_tree_and_filters(self, events):
        root = events.record("task", "root", task_id="t1")
        child = events.record("tool_call", "child", parent_id=root, task_id="t1")
        events.record("tool_call", "grandchild", parent_id=child, task_id="t1")
        events.record("task", "other", task_id="t2")
        events.flush()
        tree = events.trace_tree(root)
        assert tree["event"]["name"] == "root"
        assert tree["children"][0]["event"]["name"] == "child"
        assert tree["children"][0]["children"][0]["event"]["name"] == "grandchild"
        assert len(events.query(task_id="t1")) == 3
        assert len(events.query(kind="task")) == 2

    def test_retention_and_errors(self, events):
        for i in range(5):
            events.record("system", f"ok{i}")
        events.record("system", "bad", status="error")
        events.flush()
        removed = events.apply_retention(max_events=3)
        assert removed >= 3
        remaining = events.query(limit=100)
        assert any(e.status == "error" for e in remaining)

    def test_tree_missing_root(self, events):
        from archx_agent.helpers.exceptions import ValidationError

        with pytest.raises(ValidationError):
            events.trace_tree("does-not-exist")


class TestBackupRecovery:
    def _make_db(self, tmp_path):
        db = tmp_path / "data.db"
        store = SqliteStore(db)
        store.migrate([COUNTER_MIGRATION])
        for i in range(5):
            store.execute("INSERT INTO items(name) VALUES (?)", (f"i{i}",))
        store.close()
        return db

    def test_backup_verify_restore(self, tmp_path):
        db = self._make_db(tmp_path)
        backups = tmp_path / "backups"
        info = create_backup(db, backups, label="unit")
        assert info.size > 0
        report = verify_backup(info.path)
        assert report["ok"], report["problems"]
        # mutate the live database
        store = SqliteStore(db)
        store.execute("DELETE FROM items")
        store.close()
        preview = preview_restore(info.path, db)
        assert preview["backup_ok"] and preview["row_deltas"]["items"] == 5
        result = restore_backup(info.path, db)
        assert result["aside"] and os.path.exists(result["aside"])
        store = SqliteStore(db)
        assert store.scalar("SELECT COUNT(*) FROM items") == 5
        store.close()

    def test_tampered_backup_rejected(self, tmp_path):
        db = self._make_db(tmp_path)
        info = create_backup(db, tmp_path / "b", label="tamper")
        with open(info.path, "r+b") as fh:
            fh.seek(100)
            fh.write(b"XXXX")
        report = verify_backup(info.path)
        assert not report["ok"]
        assert any("hash" in p or "integrity" in p for p in report["problems"])
        with pytest.raises(Exception):
            restore_backup(info.path, db)

    def test_retention_moves_old_backups(self, tmp_path):
        db = self._make_db(tmp_path)
        directory = tmp_path / "b"
        for i in range(4):
            create_backup(db, directory, label=f"b{i}")
            time.sleep(0.01)
        retired = apply_retention(directory, keep=2)
        assert len(retired) == 2
        assert len(list_backups(directory)) == 2

    def test_restore_missing_file(self, tmp_path):
        with pytest.raises(Exception):
            restore_backup(tmp_path / "nope.db", tmp_path / "x.db")


@pytest.mark.parametrize("busy_commits", [2, 100])
def test_busy_commit_never_reenters_transaction_body(tmp_path, monkeypatch, busy_commits):
    """A locked commit retries the same transaction, not caller side effects."""
    from archx_agent.helpers import sqlite_store as storage
    from archx_agent.helpers.exceptions import StorageBusyError

    class Connection:
        def __init__(self):
            self.statements = []
            self.commits = 0

        def execute(self, statement):
            self.statements.append(statement)
            if statement == "COMMIT":
                self.commits += 1
                if self.commits <= busy_commits:
                    raise storage.sqlite3.OperationalError("database is locked")

    conn = Connection()
    store = SqliteStore(tmp_path / "commit.db")
    monkeypatch.setattr(store, "thread_conn", lambda: conn)
    monkeypatch.setattr(storage.time, "sleep", lambda _: None)
    effects = []
    if busy_commits >= storage._LOCK_RETRIES:
        with pytest.raises(StorageBusyError, match="commit busy"):
            with store.write_tx():
                effects.append("body ran")
        assert conn.statements.count("ROLLBACK") == 1
    else:
        with store.write_tx():
            effects.append("body ran")
        assert conn.commits == busy_commits + 1
        assert "ROLLBACK" not in conn.statements
    assert effects == ["body ran"]
    assert conn.statements.count("BEGIN IMMEDIATE") == 1
