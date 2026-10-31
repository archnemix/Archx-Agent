"""CLI entry point and command dispatch. Command implementations live in commands/."""

from __future__ import annotations


import sys


from typing import Sequence


from archx_agent.helpers.exceptions import (
    ArchxError,
    ValidationError,
)


from archx_agent.interfaces.cli.support import fail, EXIT_OK, EXIT_USAGE

from archx_agent.interfaces.cli.parser import build_parser
from archx_agent.interfaces.cli.commands.init import cmd_init
from archx_agent.interfaces.cli.commands.info import cmd_info
from archx_agent.interfaces.cli.commands.doctor import cmd_doctor
from archx_agent.interfaces.cli.commands.config import cmd_config
from archx_agent.interfaces.cli.commands.models import cmd_models
from archx_agent.interfaces.cli.commands.chat import cmd_chat
from archx_agent.interfaces.cli.commands.conv import cmd_conv
from archx_agent.interfaces.cli.commands.memory import cmd_memory
from archx_agent.interfaces.cli.commands.projects import cmd_projects
from archx_agent.interfaces.cli.commands.providers import cmd_providers
from archx_agent.interfaces.cli.commands.context import cmd_context
from archx_agent.interfaces.cli.commands.embeddings import cmd_embeddings
from archx_agent.interfaces.cli.commands.eval import cmd_eval
from archx_agent.interfaces.cli.commands.tools import cmd_tools
from archx_agent.interfaces.cli.commands.permissions import cmd_permissions
from archx_agent.interfaces.cli.commands.approvals import cmd_approvals
from archx_agent.interfaces.cli.commands.mcp import cmd_mcp
from archx_agent.interfaces.cli.commands.extensions import cmd_extensions
from archx_agent.interfaces.cli.commands.agent import cmd_agent
from archx_agent.interfaces.cli.commands.jobs import cmd_jobs
from archx_agent.interfaces.cli.commands.search import cmd_search
from archx_agent.interfaces.cli.commands.code import cmd_code
from archx_agent.interfaces.cli.commands.experiment import cmd_experiment
from archx_agent.interfaces.cli.commands.play import cmd_play
from archx_agent.interfaces.cli.commands.voice import cmd_voice
from archx_agent.interfaces.cli.commands.dataset import cmd_dataset
from archx_agent.interfaces.cli.commands.training import cmd_training
from archx_agent.interfaces.cli.commands.remote import cmd_remote
from archx_agent.interfaces.cli.commands.automation import cmd_automation
from archx_agent.interfaces.cli.commands.scene import cmd_scene
from archx_agent.interfaces.cli.commands.exec import cmd_exec
from archx_agent.interfaces.cli.commands.gui import cmd_gui
from archx_agent.interfaces.cli.commands.research import cmd_research
from archx_agent.interfaces.cli.commands.learning import cmd_learning
from archx_agent.interfaces.cli.commands.simple import cmd_simple
from archx_agent.interfaces.cli.commands.tasks import cmd_tasks
from archx_agent.interfaces.cli.commands.versions import cmd_versions
from archx_agent.interfaces.cli.commands.db import cmd_db
from archx_agent.interfaces.cli.commands.trace import cmd_trace

HANDLERS = {
    "init": cmd_init,
    "info": cmd_info,
    "doctor": cmd_doctor,
    "config": cmd_config,
    "models": cmd_models,
    "chat": cmd_chat,
    "conv": cmd_conv,
    "memory": cmd_memory,
    "projects": cmd_projects,
    "providers": cmd_providers,
    "context": cmd_context,
    "embeddings": cmd_embeddings,
    "tools": cmd_tools,
    "permissions": cmd_permissions,
    "approvals": cmd_approvals,
    "mcp": cmd_mcp,
    "extensions": cmd_extensions,
    "agent": cmd_agent,
    "jobs": cmd_jobs,
    "search": cmd_search,
    "simple": cmd_simple,
    "research": cmd_research,
    "learning": cmd_learning,
    "code": cmd_code,
    "experiment": cmd_experiment,
    "play": cmd_play,
    "voice": cmd_voice,
    "dataset": cmd_dataset,
    "train": cmd_training,
    "remote": cmd_remote,
    "exec": cmd_exec,
    "scene": cmd_scene,
    "automation": cmd_automation,
    "gui": cmd_gui,
    "tasks": cmd_tasks,
    "versions": cmd_versions,
    "eval": cmd_eval,
    "db": cmd_db,
    "trace": cmd_trace,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = HANDLERS.get(args.command)
    if handler is None:  # pragma: no cover - argparse enforces choices
        parser.print_help()
        return EXIT_USAGE
    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except ValidationError as exc:
        return fail(exc.message, EXIT_USAGE)
    except ArchxError as exc:
        return fail(f"{type(exc).__name__}: {exc.message}")
    except BrokenPipeError:  # pragma: no cover
        return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
