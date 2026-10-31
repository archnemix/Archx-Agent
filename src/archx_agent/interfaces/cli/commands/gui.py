"""Gui command: argument registration and execution."""

from __future__ import annotations

import argparse


import json


import sys


from archx_agent.interfaces.cli.support import (
    emit,
    table,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_USAGE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    gui = sub.add_parser("gui", help="the local web GUI (a client of this same app)")
    gui_sub = gui.add_subparsers(dest="gui_command", required=True)
    gui_serve = gui_sub.add_parser("serve", help="serve the GUI and print its token")
    gui_serve.add_argument(
        "--host", default=None, help="bind address (default gui.host)"
    )
    gui_serve.add_argument(
        "--port", type=int, default=None, help="port (0 picks a free one)"
    )
    gui_serve.add_argument(
        "--allow-remote",
        action="store_true",
        help="allow a non-loopback bind (the token becomes the only boundary)",
    )
    gui_serve.add_argument(
        "--token", default=None, help="use a specific token instead of a random one"
    )
    gui_serve.add_argument(
        "--open",
        dest="open_browser",
        action="store_true",
        default=None,
        help="open the URL in a browser",
    )
    gui_serve.add_argument(
        "--no-open",
        dest="open_browser",
        action="store_false",
        help="never open a browser",
    )
    gui_sub.add_parser("routes", help="list every endpoint the GUI serves")


def cmd_gui(args: argparse.Namespace) -> int:
    """`gui serve` / `gui routes`."""
    from archx_agent.interfaces.gui.server import GuiApi, GuiServer

    if args.gui_command == "routes":
        with _workspace(args) as ws:
            api = GuiApi(ws, token="inspection-only")
            rows = [
                [definition.method, definition.pattern.pattern, definition.doc]
                for definition in api.routes()
            ]
            if args.json:
                emit(
                    json.dumps(
                        [{"method": m, "path": p, "doc": d} for m, p, d in rows],
                        indent=2,
                    )
                )
            else:
                emit(table(rows, ["method", "path", "what it does"]))
        return EXIT_OK

    with _workspace(args) as ws:
        host = args.host or str(ws.config.get("gui.host"))
        port = args.port if args.port is not None else int(ws.config.get("gui.port"))
        allow_remote = bool(args.allow_remote or ws.config.get("gui.allow_remote"))
        loopback = host in {"127.0.0.1", "::1", "localhost"}
        if not loopback and not allow_remote:
            return fail(
                f"refusing to bind {host!r}: pass --allow-remote if you mean it "
                "(the token is then the only boundary between the network and your data)",
                EXIT_USAGE,
            )
        api = GuiApi(
            ws,
            token=args.token,
            token_ttl_minutes=int(ws.config.get("gui.session_minutes")),
            allow_remote=allow_remote,
            max_body_bytes=int(ws.config.get("gui.max_body_bytes")),
        )
        server = GuiServer(api, host=host, port=int(port))
        open_browser = (
            ws.config.get("gui.open_browser")
            if args.open_browser is None
            else args.open_browser
        )
        emit(f"Archx GUI on {server.url}")
        emit(f"  home      {ws.config.home}")
        emit(
            f"  bind      {host}:{server.port}{'  (remote bind allowed)' if allow_remote else '  (loopback only)'}"
        )
        emit(f"  access token: {api.token}")
        emit(f"  open      {server.token_url}")
        emit("")
        emit(
            "The token is this process's only key: anyone with it can act as you in this app."
        )
        emit(
            "Writes from a browser need the session cookie, which only this page can obtain."
        )
        emit("Press Ctrl-C to stop.")
        # stdout is a pipe when this runs under a script or a test; without a flush the
        # banner (and the token) is invisible until the process exits.
        sys.stdout.flush()
        if open_browser:
            import threading as _threading
            import webbrowser

            _threading.Timer(0.4, lambda: webbrowser.open(server.token_url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            emit("")
            emit("stopped")
        finally:
            server.stop()
    return EXIT_OK
