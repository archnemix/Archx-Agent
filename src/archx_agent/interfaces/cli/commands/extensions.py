"""Extensions command: argument registration and execution."""

from __future__ import annotations

import argparse


from pathlib import Path


from archx_agent.helpers.jsonio import json_text


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    _workspace,
    _parse_tool_args,
    _execute_tool,
    EXIT_OK,
    EXIT_USAGE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    ext = sub.add_parser("extensions", help="install, trust and call extension tools")
    ex_sub = ext.add_subparsers(dest="extensions_command", required=True)
    ex_sub.add_parser("list", help="installed extensions and their trust")
    ex_install = ex_sub.add_parser(
        "install", help="install a directory containing extension.json"
    )
    ex_install.add_argument("path")
    ex_install.add_argument("--trust", action="store_true")
    ex_install.add_argument("--enable", action="store_true")
    ex_show = ex_sub.add_parser("show", help="manifest and tool rows for one extension")
    ex_show.add_argument("extension")
    for verb, text in (
        ("trust", "register the extension's tools"),
        ("untrust", "unregister them"),
        ("enable", "make a trusted extension's tools available"),
        ("disable", "unregister them temporarily"),
    ):
        sub_verb = ex_sub.add_parser(verb, help=text)
        sub_verb.add_argument("extension")
    ex_remove = ex_sub.add_parser("remove", help="remove an extension and its tools")
    ex_remove.add_argument("extension")
    ex_tools = ex_sub.add_parser("tools", help="tools recorded for an extension")
    ex_tools.add_argument("extension")
    ex_call = ex_sub.add_parser("call", help="call an extension tool (needs a grant)")
    ex_call.add_argument("extension")
    ex_call.add_argument("tool")
    ex_call.add_argument("--arg", action="append", default=[], metavar="key=value")
    ex_call.add_argument("--conversation")
    ex_call.add_argument("--task")
    ex_call.add_argument("--project")
    ex_call.add_argument("--purpose")


def cmd_extensions(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.extensions
        command = args.extensions_command
        if command == "list":
            rows = manager.status()
            if args.json:
                emit_json(rows)
            else:
                if not rows:
                    emit("no extensions installed")
                else:
                    emit(
                        table(
                            [
                                [
                                    r["name"],
                                    r["version"],
                                    r["trust"],
                                    "yes" if r["enabled"] else "no",
                                    r["tool_count"],
                                    r["registered"],
                                ]
                                for r in rows
                            ],
                            [
                                "extension",
                                "version",
                                "trust",
                                "enabled",
                                "tools",
                                "registered",
                            ],
                        )
                    )
                    emit("")
                    emit(
                        "installing records the manifest; trusting and enabling are separate acts,"
                        " and every tool call still needs a grant"
                    )
            return EXIT_OK
        if command == "install":
            path = args.path
            if not Path(path).exists():
                candidate = ws.extensions_dir() / path
                if candidate.exists():
                    path = str(candidate)
            extension = manager.install(path, trust=args.trust, enable=args.enable)
            if args.json:
                emit_json(extension.to_dict())
            else:
                emit(
                    f"installed {extension.name} {extension.version} (id {extension.id})"
                )
                emit(f"  manifest sha256 {extension.manifest_hash}")
                emit(f"  trust={extension.trust} enabled={extension.enabled}")
                for tool in extension.manifest.get("tools") or []:
                    emit(
                        f"  tool {tool['name']:<16} needs {tool['capability']} (risk {tool['risk']})"
                    )
                if not (extension.trusted and extension.enabled):
                    emit(
                        f"  nothing is callable yet: archx-agent extensions trust {extension.name} "
                        f"&& archx-agent extensions enable {extension.name}"
                    )
            return EXIT_OK
        if command == "show":
            extension = manager.extension(args.extension)
            data = extension.to_dict()
            data["manifest"] = extension.manifest
            data["tool_rows"] = manager.tools_of(extension.id)
            emit_json(data) if args.json else emit(json_text(data))
            return EXIT_OK
        if command in ("trust", "untrust"):
            extension = manager.trust(args.extension, trusted=command == "trust")
            emit_json(extension.to_dict()) if args.json else emit(
                f"{extension.name}: trust={extension.trust}"
                + (
                    " (tools registered)"
                    if extension.trusted and extension.enabled
                    else " (nothing callable)"
                )
            )
            return EXIT_OK
        if command in ("enable", "disable"):
            extension = manager.set_enabled(args.extension, enabled=command == "enable")
            emit_json(extension.to_dict()) if args.json else emit(
                f"{extension.name}: enabled={extension.enabled}"
                + (
                    " (tools registered)"
                    if extension.trusted and extension.enabled
                    else " (nothing callable)"
                )
            )
            return EXIT_OK
        if command == "remove":
            extension = manager.remove(args.extension)
            emit_json(extension.to_dict()) if args.json else emit(
                f"removed extension {extension.name}"
            )
            return EXIT_OK
        if command == "tools":
            extension = manager.extension(args.extension)
            rows = manager.tools_of(extension.id)
            emit_json(rows) if args.json else emit(
                table(
                    [
                        [
                            r["name"],
                            r["capability"],
                            r["risk"],
                            "yes" if r["enabled"] else "no",
                            (r["description"] or "")[:44],
                        ]
                        for r in rows
                    ],
                    ["tool", "capability", "risk", "callable", "description"],
                )
            ) if rows else emit("no tools recorded")
            return EXIT_OK
        if command == "call":
            arguments = _parse_tool_args(args.arg)
            extension = manager.extension(args.extension)
            name = manager.spec_name(extension.name, args.tool)
            return _execute_tool(ws, ws.tools, name, arguments, args)
    return EXIT_USAGE
