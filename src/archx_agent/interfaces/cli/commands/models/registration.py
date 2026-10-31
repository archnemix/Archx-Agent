"""Models CLI: registration operations."""

from __future__ import annotations

from archx_agent.helpers.exceptions import ArchxError
from archx_agent.interfaces.cli.support import emit, emit_json, fail, _is_loopback, EXIT_OK, EXIT_USAGE


def handle_add_http(args, ws, command):
    record = ws.models.register_remote(
        args.name,
        provider=args.provider
        or ("local-http" if _is_loopback(args.base_url) else "remote-http"),
        runtime="openai-http",
        model_ref=args.model,
        base_url=args.base_url,
        context_length=args.context_length,
        capabilities=args.capability or ["chat"],
        verification=args.verification,
    )
    if args.credential_ref:
        metadata = dict(record.user_metadata)
        metadata["credential_ref"] = args.credential_ref
        record = ws.models.update(record.id, user_metadata=metadata)
    emit(
        f"registered {record.name} ({record.id}) provider={record.provider} runtime={record.runtime}"
    )
    emit(f"  endpoint {args.base_url}")
    emit(
        "  note: capabilities are claims until verified with `archx-agent models verify`"
    )
    return EXIT_OK

def handle_sdks(args, ws, command):
    from archx_agent.adapters.sdk_transport import SDKS, sdk_available
    for key, spec in SDKS.items():
        ok, why = sdk_available(key)
        if args.json:
            continue
        emit(
            f"{key:10s} {spec.label:16s} {'installed' if ok else 'MISSING':10s} "
            f"{spec.package:14s} key from {spec.env_var}"
        )
        if not ok:
            emit(f"           {why}")
    if args.json:
        emit_json(
            {
                key: {
                    "installed": sdk_available(key)[0],
                    "package": spec.package,
                    "env_var": spec.env_var,
                    "base_url": spec.default_base_url,
                }
                for key, spec in SDKS.items()
            }
        )
    return EXIT_OK

def handle_add_sdk(args, ws, command):
    from archx_agent.adapters.sdk_transport import SDKS, sdk_available
    if args.sdk not in SDKS:
        return fail(
            f"unknown SDK {args.sdk!r} (known: {', '.join(sorted(SDKS))})",
            EXIT_USAGE,
        )
    try:
        record = ws.register_sdk(
            args.name,
            sdk=args.sdk,
            model_ref=args.model,
            base_url=args.base_url,
            credential_ref=args.credential_ref,
            context_length=args.context_length,
            capabilities=args.capability or ["chat"],
            verification=args.verification,
        )
    except ArchxError as exc:
        return fail(exc.message, EXIT_USAGE)
    spec = SDKS[args.sdk]
    emit(
        f"registered {record.name} ({record.id}) provider={record.provider} runtime={record.runtime}"
    )
    emit(f"  sdk      {spec.package} (`{spec.import_name}`)")
    emit(f"  model    {record.model_ref}")
    emit(
        f"  endpoint {(record.facts or {}).get('base_url') or 'the SDK default'}"
    )
    emit(
        f"  key      read at use time from {(record.user_metadata or {}).get('credential_ref')} (never stored)"
    )
    installed, why = sdk_available(args.sdk)
    emit(f"  sdk      {'installed' if installed else 'NOT installed - ' + why}")
    ready, why = ws.runtime_availability(record)
    emit(f"  runtime  {'ready' if ready else 'not ready'} - {why}")
    emit(
        "note: capabilities are claims until measured with `archx-agent models probe`"
    )
    return EXIT_OK

def handle_add_gemini(args, ws, command):
    from archx_agent.adapters.gemini_runtime import DEFAULT_BASE_URL
    base_url = (args.base_url or DEFAULT_BASE_URL).rstrip("/")
    if not str(args.credential_ref).startswith("secret://"):
        return fail(
            "credentials must be a secret://env/NAME or secret://file/PATH reference, "
            "not the key itself (the key would end up in the config, the trace and the logs)",
            EXIT_USAGE,
        )
    record = ws.register_gemini(
        args.name,
        model_ref=args.model,
        base_url=base_url,
        credential_ref=args.credential_ref,
        api_version=args.api_version,
        context_length=args.context_length,
        capabilities=args.capability or ["chat"],
        verification=args.verification,
    )
    emit(
        f"registered {record.name} ({record.id}) provider={record.provider} runtime={record.runtime}"
    )
    emit(f"  model    {record.model_ref}")
    emit(f"  endpoint {base_url}/{args.api_version}")
    emit(
        f"  key      read at use time from {args.credential_ref} (never stored)"
    )
    ready, why = ws.runtime_availability(record)
    emit(f"  runtime  {'ready' if ready else 'not ready'} - {why}")
    if str(base_url).startswith("https://") and not record.provider.startswith(
        "local"
    ):
        if ws.config.get("model.local_only"):
            emit("")
            emit(
                "note: model.local_only is true, so a chat turn will refuse to send"
            )
            emit(
                "      anything to this endpoint until you set it false deliberately."
            )
        emit(
            "note: this endpoint is remote; `providers add google`, confirm its privacy"
        )
        emit(
            "      terms and record consent before the first call (see docs/PROVIDERS.md)."
        )
    emit(
        "note: capabilities are claims until measured with `archx-agent models probe`"
    )
    return EXIT_OK

def handle_add_scripted(args, ws, command):
    record = ws.models.register_remote(
        args.name,
        provider="test-double",
        runtime="scripted",
        model_ref="simulated",
        context_length=8192,
        capabilities=["chat"],
        verification="unverified",
        claims={"simulated": True},
    )
    if record.name != args.name:
        emit(
            f"a simulated model is already registered as {record.name!r} ({record.id}); "
            "one test double is enough - reusing it"
        )
    else:
        emit(f"registered SIMULATED model {record.name} ({record.id})")
    emit(
        "  this runtime performs no inference; it exists to exercise the app offline"
    )
    return EXIT_OK
