"""Open one workspace and dispatch learning subcommands."""

from __future__ import annotations

import argparse
from archx_agent.interfaces.cli.support import fail, _workspace, EXIT_USAGE, EXIT_UNAVAILABLE

from .goals import handle_goal
from .items import handle_item
from .goals import handle_plan
from .items import handle_next
from .items import handle_ask
from .items import handle_hint
from .items import handle_answer
from .sessions import handle_session
from .sessions import handle_review
from .reporting import handle_stats
from .reporting import handle_search
from .reporting import handle_report

HANDLERS = {'goal': handle_goal, 'item': handle_item, 'plan': handle_plan, 'next': handle_next, 'ask': handle_ask, 'hint': handle_hint, 'answer': handle_answer, 'session': handle_session, 'review': handle_review, 'stats': handle_stats, 'search': handle_search, 'report': handle_report}

def cmd_learning(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        if ws.learning is None:
            return fail(
                "Learning Mode is not available in this workspace", EXIT_UNAVAILABLE
            )
        manager, tutor = ws.learning, ws.tutor
        command = args.learning_command
        handler = HANDLERS.get(command)
        if handler is not None:
            result = handler(args, ws, command, manager, tutor)
            if result is not None:
                return result
    return fail(f"unknown learning command {command!r}", EXIT_USAGE)
