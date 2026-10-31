"""Simple command: argument registration and execution."""

from __future__ import annotations

import argparse


import sys


from archx_agent import BRAND


from archx_agent.helpers.exceptions import (
    ArchxError,
    ValidationError,
)


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_USAGE,
    EXIT_DENIED,
    EXIT_UNAVAILABLE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    simple = sub.add_parser(
        "simple", help="Simple Mode: ask in plain language (no subcommand = chat loop)"
    )
    sm_sub = simple.add_subparsers(dest="simple_command")
    sm_ask = sm_sub.add_parser(
        "ask", help="ask one question and see what was done and why"
    )
    sm_ask.add_argument("text")
    sm_ask.add_argument("--model")
    sm_ask.add_argument("--conversation")
    sm_sub.add_parser("status", help="model, memory, tasks and queue in plain language")
    sm_sub.add_parser("help", help="what Simple Mode understands")


def cmd_simple(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        if ws.simple is None:
            return fail(
                "Simple Mode is not available in this workspace", EXIT_UNAVAILABLE
            )
        command = getattr(args, "simple_command", None)
        if command == "status":
            result = ws.simple.status()
        elif command == "help":
            result = ws.simple.help()
        elif command == "ask":
            try:
                result = ws.simple.ask(
                    args.text,
                    model_id=getattr(args, "model", None),
                    conversation_id=getattr(args, "conversation", None),
                )
            except ArchxError as exc:
                code = EXIT_USAGE if isinstance(exc, ValidationError) else EXIT_ERROR
                return fail(getattr(exc, "message", str(exc)), code)
        else:
            return _simple_loop(ws, args)
        if args.json:
            emit_json(result.to_dict())
        else:
            _render_simple(result)
        if result.data.get("approval_id"):
            return EXIT_DENIED
        return EXIT_OK


def _render_simple(result) -> None:
    emit(result.headline)
    if result.detail:
        for line in result.detail.splitlines():
            emit(f"  {line}" if not line.startswith(" ") else line)
    if result.next_step:
        emit("")
        emit(f"next: {result.next_step}")
    emit("")
    emit(f"(why: {result.why})")


def _simple_loop(ws, args: argparse.Namespace) -> int:
    """A small REPL. Chat keeps one conversation; every line is explained."""
    if args.json:
        return fail("--json needs a subcommand (ask/status/help)", EXIT_USAGE)
    conversation_id = None
    emit(f"{BRAND} Simple Mode - type /help for what I understand, /quit to leave.")
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            emit("")
            return EXIT_OK
        line = line.strip()
        if not line:
            continue
        if line in {"/quit", "/exit", "quit", "exit"}:
            return EXIT_OK
        try:
            result = ws.simple.ask(line, conversation_id=conversation_id)
        except ValidationError as exc:
            print(f"error: {exc.message}", file=sys.stderr)
            continue
        except ArchxError as exc:
            print(f"error: {exc.message}", file=sys.stderr)
            continue
        if result.intent == "quit":
            return EXIT_OK
        if result.data.get("conversation_id"):
            conversation_id = result.data["conversation_id"]
        _render_simple(result)
