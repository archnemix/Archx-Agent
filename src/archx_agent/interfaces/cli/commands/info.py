"""Info command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent import BRAND, __version__


from archx_agent.interfaces.cli.support import emit, emit_json, _workspace, EXIT_OK


def register_parser(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("info", help="show workspace information")


def cmd_info(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        data = ws.info()
        data["memory"] = ws.memory.stats()
        data["models"] = [m.name for m in ws.models.list()]
        if args.json:
            emit_json(data)
        else:
            emit(f"{BRAND} {__version__}")
            emit(f"  home            {data['home']}")
            emit(f"  database        {data['database']}")
            emit(f"  trace database  {data['events']}")
            emit(
                f"  schema          v{data['schema_version']} (expected v{data['expected_schema_version']})"
            )
            emit(f"  conversations   {data['conversations']}")
            emit(f"  memories        {data['memories']}")
            emit(f"  models          {', '.join(data['models']) or 'none configured'}")
            for warning in data["warnings"]:
                emit(f"  warning         {warning}")
    return EXIT_OK
