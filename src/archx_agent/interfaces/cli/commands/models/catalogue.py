"""Models CLI: catalogue operations."""

from __future__ import annotations

from archx_agent.helpers.jsonio import json_text
from archx_agent.interfaces.cli.support import emit, emit_json, table, fail, EXIT_OK


def handle_list(args, ws, command):
    ws.models.refresh_states()
    records = ws.models.list()
    if args.json:
        emit_json([m.to_dict() for m in records])
    else:
        if not records:
            emit("no models configured")
            emit("  local:  archx-agent models discover --dir /path/to/gguf")
            emit(
                "  http:   archx-agent models add-http --name x --base-url http://127.0.0.1:8080 --model y"
            )
            return EXIT_OK
        emit(
            table(
                [
                    [
                        m.name[:28],
                        m.provider,
                        m.runtime,
                        m.state,
                        ",".join(m.verified_capabilities) or "-",
                        f"{m.size_bytes // (1024 * 1024)}MB"
                        if m.size_bytes
                        else "-",
                    ]
                    for m in records
                ],
                ["name", "provider", "runtime", "state", "verified", "size"],
            )
        )
    return EXIT_OK

def handle_discover(args, ws, command):
    found = ws.models.discover_local(args.dir, recursive=not args.no_recursive)
    if args.json:
        emit_json([m.to_dict() for m in found])
    else:
        if not found:
            emit(
                f"no GGUF files found in {args.dir or ws.config.get('paths.models')}"
            )
        for m in found:
            emit(
                f"registered {m.name}  ({m.state}, {m.quantization or 'unknown quant'})"
            )
    return EXIT_OK

def handle_show(args, ws, command):
    record = ws.models.get(args.model)
    if record.is_err:
        record = ws.models.by_name(args.model)
    if record.is_err:
        return fail(f"no model matches {args.model!r}")
    m = record.value
    history = ws.models.capability_history(m.id)
    data = m.to_dict()
    data["capability_tests"] = history
    if args.json:
        emit_json(data)
        return EXIT_OK
    emit(f"{m.name}   ({m.id})")
    emit(f"  provider        {m.provider}")
    emit(f"  runtime         {m.runtime}")
    emit(f"  state           {m.state}")
    emit(f"  path / ref      {m.path or m.model_ref}")
    emit(f"  context         {m.context_length}")
    emit(f"  quantization    {m.quantization or 'unknown'} (claim)")
    emit(f"  verified caps   {', '.join(m.verified_capabilities) or 'none'}")
    emit(f"  verification    {m.verification_state}")
    emit(f"  usage           {m.success_count} ok / {m.failure_count} failed")
    if m.claims:
        emit(f"  claims          {json_text(m.claims)}")
    if m.facts:
        emit(f"  facts           {json_text(m.facts)}")
    if history:
        emit("  capability tests")
        for row in history[:5]:
            emit(f"    {row['capability']}: {row['outcome']} ({row['run_at']})")
    return EXIT_OK

def handle_enable(args, ws, command):
    record = ws.models.get(args.model)
    if record.is_err:
        record = ws.models.by_name(args.model)
    if record.is_err:
        return fail(f"no model matches {args.model!r}")
    updated = ws.models.set_enabled(record.value.id, command == "enable")
    emit(f"{updated.name} is now {updated.state}")
    return EXIT_OK

def handle_verify(args, ws, command):
    record = ws.models.get(args.model)
    if record.is_err:
        record = ws.models.by_name(args.model)
    if record.is_err:
        return fail(f"no model matches {args.model!r}")
    updated = ws.models.set_verified_capabilities(
        record.value.id,
        args.capability,
        basis=args.basis,
        verification_state=args.state,
    )
    emit(
        f"verified capabilities for {updated.name}: {', '.join(updated.verified_capabilities)}"
    )
    return EXIT_OK

def handle_prefer(args, ws, command):
    record = ws.models.get(args.model)
    if record.is_err:
        record = ws.models.by_name(args.model)
    if record.is_err:
        return fail(f"no model matches {args.model!r}")
    updated = ws.models.set_preferred_for(record.value.id, args.task)
    emit(f"{updated.name} preferred for: {', '.join(args.task)}")
    return EXIT_OK

def handle_remove(args, ws, command):
    record = ws.models.get(args.model)
    if record.is_err:
        record = ws.models.by_name(args.model)
    if record.is_err:
        return fail(f"no model matches {args.model!r}")
    ws.models.remove(record.value.id, delete_file=args.delete_file)
    emit(f"removed {record.value.name}")
    return EXIT_OK

def handle_storage(args, ws, command):
    data = ws.models.storage_summary()
    emit_json(data) if args.json else emit(json_text(data))
    return EXIT_OK

def handle_compare(args, ws, command):
    rows = ws.models.compare(args.models)
    if args.json:
        emit_json(rows)
    else:
        emit(
            table(
                [
                    [
                        r["name"],
                        r["provider"],
                        r["state"],
                        r["context_length"],
                        r["verification_state"],
                        f"{r['success_count']}/{r['failure_count']}",
                    ]
                    for r in rows
                ],
                ["name", "provider", "state", "ctx", "verification", "ok/fail"],
            )
        )
    return EXIT_OK
