"""Versions command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_UNAVAILABLE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    versions = sub.add_parser(
        "versions", help="content versions: history, diff, restore"
    )
    v_sub = versions.add_subparsers(dest="versions_command", required=True)
    v_list = v_sub.add_parser("list", help="versions of one subject")
    v_list.add_argument("subject_type")
    v_list.add_argument("subject_id")
    v_record = v_sub.add_parser(
        "record", help="record the current content as a version"
    )
    v_record.add_argument("subject_type")
    v_record.add_argument("subject_id")
    v_record.add_argument("--content")
    v_record.add_argument("--file")
    v_record.add_argument("--note", default="")
    v_record.add_argument("--label")
    v_record.add_argument("--by", default="user")
    v_record.add_argument(
        "--no-content",
        action="store_true",
        help="record only checksum and size (binary or large content)",
    )
    v_show = v_sub.add_parser("show", help="one version (content included)")
    v_show.add_argument("subject_type")
    v_show.add_argument("subject_id")
    v_show.add_argument("version", nargs="?", default="latest")
    v_diff = v_sub.add_parser("diff", help="unified diff between two versions")
    v_diff.add_argument("subject_type")
    v_diff.add_argument("subject_id")
    v_diff.add_argument("--from", dest="from_version")
    v_diff.add_argument("--to", dest="to_version")
    v_restore = v_sub.add_parser(
        "restore", help="write an old version as a new version"
    )
    v_restore.add_argument("subject_type")
    v_restore.add_argument("subject_id")
    v_restore.add_argument("version")
    v_restore.add_argument("--note", default="")
    v_sub.add_parser("subjects", help="subjects that have versions")


def cmd_versions(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.versions
        if manager is None:
            return fail(
                "no version store is available in this workspace", EXIT_UNAVAILABLE
            )
        command = args.versions_command
        if command == "list":
            versions = manager.history(args.subject_type, args.subject_id)
            if args.json:
                emit_json([v.to_dict() for v in versions])
            else:
                if not versions:
                    emit("no versions recorded")
                else:
                    emit(
                        table(
                            [
                                [
                                    v.version,
                                    v.created_at[11:19],
                                    v.created_by,
                                    v.size,
                                    "yes" if v.content_stored else "no",
                                    v.note[:40],
                                ]
                                for v in versions
                            ],
                            ["version", "time", "by", "bytes", "content", "note"],
                        )
                    )
            return EXIT_OK
        if command == "record":
            write = manager.record(
                args.subject_type,
                args.subject_id,
                content=args.content,
                path=args.file,
                note=args.note,
                created_by=args.by,
                version=args.label,
                store_content=False if args.no_content else None,
            )
            if args.json:
                emit_json(write.to_dict())
            else:
                if write.created:
                    emit(
                        f"recorded {write.version.version} of {write.version.subject_type} "
                        f"{write.version.subject_id} ({write.version.size} bytes, "
                        f"sha256 {write.version.checksum[:12]}...)"
                    )
                else:
                    emit(f"nothing recorded: {write.reason}")
            return EXIT_OK
        if command == "show":
            version = manager.at(args.subject_type, args.subject_id, args.version)
            data = version.to_dict(with_content=True)
            if args.json:
                emit_json(data)
            else:
                emit(
                    f"{version.subject_type} {version.subject_id} {version.version}"
                    f"  ({version.size} bytes, {version.created_at}, by {version.created_by})"
                )
                if version.restored_from:
                    emit(f"restored from {version.restored_from}")
                if version.note:
                    emit(f"note: {version.note}")
                emit("")
                emit(
                    version.content
                    if version.content_stored
                    else "(content was not stored)"
                )
            return EXIT_OK
        if command == "diff":
            data = manager.diff(
                args.subject_type,
                args.subject_id,
                args.from_version,
                args.to_version,
            )
            if args.json:
                emit_json(data)
            else:
                emit(
                    f"{data['from']} -> {data['to']}: +{data['added']} -{data['removed']}"
                )
                emit(data["text"] or "(no textual difference)")
            return EXIT_OK
        if command == "restore":
            write = manager.restore(
                args.subject_type, args.subject_id, args.version, note=args.note
            )
            emit_json(write.to_dict()) if args.json else emit(
                f"restored {args.version} as {write.version.version} of "
                f"{write.version.subject_type} {write.version.subject_id} (history kept)"
            )
            return EXIT_OK
        if command == "subjects":
            rows = manager.subjects()
            if args.json:
                emit_json(rows)
            else:
                emit(
                    table(
                        [
                            [
                                r["subject_type"],
                                r["subject_id"],
                                r["versions"],
                                r["latest_ordinal"],
                            ]
                            for r in rows
                        ],
                        ["type", "subject", "versions", "latest"],
                    )
                )
            return EXIT_OK
    return EXIT_USAGE
