"""Projects command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.helpers.jsonio import json_text


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
    proj = sub.add_parser(
        "projects", help="project identity (project memory is scoped to a project)"
    )
    proj_sub = proj.add_subparsers(dest="project_command", required=True)
    proj_create = proj_sub.add_parser("create", help="create a project")
    proj_create.add_argument("name")
    proj_create.add_argument("--path", help="workspace directory")
    proj_create.add_argument("--description", default="")
    proj_sub.add_parser("list", help="list projects")
    proj_show = proj_sub.add_parser("show", help="show one project")
    proj_show.add_argument("project")
    proj_rename = proj_sub.add_parser("rename", help="rename a project")
    proj_rename.add_argument("project")
    proj_rename.add_argument("name")
    proj_archive = proj_sub.add_parser("archive", help="archive a project")
    proj_archive.add_argument("project")
    proj_link = proj_sub.add_parser("link", help="attach a conversation to a project")
    proj_link.add_argument("project")
    proj_link.add_argument("conversation")


def cmd_projects(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.projects
        command = args.project_command
        if command == "create":
            project = manager.create(
                args.name, root_path=args.path, description=args.description
            )
            emit_json(project.to_dict()) if args.json else emit(
                f"created project {project.id}  {project.name}"
                + (f"  ({project.path})" if project.path else "")
            )
            return EXIT_OK
        if command == "list":
            rows = [p.to_dict() for p in manager.list(include_archived=False)]
            emit_json(rows) if args.json else (
                emit(
                    table(
                        [
                            [r["id"], r["name"], r["path"] or "-", r["created_at"]]
                            for r in rows
                        ],
                        ["id", "name", "path", "created"],
                    )
                )
                if rows
                else emit("no projects")
            )
            return EXIT_OK
        if command == "show":
            result = manager.get(args.project)
            if result.is_err:
                return fail(result.error.message)
            emit_json(result.value.to_dict()) if args.json else emit(
                json_text(result.value.to_dict())
            )
            return EXIT_OK
        if command == "rename":
            result = manager.rename(args.project, args.name)
            if result.is_err:
                return fail(result.error.message)
            emit_json(result.value.to_dict()) if args.json else emit(
                f"renamed {result.value.id} -> {result.value.name}"
            )
            return EXIT_OK
        if command == "archive":
            result = manager.archive(args.project)
            if result.is_err:
                return fail(result.error.message)
            emit(f"archived {args.project} (memory and history are preserved)")
            return EXIT_OK
        if command == "link":
            result = ws.conversations.attach_project(args.conversation, args.project)
            if result.is_err:
                return fail(result.error.message)
            emit(f"linked conversation {args.conversation} to project {args.project}")
            return EXIT_OK
    return EXIT_USAGE
