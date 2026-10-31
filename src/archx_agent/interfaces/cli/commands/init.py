"""Init command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent import BRAND


from archx_agent.application.workspace import open_workspace


from archx_agent.helpers.config import load_config


from archx_agent.interfaces.cli.support import emit, emit_json, EXIT_OK


def register_parser(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("init", help="create the home directory, config and database")


def cmd_init(args: argparse.Namespace) -> int:
    cfg = load_config(home=args.home, config_path=args.config, create=False)
    with open_workspace(home=args.home, config_path=args.config) as ws:
        cfg = ws.config
        found = ws.models.discover_local()
        data = {
            "home": str(cfg.home),
            "database": str(ws.store.path),
            "events": str(ws.events.path),
            "config": str(cfg.source_file or (cfg.home / "config.json")),
            "schema_version": ws.store.schema_version(),
            "models_discovered": [m.name for m in found],
            "warnings": ws.warnings,
        }
        if args.json:
            emit_json(data)
        else:
            emit(f"{BRAND} initialised")
            emit(f"  home       {data['home']}")
            emit(f"  database   {data['database']}")
            emit(f"  traces     {data['events']}")
            emit(f"  config     {data['config']}")
            emit(f"  schema     v{data['schema_version']}")
            if found:
                emit(
                    f"  models     discovered {len(found)}: {', '.join(m.name for m in found)}"
                )
            else:
                emit("  models     none found in the models directory")
                emit("             add one with: archx-agent models add-http ...")
            for warning in ws.warnings:
                emit(f"  warning    {warning}")
    return EXIT_OK
