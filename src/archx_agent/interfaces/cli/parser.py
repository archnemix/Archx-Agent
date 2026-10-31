"""Build the command tree; each command owns its arguments and handler."""

from __future__ import annotations

import argparse


import textwrap


from archx_agent import BRAND, __version__


from archx_agent.interfaces.cli.commands import (
    init,
    info,
    doctor,
    config,
    models,
    chat,
    conv,
    memory,
    projects,
    providers,
    context,
    embeddings,
    eval,
    tools,
    permissions,
    approvals,
    mcp,
    extensions,
    agent,
    jobs,
    search,
    code,
    experiment,
    play,
    voice,
    dataset,
    training,
    remote,
    automation,
    scene,
    exec,
    gui,
    research,
    learning,
    simple,
    tasks,
    versions,
    db,
    trace,
)


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    """Let ``--json``/``--home`` also be written after the subcommand.

    Users type ``archx-agent memory list --json`` far more often than the global
    form, and argparse would otherwise reject it. ``SUPPRESS`` defaults mean an
    unset subparser flag does not clobber the value parsed at the top level.
    """
    existing = {opt for action in parser._actions for opt in action.option_strings}  # noqa: SLF001

    def add(flags: list[str], **kwargs) -> None:
        if not any(flag in existing for flag in flags):
            parser.add_argument(*flags, **kwargs)

    add(
        ["--json"],
        action="store_true",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    add(["--home"], default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    add(["--config"], default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    add(
        ["--allow-simulated"],
        action="store_true",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )


def _add_leaf_flags(parser: argparse.ArgumentParser) -> None:
    """Accept global flags at every subcommand depth without overwriting earlier values."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                _add_global_flags(child)
                _add_leaf_flags(child)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archx-agent",
        description=f"{BRAND} - a modular, local-first AI operating environment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            examples:
              archx-agent init
              archx-agent models add-http --name local-llama --base-url http://127.0.0.1:8080 --model smollm2
              archx-agent chat --message "hello"
              archx-agent memory add --kind permanent --title "Prefers metric" --content "Use metric units" --category preference
              archx-agent memory search python
              archx-agent trace list --limit 20
            """
        ),
    )
    parser.add_argument("--version", action="version", version=f"{BRAND} {__version__}")
    parser.add_argument(
        "--home", help="Archx home directory (default ~/.archx or $ARCHX_PATHS_HOME)"
    )
    parser.add_argument("--config", help="configuration file to load")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--allow-simulated",
        action="store_true",
        help="allow the simulated test-double runtime (never a substitute for a real model)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init.register_parser(sub)
    info.register_parser(sub)
    doctor.register_parser(sub)
    config.register_parser(sub)
    models.register_parser(sub)
    chat.register_parser(sub)
    conv.register_parser(sub)
    memory.register_parser(sub)
    projects.register_parser(sub)
    providers.register_parser(sub)
    context.register_parser(sub)
    embeddings.register_parser(sub)
    eval.register_parser(sub)
    tools.register_parser(sub)
    permissions.register_parser(sub)
    approvals.register_parser(sub)
    mcp.register_parser(sub)
    extensions.register_parser(sub)
    agent.register_parser(sub)
    jobs.register_parser(sub)
    search.register_parser(sub)
    code.register_parser(sub)
    experiment.register_parser(sub)
    play.register_parser(sub)
    voice.register_parser(sub)
    dataset.register_parser(sub)
    training.register_parser(sub)
    remote.register_parser(sub)
    automation.register_parser(sub)
    scene.register_parser(sub)
    exec.register_parser(sub)
    gui.register_parser(sub)
    research.register_parser(sub)
    learning.register_parser(sub)
    simple.register_parser(sub)
    tasks.register_parser(sub)
    versions.register_parser(sub)
    db.register_parser(sub)
    trace.register_parser(sub)
    _add_leaf_flags(parser)
    return parser
