"""Doctor command: argument registration and execution."""

from __future__ import annotations

import argparse


import os


from pathlib import Path


from archx_agent.helpers.config import load_config


from archx_agent.helpers.exceptions import (
    ArchxError,
)


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    _workspace,
    EXIT_OK,
    EXIT_ERROR,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("doctor", help="check the environment and report problems")


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []
    cfg = load_config(home=args.home, config_path=args.config, create=False)
    for key in ("paths.home", "storage.db_path", "storage.events_path"):
        path = Path(cfg.get(key))
        target = path if key != "storage.db_path" else path.parent
        writable = os.access(target if target.exists() else target.parent, os.W_OK)
        checks.append((key, writable, str(target)))
    try:
        with _workspace(args) as ws:
            integrity = ws.store.integrity_check()
            checks.append(
                ("database integrity", integrity == ["ok"], ", ".join(integrity))
            )
            models = ws.models.list()
            checks.append(("model catalogue", bool(models), f"{len(models)} model(s)"))
            usable = [m for m in models if m.is_usable]
            checks.append(
                (
                    "usable models",
                    bool(usable),
                    ", ".join(m.name for m in usable) or "none",
                )
            )
            try:
                record = ws.resolve_model()
                runtime = ws.runtime_for(record)
                health = runtime.health()
                checks.append(("runtime", health.ok, f"{record.name}: {health.detail}"))
            except ArchxError as exc:
                checks.append(("runtime", False, exc.message))
            checks.append(
                (
                    "tracing",
                    ws.events.count() >= 0,
                    f"{ws.events.count()} event(s) at {ws.events.path}",
                )
            )
    except ArchxError as exc:
        checks.append(("workspace", False, exc.message))
    ok = all(passed for _name, passed, _detail in checks)
    if args.json:
        emit_json(
            {
                "ok": ok,
                "checks": [{"check": n, "ok": p, "detail": d} for n, p, d in checks],
            }
        )
    else:
        for name, passed, detail in checks:
            emit(f"[{'ok' if passed else 'FAIL'}] {name}: {detail}")
    return EXIT_OK if ok else EXIT_ERROR
