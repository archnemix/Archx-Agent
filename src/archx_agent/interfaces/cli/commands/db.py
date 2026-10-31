"""Db command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.helpers.backup_recovery import (
    apply_retention,
    create_backup,
    list_backups,
    preview_restore,
    restore_backup,
    verify_backup,
)


from archx_agent.helpers.config import load_config


from archx_agent.helpers.jsonio import json_text


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_USAGE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    db = sub.add_parser("db", help="database health, backup and restore")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("check", help="integrity check and table counts")
    db_sub.add_parser("stats", help="row counts for every table")
    db_backup = db_sub.add_parser("backup", help="create a backup")
    db_backup.add_argument("--label", default="manual")
    db_sub.add_parser("backups", help="list backups")
    db_verify = db_sub.add_parser("verify", help="verify a backup")
    db_verify.add_argument("backup")
    db_preview = db_sub.add_parser(
        "preview-restore", help="preview a restore (changes nothing)"
    )
    db_preview.add_argument("backup")
    db_restore = db_sub.add_parser(
        "restore", help="restore a backup (the current db is renamed aside)"
    )
    db_restore.add_argument("backup")
    db_restore.add_argument("--yes", action="store_true")
    db_retention = db_sub.add_parser("retention", help="retire old backups")
    db_retention.add_argument("--keep", type=int, default=10)
    db_sub.add_parser("journal", help="show recent write-journal entries")


def cmd_db(args: argparse.Namespace) -> int:
    command = args.db_command
    if command == "restore":
        cfg = load_config(home=args.home, config_path=args.config, create=False)
        preview = preview_restore(args.backup, cfg.get("storage.db_path"))
        if not preview["backup_ok"]:
            return fail("backup failed verification: " + "; ".join(preview["problems"]))
        if not args.yes:
            emit(json_text(preview))
            emit(
                "re-run with --yes to restore (the current database is renamed aside, never deleted)"
            )
            return EXIT_USAGE
        result = restore_backup(args.backup, cfg.get("storage.db_path"))
        emit_json(result) if args.json else emit(json_text(result))
        return EXIT_OK
    with _workspace(args) as ws:
        if command == "check":
            integrity = ws.store.integrity_check()
            fk = ws.store.foreign_key_check()
            data = {
                "integrity": integrity,
                "foreign_keys": fk,
                "schema_version": ws.store.schema_version(),
                "tables": ws.store.table_counts(),
                "journal": ws.coordinator.journal(5),
            }
            if args.json:
                emit_json(data)
            else:
                emit(f"integrity     {', '.join(integrity)}")
                emit(f"foreign keys  {'ok' if not fk else fk}")
                emit(f"schema        v{data['schema_version']}")
                emit(f"tables        {len(data['tables'])}")
                emit(f"write journal {len(data['journal'])} recent entries")
            return EXIT_OK if integrity == ["ok"] and not fk else EXIT_ERROR
        if command == "stats":
            counts = ws.store.table_counts()
            emit_json(counts) if args.json else emit(
                table([[k, v] for k, v in sorted(counts.items())], ["table", "rows"])
            )
            return EXIT_OK
        if command == "backup":
            info = create_backup(
                ws.store.path, ws.config.path("paths.backups"), label=args.label
            )
            emit_json(info.to_dict()) if args.json else emit(
                f"backup written to {info.path} ({info.size} bytes)"
            )
            return EXIT_OK
        if command == "backups":
            rows = list_backups(ws.config.path("paths.backups"))
            if args.json:
                emit_json(rows)
            else:
                if not rows:
                    emit("no backups")
                for row in rows:
                    emit(f"{row['path']}  {row['size']} bytes  {row['created_at']}")
            return EXIT_OK
        if command == "verify":
            report = verify_backup(args.backup)
            emit_json(report) if args.json else emit(
                ("ok: " if report["ok"] else "FAILED: ")
                + ("; ".join(report["problems"]) or "verified")
            )
            return EXIT_OK if report["ok"] else EXIT_ERROR
        if command == "preview-restore":
            emit_json(
                preview_restore(args.backup, ws.store.path)
            ) if args.json else emit(
                json_text(preview_restore(args.backup, ws.store.path))
            )
            return EXIT_OK
        if command == "retention":
            retired = apply_retention(ws.config.path("paths.backups"), keep=args.keep)
            emit_json({"retired": retired}) if args.json else emit(
                f"retired {len(retired)} backup(s) to _retired/"
            )
            return EXIT_OK
        if command == "journal":
            rows = ws.coordinator.journal(20)
            if args.json:
                emit_json(rows)
            else:
                emit(
                    table(
                        [
                            [r["op_id"], r["kind"], r["state"], r["created_at"]]
                            for r in rows
                        ],
                        ["op", "kind", "state", "created"],
                    )
                )
            return EXIT_OK
    return EXIT_USAGE
