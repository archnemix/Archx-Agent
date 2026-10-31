"""Chat command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.application.chat import ChatService


from archx_agent.helpers.exceptions import (
    ProviderError,
)


from archx_agent.helpers.jsonio import json_text


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_UNAVAILABLE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    chat = sub.add_parser("chat", help="chat with the configured model")
    chat.add_argument("--message", "-m", help="send one message and exit")
    chat.add_argument("--conversation", "-c", help="conversation id to continue")
    chat.add_argument("--model", help="model id or name")
    chat.add_argument(
        "--strategy",
        choices=["oldest_first", "summarize", "ai_select", "manual", "ai_proposed"],
    )
    chat.add_argument(
        "--manual-ids", help="comma separated message ids for the manual strategy"
    )
    chat.add_argument(
        "--proposal", help="approved proposal id for the ai_proposed strategy"
    )
    chat.add_argument("--system", help="system prompt override")
    chat.add_argument(
        "--stream", action="store_true", help="stream tokens as they arrive"
    )
    chat.add_argument("--temperature", type=float)
    chat.add_argument("--max-tokens", type=int)
    chat.add_argument(
        "--show-context",
        action="store_true",
        help="print the context manifest after replying",
    )


def cmd_chat(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        service = ChatService(ws, ws.context)
        params = None
        if args.temperature is not None or args.max_tokens is not None:
            from archx_agent.adapters.model_runtime import GenerationParams

            params = GenerationParams(
                temperature=args.temperature
                if args.temperature is not None
                else ws.config.get("model.temperature"),
                max_tokens=args.max_tokens
                if args.max_tokens is not None
                else ws.config.get("model.output_budget"),
            )
        manual_ids = [
            x.strip() for x in (args.manual_ids or "").split(",") if x.strip()
        ] or None
        try:
            reply = service.send(
                args.message or "",
                conversation_id=args.conversation,
                model_id=args.model,
                strategy=args.strategy,
                manual_ids=manual_ids,
                approved_proposal_id=args.proposal,
                system_prompt=args.system,
                stream_callback=(lambda piece: print(piece, end="", flush=True))
                if args.stream
                else None,
                params=params,
            )
        except ProviderError as exc:
            return fail(f"{type(exc).__name__}: {exc.message}", EXIT_UNAVAILABLE)
        if args.json:
            emit_json(reply.to_dict())
        else:
            if args.stream:
                emit()
            else:
                emit(reply.text)
            emit()
            emit(
                f"[model {reply.model['name']} ({reply.model['provider']})"
                f"{' SIMULATED' if reply.simulated else ''} | "
                f"{reply.latency_ms:.0f}ms | context {reply.manifest.tokens_used}/{reply.manifest.budget} tokens"
                f" | strategy {reply.manifest.strategy}]"
            )
            for warning in reply.warnings:
                emit(f"[warning] {warning}")
            if args.show_context:
                emit(json_text(reply.manifest.to_dict()))
        return EXIT_OK
