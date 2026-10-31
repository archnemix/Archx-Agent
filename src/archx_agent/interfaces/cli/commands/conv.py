"""Conv command: argument registration and execution."""

from __future__ import annotations

import argparse


from pathlib import Path


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_USAGE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    conv = sub.add_parser("conv", help="manage conversations")
    c_sub = conv.add_subparsers(dest="conv_command", required=True)
    c_sub.add_parser("list", help="list conversations")
    c_new = c_sub.add_parser("new", help="create a conversation")
    c_new.add_argument("title", nargs="?", default="New conversation")
    c_show = c_sub.add_parser("show", help="show a conversation")
    c_show.add_argument("conversation")
    c_search = c_sub.add_parser("search", help="search titles and messages")
    c_search.add_argument("query")
    c_rename = c_sub.add_parser("rename", help="rename a conversation")
    c_rename.add_argument("conversation")
    c_rename.add_argument("title")
    c_delete = c_sub.add_parser("delete", help="delete a conversation")
    c_delete.add_argument("conversation")
    c_delete.add_argument("--hard", action="store_true")
    c_delete.add_argument("--yes", action="store_true")
    c_restore = c_sub.add_parser("restore", help="restore a soft-deleted conversation")
    c_restore.add_argument("conversation")
    c_clear = c_sub.add_parser(
        "clear", help="hide messages from context without deleting them"
    )
    c_clear.add_argument("conversation")
    c_export = c_sub.add_parser("export", help="export a conversation")
    c_export.add_argument("conversation")
    c_export.add_argument("--format", choices=["json", "markdown"], default="json")
    c_export.add_argument("--out")


def cmd_conv(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        command = args.conv_command
        if command == "list":
            conversations = ws.conversations.list_conversations()
            if args.json:
                emit_json([c.to_dict() for c in conversations])
            else:
                if not conversations:
                    emit("no conversations yet")
                else:
                    emit(
                        table(
                            [
                                [c.id, c.title[:40], c.updated_at, c.project_id or "-"]
                                for c in conversations
                            ],
                            ["id", "title", "updated", "project"],
                        )
                    )
            return EXIT_OK
        if command == "new":
            conv = ws.conversations.create(args.title)
            emit(f"created conversation {conv.id} ({conv.title})")
            return EXIT_OK
        if command == "show":
            conv = ws.conversations.require(args.conversation)
            messages = ws.conversations.messages(conv.id, include_excluded=True)
            if args.json:
                emit_json(
                    {
                        "conversation": conv.to_dict(),
                        "messages": [m.to_dict() for m in messages],
                    }
                )
            else:
                emit(f"{conv.title}   ({conv.id})")
                emit(
                    f"created {conv.created_at}   updated {conv.updated_at}   messages {len(messages)}"
                )
                for message in messages:
                    flag = (
                        " [hidden]"
                        if message.excluded
                        else (" [pinned]" if message.pinned else "")
                    )
                    emit(
                        f"\n{message.seq:>3} {message.role}{flag}: {message.content[:500]}"
                    )
            return EXIT_OK
        if command == "search":
            hits = ws.conversations.search(args.query)
            if args.json:
                emit_json(hits)
            else:
                if not hits:
                    emit(f"no conversations match {args.query!r}")
                for hit in hits:
                    emit(
                        f"{hit['conversation_id']}  {hit['title'][:40]}  ({hit['matched']})"
                    )
                    emit(f"    {hit['excerpt']}")
            return EXIT_OK
        if command == "rename":
            conv = ws.conversations.rename(args.conversation, args.title)
            emit(f"renamed to {conv.title}")
            return EXIT_OK
        if command == "delete":
            if args.hard and not args.yes:
                return fail(
                    "hard delete removes messages; re-run with --yes to confirm",
                    EXIT_USAGE,
                )
            result = ws.conversations.delete(
                args.conversation, hard=args.hard, confirm=args.yes
            )
            emit(f"{args.conversation}: {result}")
            return EXIT_OK
        if command == "restore":
            conv = ws.conversations.restore(args.conversation)
            emit(f"restored {conv.title}")
            return EXIT_OK
        if command == "clear":
            hidden = ws.conversations.clear_context(args.conversation)
            emit(f"hid {hidden} message(s) from the active context (history preserved)")
            return EXIT_OK
        if command == "export":
            text = ws.conversations.export(args.conversation, fmt=args.format)
            if args.out:
                Path(args.out).write_text(text)
                emit(f"wrote {args.out}")
            else:
                emit(text)
            return EXIT_OK
    return EXIT_USAGE
