"""Eval command: argument registration and execution."""

from __future__ import annotations

import argparse


from pathlib import Path


from archx_agent.application.workspace import open_workspace


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_USAGE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    ev = sub.add_parser("eval", help="evaluations")
    ev_sub = ev.add_subparsers(dest="eval_command", required=True)
    ev_ret = ev_sub.add_parser(
        "retrieval", help="score retrieval modes against a labelled test set"
    )
    ev_ret.add_argument("--dataset", default="data/retrieval_set.json")
    ev_ret.add_argument("--k", type=int, default=5)
    ev_ret.add_argument("--out", help="write a markdown report here")
    ev_ret.add_argument(
        "--no-scratch",
        action="store_true",
        help="use this workspace instead of a temporary scratch workspace",
    )


def cmd_eval(args: argparse.Namespace) -> int:
    from archx_agent.application.retrieval_eval import (
        load_dataset,
        render_markdown,
        run_evaluation,
    )

    if args.eval_command != "retrieval":
        return EXIT_USAGE
    dataset_path = args.dataset
    if not Path(dataset_path).exists():
        candidate = Path(__file__).resolve().parents[4] / dataset_path
        if candidate.exists():
            dataset_path = str(candidate)
        else:
            return fail(f"dataset not found: {args.dataset}")
    dataset = load_dataset(dataset_path)
    if args.no_scratch:
        with _workspace(args) as ws:
            report = run_evaluation(
                dataset, memory=ws.memory, embeddings=ws.embeddings, k=args.k
            )
    else:
        import tempfile

        scratch = tempfile.mkdtemp(prefix="archx-eval-")
        overrides = {
            "memory.embeddings_enabled": True,
            "memory.embedding_provider": "local-hash",
        }
        with open_workspace(home=scratch, overrides=overrides) as ws:
            report = run_evaluation(
                dataset, memory=ws.memory, embeddings=ws.embeddings, k=args.k
            )
        report["scratch_home"] = scratch
    report["dataset_path"] = dataset_path
    markdown = render_markdown(report)
    if args.out:
        Path(args.out).write_text(markdown + "\n")
        emit(f"wrote {args.out}")
    if args.json:
        emit_json(report)
    else:
        emit(markdown)
    return EXIT_OK
