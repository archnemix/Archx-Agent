"""Remote command: argument registration and execution."""

from __future__ import annotations

import argparse
import os


from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    _metric,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_DEGRADED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    remote = sub.add_parser(
        "remote",
        help="Remote compute: a portable bundle, a worker, and a hash checked on arrival",
    )
    rm_sub = remote.add_subparsers(dest="remote_command", required=True)
    rm_exp = rm_sub.add_parser(
        "export", help="write one portable bundle for a built dataset"
    )
    rm_exp.add_argument("dataset")
    rm_exp.add_argument("--method", default="ngram")
    rm_exp.add_argument("--order", type=int, default=3)
    rm_exp.add_argument("--smoothing", type=float, default=0.1)
    rm_exp.add_argument("--seed", type=int, default=0)
    rm_apr = rm_sub.add_parser("approve", help="allow this bundle to leave the machine")
    rm_apr.add_argument("job")
    rm_apr.add_argument("--by", default="user")
    rm_dis = rm_sub.add_parser(
        "dispatch", help="send a bundle to an endpoint and record the answer"
    )
    rm_dis.add_argument("job")
    rm_dis.add_argument("--endpoint", default=None)
    rm_col = rm_sub.add_parser("collect", help="fetch the artifact and re-hash it here")
    rm_col.add_argument("job")
    rm_col.add_argument("--endpoint", default=None)
    rm_ver = rm_sub.add_parser(
        "verify", help="re-read the artifact and compare it with the row"
    )
    rm_ver.add_argument("job")
    rm_list = rm_sub.add_parser("list", help="remote jobs, newest first")
    rm_list.add_argument(
        "--status",
        choices=[
            "draft",
            "dispatched",
            "running",
            "received",
            "verified",
            "failed",
            "refused",
        ],
    )
    rm_list.add_argument("--limit", type=int, default=20)
    rm_show = rm_sub.add_parser(
        "show", help="one remote job and every attempt made for it"
    )
    rm_show.add_argument("job")
    rm_att = rm_sub.add_parser(
        "attempts", help="the attempts log: dispatches that did not arrive"
    )
    rm_att.add_argument("--job", default=None)
    rm_att.add_argument("--limit", type=int, default=20)
    rm_sub.add_parser("stats", help="jobs by status, and why nothing can be dispatched")
    rm_worker = rm_sub.add_parser(
        "worker", help="serve the worker protocol on this machine"
    )
    rm_worker.add_argument(
        "--host", default="127.0.0.1", help="bind address (loopback by default)"
    )
    rm_worker.add_argument("--port", type=int, default=9001)
    rm_worker.add_argument("--name", default=None)
    rm_worker.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="seconds to wait before training (to see a pending job)",
    )
    rm_worker.add_argument(
        "--allow-exec",
        dest="allow_exec",
        action="store_true",
        help="let another machine run commands here (off by default)",
    )
    credentials = rm_worker.add_mutually_exclusive_group()
    credentials.add_argument("--token", default=None, help="bearer token (visible in argv; prefer --token-env)")
    credentials.add_argument("--token-env", help="environment variable containing the bearer token")
    rm_worker.add_argument("--max-running-jobs", type=int, default=4, help="active training job ceiling")
    rm_worker.add_argument("--max-jobs", type=int, default=128, help="retained job/result ceiling; no silent eviction")
    rm_worker.add_argument(
        "--workdir",
        default=None,
        help="directory commands and pushed files live in (default: a temp dir)",
    )


def cmd_remote(args: argparse.Namespace) -> int:
    """`remote ...` - hand a bundle to a worker, and check what comes back.

    Exit codes: 0 the question was answered (which includes a job that is simply still running);
    2 the input made no sense; 3 nothing was sent, or what came back did not verify.
    """
    command = args.remote_command
    try:
        if command == "worker":
            from archx_agent.application.remote_worker import serve

            # The worker needs no workspace: it is not a client of this database, which is what
            # makes it a remote worker rather than a second process reading the same file.
            token = args.token
            if args.token_env is not None:
                token = os.environ.get(args.token_env)
                if not token:
                    raise ValidationError("worker token environment variable is unset or empty")
            from archx_agent.application.remote_worker.policy import require_authenticated_bind
            try:
                require_authenticated_bind(args.host, token=token, allow_exec=args.allow_exec)
                if args.max_running_jobs <= 0 or args.max_jobs <= 0:
                    raise ValueError("worker job limits must be positive integers")
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            serve(
                host=args.host,
                port=args.port,
                name=args.name,
                delay=args.delay,
                allow_exec=args.allow_exec,
                token=token,
                max_running_jobs=args.max_running_jobs,
                max_jobs=args.max_jobs,
                workdir=args.workdir,
            )
            return EXIT_OK

        with _workspace(args) as ws:
            service = ws.remotes

            if command == "export":
                job = service.export(
                    args.dataset,
                    method=args.method,
                    order=args.order,
                    smoothing=args.smoothing,
                    seed=args.seed,
                )
                if args.json:
                    emit_json(job)
                    return EXIT_OK
                emit(
                    f"bundled {job['dataset_id']} as {job['id']}  ({job['records']} records, "
                    f"{job['chars']} characters)"
                )
                emit(f"  sha256    {job['bundle_sha256']}")
                emit(f"  path      {job['bundle_path']}")
                emit(f"  run       {job['config']['run']}")
                emit(
                    f"  next      archx-agent remote dispatch {job['id']} --endpoint URL"
                )
                return EXIT_OK

            if command == "approve":
                job = service.approve(args.job, by=args.by)
                if args.json:
                    emit_json(job)
                    return EXIT_OK
                emit(f"{job['id']} approved by {job['approved_by']}")
                emit(
                    f"  next      archx-agent remote dispatch {job['id']} --endpoint URL"
                )
                return EXIT_OK

            if command == "dispatch":
                job = service.dispatch(args.job, endpoint=args.endpoint)
                if args.json:
                    emit_json(job)
                    return EXIT_OK if job["status"] == "dispatched" else EXIT_DEGRADED
                emit(f"{job['status']} {job['id']}")
                emit(f"  {job['sentence']}")
                for reason in job.get("reasons", []):
                    emit(f"  - {reason}")
                if job["status"] == "dispatched":
                    emit(f"  next      archx-agent remote collect {job['id']}")
                    return EXIT_OK
                return EXIT_DEGRADED

            if command == "collect":
                job = service.collect(
                    args.job, timeout=float(ws.config.get("remote.timeout", 10))
                )
                if args.json:
                    emit_json(job)
                    return EXIT_OK if job["status"] == "verified" else EXIT_DEGRADED
                emit(f"{job['status']} {job['id']}")
                emit(f"  {job['sentence']}")
                if job.get("claimed_sha256"):
                    emit(f"  claimed   {job['claimed_sha256']}")
                    emit(f"  measured  {job['received_sha256']}")
                if job.get("artifact_path"):
                    emit(f"  artifact  {job['artifact_path']}")
                for split, values in sorted(
                    (job.get("outputs") or {}).get("metrics", {}).items()
                ):
                    rendered = ", ".join(
                        f"{name} {_metric(value)}"
                        for name, value in sorted(values.items())
                    )
                    emit(f"  {split:<8} {rendered}")
                if job.get("actual"):
                    rendered = ", ".join(
                        f"{k} {v}" for k, v in sorted(job["actual"].items())
                    )
                    emit(f"  worker    {rendered}")
                for reason in job.get("reasons", []):
                    emit(f"  - {reason}")
                return EXIT_OK if job["status"] == "verified" else EXIT_DEGRADED

            if command == "verify":
                result = service.verify(args.job)
                if args.json:
                    emit_json(result)
                    return EXIT_OK if result["agrees"] else EXIT_DEGRADED
                emit(
                    f"{result['id']}  {'verified' if result['agrees'] else 'not verified'}"
                )
                emit(f"  {result['verify_note']}")
                return EXIT_OK if result["agrees"] else EXIT_DEGRADED

            if command == "list":
                jobs = service.jobs(status=args.status, limit=args.limit)
                if args.json:
                    emit_json(jobs)
                    return EXIT_OK
                if not jobs:
                    emit("no remote jobs yet (archx-agent remote export DATASET)")
                    return EXIT_OK
                rows = [
                    [
                        job["id"],
                        job["status"],
                        job["dataset_id"] or "-",
                        str(job["bundle_sha256"] or "-")[:12],
                        job["endpoint"] or "-",
                        job["created_at"],
                    ]
                    for job in jobs
                ]
                emit(
                    table(
                        rows,
                        ["id", "status", "dataset", "bundle", "endpoint", "created"],
                    )
                )
                return EXIT_OK

            if command == "show":
                job = service.view(args.job)
                if args.json:
                    emit_json(job)
                    return EXIT_OK
                emit(f"{job['id']}  {job['status']}  ({job['kind']})")
                emit(f"  {job['sentence']}")
                emit(f"  dataset   {job['dataset_id'] or '-'}")
                emit(
                    f"  bundle    {str(job['bundle_sha256'] or '-')[:16]}  {job['bundle_path'] or ''}"
                )
                if job["endpoint"]:
                    emit(
                        f"  endpoint  {job['endpoint']}  ({job['protocol'] or '-'}, "
                        f"{job['machine'] or '-'})"
                    )
                if job["claimed_sha256"] or job["received_sha256"]:
                    emit(f"  claimed   {job['claimed_sha256'] or '-'}")
                    emit(f"  measured  {job['received_sha256'] or '-'}")
                if job["verify_note"]:
                    emit(f"  note      {job['verify_note']}")
                for split, values in sorted(
                    (job.get("outputs") or {}).get("metrics", {}).items()
                ):
                    rendered = ", ".join(
                        f"{name} {_metric(value)}"
                        for name, value in sorted(values.items())
                    )
                    emit(f"  {split:<8} {rendered}")
                for attempt in job["attempts"]:
                    emit(
                        f"  attempt   {attempt['action']:<8} {attempt['status']:<9} "
                        f"{attempt['detail'] or ''}"
                    )
                for reason in job.get("reasons", []):
                    emit(f"  - {reason}")
                return EXIT_OK

            if command == "attempts":
                attempts = service.attempts(job_id=args.job, limit=args.limit)
                if args.json:
                    emit_json(attempts)
                    return EXIT_OK
                if not attempts:
                    emit("no remote attempts yet")
                    return EXIT_OK
                rows = [
                    [
                        item["id"],
                        item["job_id"] or "-",
                        item["action"],
                        item["status"],
                        item["endpoint"] or "-",
                        item["detail"] or "-",
                        item["created_at"],
                    ]
                    for item in attempts
                ]
                emit(
                    table(
                        rows,
                        [
                            "id",
                            "job",
                            "action",
                            "status",
                            "endpoint",
                            "detail",
                            "created",
                        ],
                    )
                )
                return EXIT_OK

            if command == "stats":
                stats = service.stats()
                if args.json:
                    emit_json(stats)
                    return EXIT_OK
                emit(
                    f"remote   {'on' if stats['enabled'] else 'off'}   endpoint "
                    f"{stats['endpoint'] or '(none)'}"
                )
                emit(f"  protocol  {stats['protocol']}")
                emit(
                    f"  jobs      {stats['jobs']}   attempts {stats['attempts']}"
                    f"   unverified {stats['unverified']}"
                )
                for status, count in sorted(stats["by_status"].items()):
                    emit(f"    {status:<10} {count}")
                for reason in stats["why_not"]:
                    emit(f"  - {reason}")
                return EXIT_OK

    except ValidationError as exc:
        return fail(str(exc), EXIT_USAGE)
    except (NotFoundError, PermissionDeniedError) as exc:
        return fail(str(exc), EXIT_DEGRADED)
    except ApprovalRequiredError as exc:
        return fail(
            f"{exc} (approve with: archx-agent approve {getattr(exc, 'approval_id', '')})",
            EXIT_DEGRADED,
        )
    except ToolError as exc:
        return fail(str(exc), EXIT_DEGRADED)
    return fail(f"unknown remote command: {command}", EXIT_USAGE)
