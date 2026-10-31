"""Embeddings command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.helpers.jsonio import json_text


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_UNAVAILABLE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    emb = sub.add_parser("embeddings", help="embedding index and semantic search")
    e_sub = emb.add_subparsers(dest="embedding_command", required=True)
    e_sub.add_parser("status", help="provider, dimension and coverage")
    e_backfill = e_sub.add_parser(
        "backfill", help="embed memories and messages missing a vector"
    )
    e_backfill.add_argument("--limit", type=int, default=500)
    e_conv = e_sub.add_parser(
        "embed-conversation", help="embed a conversation's messages"
    )
    e_conv.add_argument("conversation")
    e_search = e_sub.add_parser("search", help="semantic search over memory")
    e_search.add_argument("query")
    e_search.add_argument("-k", type=int, default=5)
    e_search.add_argument("--threshold", type=float)
    e_purge = e_sub.add_parser("purge", help="delete vectors (all, or one model's)")
    e_purge.add_argument("--model")
    e_purge.add_argument("--yes", action="store_true")


def cmd_embeddings(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.embeddings
        if manager is None:
            return fail("no embedding subsystem is configured", EXIT_UNAVAILABLE)
        command = args.embedding_command
        if command == "status":
            data = manager.status()
            data["memory"] = ws.memory.stats()["embedding_states"]
            data["enabled"] = data.get("provider") is not None
            data["hint"] = (
                "enable with: archx-agent config set memory.embeddings_enabled true"
                if not data["enabled"]
                else "disable with: archx-agent config set memory.embeddings_enabled false"
            )
            if args.json:
                emit_json(data)
            else:
                provider = data["provider"]
                if provider is None:
                    emit("embedding provider: none configured")
                    emit(
                        "  enable with: archx-agent config set memory.embeddings_enabled true"
                    )
                    emit(
                        "  (local-hash is the offline default; it is lexical, not semantic)"
                    )
                else:
                    emit(
                        f"provider {provider['id']} model={provider['model_id']} dim={provider['dim']} "
                        f"semantic={provider['semantic']} local={provider['local']}"
                    )
                emit(f"states           {data['states']}")
                emit(f"stale vectors    {data['stale_vectors']}")
                emit(f"threshold        {data['threshold']}")
            return EXIT_OK
        if command == "backfill":
            result = manager.backfill(limit=args.limit)
            emit_json(result) if args.json else emit(json_text(result))
            return EXIT_OK
        if command == "embed-conversation":
            result = manager.embed_conversation(args.conversation)
            emit_json(result) if args.json else emit(json_text(result))
            return EXIT_OK
        if command == "search":
            if manager.provider is None:
                return fail(
                    "embedding search needs a provider; embeddings are disabled "
                    "(enable with: archx-agent config set memory.embeddings_enabled true)",
                    EXIT_UNAVAILABLE,
                )
            found = manager.search(
                args.query, owner_types=("memory",), k=args.k, threshold=args.threshold
            )
            if args.json:
                emit_json(
                    {
                        "degraded": found.degraded,
                        "degraded_reason": found.degraded_reason,
                        "model_id": found.model_id,
                        "scanned": found.scanned,
                        "results": [n.to_dict() for n in found.neighbours],
                    }
                )
            else:
                if found.degraded:
                    emit(f"[degraded] {found.degraded_reason}")
                emit(
                    f"scanned {found.scanned} vector(s) with {found.model_id or 'no model'}"
                )
                for neighbour in found.neighbours:
                    memory = ws.memory.get(neighbour.owner_id)
                    title = memory.value.title if memory.is_ok else "(missing)"
                    emit(f"  {neighbour.score:.3f}  {title[:60]}  {neighbour.owner_id}")
            return EXIT_OK
        if command == "purge":
            if not args.yes:
                return fail(
                    "purging vectors is irreversible; re-run with --yes", EXIT_USAGE
                )
            removed = manager.purge(model_id=args.model)
            payload = {"deleted": removed, "model_id": args.model}
            emit_json(payload) if args.json else emit(f"removed {removed} vector(s)")
            return EXIT_OK
    return EXIT_USAGE
