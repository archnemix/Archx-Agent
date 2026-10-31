"""Config command: argument registration and execution."""

from __future__ import annotations

import argparse


import json


from pathlib import Path


from typing import Any


from archx_agent.helpers.config import list_settings, load_config


from archx_agent.helpers.exceptions import (
    ArchxError,
)


from archx_agent.helpers.jsonio import json_text


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    EXIT_OK,
    EXIT_USAGE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    cfg = sub.add_parser("config", help="inspect and edit settings")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)
    cfg_sub.add_parser("list", help="list every setting with defaults")
    cfg_get = cfg_sub.add_parser("get", help="read a setting")
    cfg_get.add_argument("key")
    cfg_set = cfg_sub.add_parser("set", help="change a setting")
    cfg_set.add_argument("key")
    cfg_set.add_argument("value")
    cfg_sub.add_parser("show", help="show the resolved configuration and provenance")


def cmd_config(args: argparse.Namespace) -> int:
    cfg = load_config(home=args.home, config_path=args.config, create=False)
    if args.config_command == "list":
        rows = list_settings()
        if args.json:
            emit_json(rows)
        else:
            emit(
                table(
                    [
                        [
                            r["key"],
                            r["type"],
                            str(r["default"])[:30],
                            r["description"][:60],
                        ]
                        for r in rows
                    ],
                    ["setting", "type", "default", "description"],
                )
            )
        return EXIT_OK
    if args.config_command == "get":
        value = cfg.get(args.key)
        emit_json(
            {"key": args.key, "value": value, "source": cfg.provenance.get(args.key)}
        ) if args.json else emit(
            f"{args.key} = {value}  (source: {cfg.provenance.get(args.key)})"
        )
        return EXIT_OK
    if args.config_command == "set":
        raw: Any = args.value
        expected = {row["key"]: row["type"] for row in list_settings()}.get(args.key)
        if expected == "list":
            # Accept both a JSON array and a comma-separated list; a JSON string that is
            # not an array is almost always a quoting mistake, so say so.
            text = args.value.strip()
            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    return fail(
                        f"{args.key} is a list; that is not valid JSON: {exc}",
                        EXIT_USAGE,
                    )
                if not isinstance(parsed, list):
                    return fail(
                        f"{args.key} expects a list, got {type(parsed).__name__}",
                        EXIT_USAGE,
                    )
                raw = parsed
            else:
                raw = [part.strip() for part in text.split(",") if part.strip()]
        try:
            cfg.set(args.key, raw, source="cli")
        except ArchxError as exc:
            return fail(f"{args.key}: {exc.message}", EXIT_USAGE)
        path = Path(args.config) if args.config else cfg.home / "config.json"
        existing = {}
        if path.exists():
            existing = json.loads(path.read_text()).get("settings", {})
        existing[args.key] = cfg.get(args.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json_text({"version": cfg.version, "settings": existing}) + "\n"
        )
        emit(f"set {args.key} = {cfg.get(args.key)} in {path}")
        return EXIT_OK
    emit_json(cfg.to_dict()) if args.json else emit(json_text(cfg.to_dict()))
    return EXIT_OK
