"""Models CLI: routing operations."""

from __future__ import annotations

from archx_agent.helpers.exceptions import ArchxError, ModelNotFoundError
from archx_agent.interfaces.cli.support import emit, emit_json, table, fail, EXIT_OK, EXIT_USAGE, EXIT_UNAVAILABLE, EXIT_DEGRADED


def handle_route(args, ws, command):
    required = args.require or None
    try:
        decision = ws.route_model(
            task=args.task,
            model_id=args.model,
            required=required,
            allow_unverified=True if args.allow_unverified else None,
            allow_cloud=True if args.allow_cloud else None,
            min_context_tokens=args.min_context,
        )
    except ArchxError as exc:
        return fail(
            exc.message,
            EXIT_UNAVAILABLE
            if isinstance(exc, ModelNotFoundError)
            else EXIT_USAGE,
        )
    data = decision.to_dict()
    if args.json:
        emit_json(data)
    else:
        if decision.chosen is None:
            emit("no eligible model")
        else:
            emit(f"chosen    {decision.chosen.name}  ({decision.chosen.id})")
        emit(f"task      {decision.task}  required={list(decision.required)}")
        emit(f"why       {decision.explanation()}")
        if decision.fallbacks:
            emit("fallbacks " + ", ".join(m.name for m in decision.fallbacks))
        for candidate in decision.candidates:
            if candidate.eligible:
                mark = (
                    "*"
                    if decision.chosen
                    and candidate.model_id == decision.chosen.id
                    else " "
                )
                emit(
                    f"  {mark} {candidate.name:<24} score {candidate.score:6.1f}  eligible"
                )
            else:
                emit(
                    f"    {candidate.name:<24} rejected: {candidate.blockers[0]}"
                )
    return EXIT_OK

def handle_probe(args, ws, command):
    try:
        result = ws.router.probe(args.model, args.capability)
    except ArchxError as exc:
        return fail(exc.message, EXIT_USAGE)
    if args.json:
        emit_json(result)
    else:
        emit(
            f"{result['capability']}: {result['outcome']}  ({result['detail']})"
        )
        emit(f"  latency {result['latency_ms']} ms")
        state = result["state_after"]
        emit(f"  state now {state['state']} ({state['basis']})")
        emit(
            "  this drove the runtime; the result is recorded and the router will use it"
        )
    return EXIT_OK if result["outcome"] == "passed" else EXIT_DEGRADED

def handle_capabilities(args, ws, command):
    if args.model:
        record = ws.models.get(args.model)
        if record.is_err:
            record = ws.models.by_name(args.model)
        if record.is_err:
            return fail(f"no model matches {args.model!r}")
        matrix = ws.models.capability_matrix(record.value.id)
        if args.json:
            emit_json({"model": record.value.name, "capabilities": matrix})
        else:
            emit(f"{record.value.name} ({record.value.id})")
            for capability, state in matrix.items():
                emit(
                    f"  {capability:<14} {state['state']:<12} {state['basis']}"
                )
        return EXIT_OK
    rows = []
    for record in ws.models.list():
        for capability, state in ws.models.capability_matrix(record.id).items():
            rows.append(
                [record.name, capability, state["state"], state["basis"]]
            )
    if args.json:
        emit_json(
            [
                {
                    "model": r[0],
                    "capability": r[1],
                    "state": r[2],
                    "basis": r[3],
                }
                for r in rows
            ]
        )
    else:
        emit(
            table(rows, ["model", "capability", "state", "basis"])
        ) if rows else emit("no models")
    return EXIT_OK
