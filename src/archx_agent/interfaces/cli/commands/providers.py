"""Providers command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.helpers.jsonio import json_text


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_DEGRADED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    prov = sub.add_parser(
        "providers", help="local/cloud providers, privacy terms, consent, usage"
    )
    prov_sub = prov.add_subparsers(dest="provider_command", required=True)
    prov_sub.add_parser(
        "catalogue", help="known provider templates (claims, not facts)"
    )
    p_list = prov_sub.add_parser("list", help="registered providers")
    p_list.add_argument("--kind", choices=["local", "cloud", "custom"])
    p_add = prov_sub.add_parser("add", help="register a provider")
    p_add.add_argument("name")
    p_add.add_argument(
        "--template",
        help="known template slug (openai, anthropic, google, openai-compatible-local)",
    )
    p_add.add_argument("--kind", choices=["local", "cloud", "custom"])
    p_add.add_argument(
        "--api-style", choices=["openai", "anthropic", "gemini", "custom"]
    )
    p_add.add_argument("--base-url")
    p_add.add_argument("--model-family")
    p_add.add_argument("--auth-ref", help="secret://env/NAME (never the key itself)")
    p_add.add_argument(
        "--local",
        action="store_true",
        help="endpoint runs on this machine (loopback only)",
    )
    p_add.add_argument("--notes", default="")
    p_add.add_argument(
        "--price-in", type=float, help="cost per 1k input tokens, if you want estimates"
    )
    p_add.add_argument("--price-out", type=float)
    p_add.add_argument("--currency", default="USD")
    p_show = prov_sub.add_parser(
        "show", help="one provider with effective privacy view"
    )
    p_show.add_argument("provider")
    p_confirm = prov_sub.add_parser(
        "confirm", help="record what YOU confirmed about the provider's data handling"
    )
    p_confirm.add_argument("provider")
    p_confirm.add_argument("--data-leaves-device", required=True, choices=["yes", "no"])
    p_confirm.add_argument("--training-use", default="unknown")
    p_confirm.add_argument("--retention", default="unknown")
    p_confirm.add_argument("--region", default="unknown")
    p_consent = prov_sub.add_parser(
        "consent", help="record explicit consent to send data remotely"
    )
    p_consent.add_argument("provider")
    p_consent.add_argument("--note", default="")
    p_revoke = prov_sub.add_parser("revoke", help="withdraw consent")
    p_revoke.add_argument("provider")
    p_enable = prov_sub.add_parser("enable", help="enable a provider")
    p_enable.add_argument("provider")
    p_disable = prov_sub.add_parser("disable", help="disable a provider")
    p_disable.add_argument("provider")
    p_check = prov_sub.add_parser(
        "check", help="probe reachability/auth (never sends prompt content)"
    )
    p_check.add_argument("provider")
    p_check.add_argument("--timeout", type=float, default=4.0)
    p_quota = prov_sub.add_parser("quota", help="declare (and enforce) a daily quota")
    p_quota.add_argument("provider")
    p_quota.add_argument("--requests-per-day", type=int)
    p_quota.add_argument("--tokens-per-day", type=int)
    p_usage = prov_sub.add_parser("usage", help="usage and estimated cost")
    p_usage.add_argument("provider", nargs="?")
    p_usage.add_argument("--days", type=int, default=30)
    p_usage.add_argument("--by-day", action="store_true")
    prov_sub.add_parser("privacy", help="privacy view of every registered provider")
    p_remove = prov_sub.add_parser("remove", help="remove a provider record")
    p_remove.add_argument("provider")
    prov_sub.add_parser("stats", help="provider counts")


def cmd_providers(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.providers
        command = args.provider_command
        if command == "catalogue":
            rows = manager.catalogue()
            emit_json(rows) if args.json else emit(
                table(
                    [
                        [
                            r["slug"],
                            r["kind"],
                            "yes" if r["is_local"] else "no",
                            r["base_url"] or "-",
                        ]
                        for r in rows
                    ],
                    ["template", "kind", "local", "base_url"],
                )
            )
            return EXIT_OK
        if command == "list":
            rows = [p.to_dict() for p in manager.list(kind=args.kind)]
            emit_json(rows) if args.json else (
                emit(
                    table(
                        [
                            [
                                r["id"],
                                r["name"],
                                r["kind"],
                                "local" if r["is_local"] else "cloud",
                                "consented"
                                if r["consented"]
                                else (
                                    "n/a" if not r["requires_consent"] else "no consent"
                                ),
                                r["blocking_reason"] or "usable",
                            ]
                            for r in rows
                        ],
                        ["id", "name", "kind", "scope", "consent", "state"],
                    )
                )
                if rows
                else emit("no providers registered")
            )
            return EXIT_OK
        if command == "add":
            result = manager.add(
                args.name,
                template=args.template,
                kind=args.kind,
                api_style=args.api_style,
                base_url=args.base_url,
                model_family=args.model_family,
                auth_ref=args.auth_ref,
                is_local=True if args.local else None,
                notes=args.notes,
                price_in_per_1k=args.price_in,
                price_out_per_1k=args.price_out,
                currency=args.currency,
            )
            if result.is_err:
                return fail(result.error.message, EXIT_USAGE)
            data = result.value.to_dict()
            if args.json:
                emit_json(data)
            else:
                emit(
                    f"registered provider {data['id']}  {data['name']} "
                    f"({'on this machine' if data['is_local'] else 'remote'}, {data['kind']})"
                )
                if data["blocking_reason"]:
                    emit(f"  not usable yet: {data['blocking_reason']}")
            return EXIT_OK
        if command == "show":
            result = manager.get(args.provider)
            if result.is_err:
                return fail(result.error.message)
            data = result.value.to_dict()
            emit_json(data) if args.json else emit(json_text(data))
            return EXIT_OK
        if command == "confirm":
            result = manager.confirm_privacy(
                args.provider,
                data_leaves_device=args.data_leaves_device == "yes",
                training_use=args.training_use,
                retention=args.retention,
                region=args.region,
            )
            if result.is_err:
                return fail(result.error.message, EXIT_USAGE)
            emit_json(result.value.to_dict()) if args.json else emit(
                f"privacy terms recorded for {result.value.name}: data_leaves_device="
                f"{result.value.data_leaves_device}; training_use={args.training_use}; "
                f"retention={args.retention}"
            )
            return EXIT_OK
        if command == "consent":
            result = manager.consent(args.provider, note=args.note)
            if result.is_err:
                return fail(result.error.message, EXIT_USAGE)
            emit_json(result.value.to_dict()) if args.json else emit(
                f"consent recorded for {result.value.name} (version {result.value.consent_version})"
            )
            return EXIT_OK
        if command == "revoke":
            result = manager.revoke_consent(args.provider)
            if result.is_err:
                return fail(result.error.message)
            emit(
                f"consent revoked for {result.value.name}: no request will be sent until you consent again"
            )
            return EXIT_OK
        if command in ("enable", "disable"):
            result = manager.enable(args.provider, enabled=command == "enable")
            if result.is_err:
                return fail(result.error.message)
            emit_json(result.value.to_dict()) if args.json else emit(
                f"{result.value.name} {'enabled' if result.value.enabled else 'disabled'}"
            )
            return EXIT_OK
        if command == "check":
            result = manager.check(args.provider, timeout=args.timeout)
            if result.is_err:
                return fail(result.error.message)
            data = result.value
            if args.json:
                emit_json(data)
            else:
                emit(f"{data['status']}  ({data['detail']})")
                if data.get("latency_ms") is not None:
                    emit(f"  latency {data['latency_ms']} ms")
                if data.get("models_seen") is not None:
                    emit(f"  models seen {data['models_seen']}")
                emit(
                    "  note: this probes the models endpoint; it never sends prompt content"
                )
            return (
                EXIT_OK
                if data["status"] in ("reachable", "model_missing")
                else EXIT_DEGRADED
            )
        if command == "quota":
            if args.requests_per_day is None and args.tokens_per_day is None:
                existing = manager.get(args.provider)
                if existing.is_err:
                    return fail(existing.error.message)
                emit_json(existing.value.quotas) if args.json else emit(
                    json_text(existing.value.quotas)
                    if existing.value.quotas
                    else "no quota declared"
                )
                return EXIT_OK
            result = manager.set_quota(
                args.provider,
                max_requests_per_day=args.requests_per_day,
                max_tokens_per_day=args.tokens_per_day,
            )
            if result.is_err:
                return fail(result.error.message)
            emit_json(result.value.quotas) if args.json else emit(
                f"quota for {result.value.name}: {result.value.quotas}"
            )
            return EXIT_OK
        if command == "usage":
            if args.provider:
                result = manager.get(args.provider)
                if result.is_err:
                    return fail(result.error.message)
                data = manager.usage(result.value.id, days=args.days)
                if args.by_day:
                    data = {
                        "summary": data,
                        "daily": manager.usage_by_day(result.value.id, days=args.days),
                    }
                emit_json(data) if args.json else emit(json_text(data))
                return EXIT_OK
            rows = [
                {"provider": p.name, **manager.usage(p.id, days=args.days)}
                for p in manager.list()
            ]
            emit_json(rows) if args.json else (
                emit(
                    table(
                        [
                            [
                                r["provider"],
                                r["requests"],
                                r["tokens_in"],
                                r["tokens_out"],
                                r["errors"],
                                r["estimated_cost"]
                                if r["estimated_cost"] is not None
                                else "-",
                            ]
                            for r in rows
                        ],
                        [
                            "provider",
                            "requests",
                            "tokens_in",
                            "tokens_out",
                            "errors",
                            "est. cost",
                        ],
                    )
                )
                if rows
                else emit("no providers registered")
            )
            return EXIT_OK
        if command == "privacy":
            rows = manager.privacy_report()

            def leaves_cell(row):
                value = row["data_leaves_device"]
                label = "yes" if value else ("no" if value is False else "unknown")
                source = row["effective_privacy"]["sources"].get("data_leaves_device")
                if source == "user-confirmed":
                    return f"{label} (you confirmed)"
                if source and source.startswith("derived"):
                    return f"{label} (from URL)"
                if source:
                    return f"{label} (vendor claim)"
                return label

            emit_json(rows) if args.json else (
                emit(
                    table(
                        [
                            [
                                r["name"],
                                r["kind"],
                                "yes" if r["is_local"] else "no",
                                leaves_cell(r),
                                "yes" if r["consented"] else "no",
                                r["blocking_reason"] or "usable",
                            ]
                            for r in rows
                        ],
                        [
                            "provider",
                            "kind",
                            "local",
                            "leaves device",
                            "consent",
                            "state",
                        ],
                    )
                )
                if rows
                else emit("no providers registered")
            )
            return EXIT_OK
        if command == "remove":
            result = manager.remove(args.provider)
            if result.is_err:
                return fail(result.error.message)
            emit(f"removed provider {result.value}")
            return EXIT_OK
        if command == "stats":
            data = manager.stats()
            emit_json(data) if args.json else emit(json_text(data))
            return EXIT_OK
    return EXIT_USAGE
