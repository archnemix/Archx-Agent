"""Mcp command: argument registration and execution."""

from __future__ import annotations

import argparse


import os


import sys


from archx_agent.helpers.exceptions import (
    ArchxError,
)


from archx_agent.helpers.jsonio import json_text


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    _parse_tool_args,
    _execute_tool,
    _pairs,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_UNAVAILABLE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    mcp = sub.add_parser("mcp", help="MCP client servers and the optional MCP server")
    mc_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mc_sub.add_parser("servers", help="configured servers, trust and tool counts")
    mc_sub.add_parser("list", help="alias for servers")
    mc_add = mc_sub.add_parser("add", help="register a server (nothing runs yet)")
    mc_add.add_argument("name")
    mc_add.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    # dest is not "command": that name belongs to the top-level subcommand and
    # argparse would overwrite it, making the handler lookup fail.
    mc_add.add_argument(
        "--command", dest="server_command", help="stdio: the program to run"
    )
    mc_add.add_argument(
        "--arg",
        action="append",
        default=[],
        metavar="value",
        help="stdio: one argument for the command (repeatable)",
    )
    mc_add.add_argument("--url", help="http: the JSON-RPC endpoint")
    mc_add.add_argument("--env", action="append", default=[], metavar="KEY=value")
    mc_add.add_argument("--header", action="append", default=[], metavar="Name=value")
    mc_add.add_argument(
        "--trust", action="store_true", help="trust it at registration time"
    )
    mc_add.add_argument(
        "--enable", action="store_true", help="enable it at registration time"
    )
    mc_show = mc_sub.add_parser("show", help="one server with its discovered tools")
    mc_show.add_argument("server")
    for verb, text in (
        ("enable", "let a trusted server register its tools"),
        ("disable", "unregister a server's tools"),
        ("trust", "accept what the server advertises"),
        ("untrust", "stop accepting it (tools are unregistered)"),
    ):
        sub_verb = mc_sub.add_parser(verb, help=text)
        sub_verb.add_argument("server")
    mc_remove = mc_sub.add_parser("remove", help="remove a server and its tools")
    mc_remove.add_argument("server")
    mc_sync = mc_sub.add_parser(
        "sync", help="connect, discover tools and register them if allowed"
    )
    mc_sync.add_argument("server")
    mc_tools = mc_sub.add_parser("tools", help="tools discovered from a server")
    mc_tools.add_argument("server")
    mc_call = mc_sub.add_parser(
        "call", help="call a discovered tool (needs an mcp.call grant)"
    )
    mc_call.add_argument("server")
    mc_call.add_argument("tool")
    mc_call.add_argument("--arg", action="append", default=[], metavar="key=value")
    mc_call.add_argument("--conversation")
    mc_call.add_argument("--task")
    mc_call.add_argument("--project")
    mc_call.add_argument("--purpose")
    mc_serve = mc_sub.add_parser(
        "serve", help="expose a whitelist of tools as an MCP server"
    )
    mc_serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    mc_serve.add_argument("--token-env", help="environment variable containing the MCP HTTP bearer token")
    mc_serve.add_argument("--host")
    mc_serve.add_argument("--port", type=int)


def cmd_mcp(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.mcp
        command = getattr(args, "mcp_command", None)
        if command in ("servers", "list"):
            rows = manager.status()
            if args.json:
                emit_json(rows)
            else:
                if not rows:
                    emit("no MCP servers configured")
                else:
                    emit(
                        table(
                            [
                                [
                                    r["name"],
                                    r["transport"],
                                    "yes" if r["trusted"] else "no",
                                    "yes" if r["enabled"] else "no",
                                    r["tools"],
                                    r["registered"],
                                    r["last_status"] or "-",
                                ]
                                for r in rows
                            ],
                            [
                                "server",
                                "transport",
                                "trusted",
                                "enabled",
                                "tools",
                                "callable",
                                "status",
                            ],
                        )
                    )
                    emit("")
                    emit(
                        "a discovered tool only becomes callable when the server is trusted AND enabled,"
                        " and every call still needs an mcp.call grant"
                    )
            return EXIT_OK
        if command == "add":
            server = manager.add_server(
                args.name,
                transport=args.transport,
                command=args.server_command,
                args=list(args.arg or []),
                url=args.url,
                env=_pairs(args.env, flag="--env"),
                headers=_pairs(args.header, flag="--header"),
                enabled=args.enable,
                trusted=args.trust,
            )
            if args.json:
                emit_json(server.to_dict())
            else:
                emit(
                    f"added MCP server {server.name} ({server.transport}) id {server.id}"
                )
                emit(f"  trusted={server.trusted} enabled={server.enabled}")
                emit(f"  next: archx-agent mcp sync {server.name}")
            return EXIT_OK
        if command == "show":
            server = manager.server(args.server)
            data = server.to_dict()
            data["tools"] = manager.tools_of(server.id)
            emit_json(data) if args.json else emit(json_text(data))
            return EXIT_OK
        if command in ("enable", "disable"):
            server = manager.enable(args.server, enabled=command == "enable")
            emit_json(server.to_dict()) if args.json else emit(
                f"{server.name}: enabled={server.enabled}"
                + (
                    ""
                    if server.enabled and server.trusted
                    else " (no tools are callable until it is trusted too)"
                )
            )
            return EXIT_OK
        if command in ("trust", "untrust"):
            server = manager.trust(args.server, trusted=command == "trust")
            if args.json:
                emit_json(server.to_dict())
            else:
                emit(f"{server.name}: trusted={server.trusted}")
                if not server.trusted:
                    emit("its tools were unregistered; nothing it advertises can run")
            return EXIT_OK
        if command == "remove":
            server = manager.remove_server(args.server)
            emit_json(server.to_dict()) if args.json else emit(
                f"removed MCP server {server.name}"
            )
            return EXIT_OK
        if command == "sync":
            try:
                result = manager.sync(args.server)
            except ArchxError as exc:
                return fail(exc.message, EXIT_UNAVAILABLE)
            if args.json:
                emit_json(result)
            else:
                emit(
                    f"{result['server']}: protocol {result['protocol_version']} "
                    f"({result['server_info'].get('name', '?')})"
                )
                emit(f"discovered {len(result['discovered'])} tool(s)")
                for tool in result["discovered"]:
                    emit(f"  - {tool['name']:<20} {tool['description'][:50]}")
                if result["registered"]:
                    emit(
                        f"registered {len(result['registered'])} callable tool(s): "
                        + ", ".join(result["registered"])
                    )
                else:
                    emit(f"nothing registered: {result['reason']}")
            return EXIT_OK
        if command == "tools":
            rows = manager.tools_of(args.server)
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
            ) if rows else emit(
                "no tools discovered (run `archx-agent mcp sync <server>`)"
            )
            return EXIT_OK
        if command == "call":
            arguments = _parse_tool_args(args.arg)
            server = manager.server(args.server)
            discovered = {row["name"] for row in manager.tools_of(server.id)}
            if args.tool not in discovered:
                return fail(
                    f"{server.name} does not expose {args.tool!r} "
                    f"(discovered: {', '.join(sorted(discovered)) or 'nothing - run mcp sync'})",
                    EXIT_USAGE,
                )
            name = manager.registered_tool_name(args.server, args.tool)
            return _execute_tool(ws, ws.tools, name, arguments, args)
        if command == "serve":
            from archx_agent.interfaces.mcp_server import ArchxMcpServer

            try:
                server = ArchxMcpServer(ws)
            except ArchxError as exc:
                return fail(exc.message, EXIT_USAGE)
            if args.transport == "stdio":
                print("serving MCP over stdio (pid %d)" % os.getpid(), file=sys.stderr)
                server.serve_stdio()
                return EXIT_OK
            host = args.host if args.host is not None else ws.config.get("mcp.server_host")
            port = args.port if args.port is not None else int(ws.config.get("mcp.server_port"))
            token = None
            if args.token_env:
                token = os.environ.get(args.token_env)
                if not token:
                    return fail("MCP token environment variable is missing or empty", EXIT_USAGE)
            httpd = server.serve_http(host=host, port=port, token=token)
            print(
                f"serving MCP over http on {host}:{httpd.server_port}",
                file=sys.stderr,
            )
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                httpd.server_close()
            return EXIT_OK
    return EXIT_USAGE
