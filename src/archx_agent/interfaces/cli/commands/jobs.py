"""Jobs command: argument registration and execution."""

from __future__ import annotations

import argparse


import json


import sys


from typing import Any


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_USAGE,
    EXIT_UNAVAILABLE,
    EXIT_DEGRADED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    jobs = sub.add_parser(
        "jobs", help="durable job queue: submit, run, pause, resume, recover"
    )
    jb_sub = jobs.add_subparsers(dest="jobs_command", required=True)
    jb_submit = jb_sub.add_parser("submit", help="queue a job (queued is not done)")
    jb_kinds = jb_submit.add_subparsers(dest="job_kind", required=True)

    def _job_options(p) -> None:
        p.add_argument("--title")
        p.add_argument("--priority", type=int, default=5, help="0-9, higher runs first")
        p.add_argument("--timeout", type=int, help="hard deadline in seconds")
        p.add_argument(
            "--max-attempts",
            type=int,
            help="attempts before a crash leaves it interrupted",
        )
        p.add_argument(
            "--dedupe-key",
            help="return the existing live job with this key instead of queueing twice",
        )
        p.add_argument("--project")
        p.add_argument(
            "--job-json",
            dest="payload",
            metavar="JSON",
            help="extra payload as a JSON object",
        )
        p.add_argument(
            "--run", action="store_true", help="drain the queue right after submitting"
        )

    jb_cmd = jb_kinds.add_parser("command", help="run a local command as a job")
    jb_cmd.add_argument(
        "job_command",
        metavar="command",
        help="command line (split like a shell; run without one)",
    )
    jb_cmd.add_argument("--cwd")
    _job_options(jb_cmd)

    jb_wf = jb_kinds.add_parser("workflow", help="run a stored workflow as a job")
    jb_wf.add_argument("workflow")
    jb_wf.add_argument(
        "--approve", action="store_true", help="approve a proposed plan / checkpoints"
    )
    _job_options(jb_wf)

    jb_res = jb_kinds.add_parser("research", help="run a research question as a job")
    jb_res.add_argument("question")
    jb_res.add_argument("--mode", choices=["local", "web", "mixed"])
    jb_res.add_argument("--url", action="append", default=[], metavar="URL")
    jb_res.add_argument("--max-subquestions", type=int)
    jb_res.add_argument("--no-model", action="store_true")
    _job_options(jb_res)

    jb_list = jb_sub.add_parser("list", help="job records (newest first)")
    jb_list.add_argument("--status")
    jb_list.add_argument("--kind", choices=["command", "workflow", "research"])
    jb_list.add_argument("--limit", type=int, default=20)
    jb_sub.add_parser("queue", help="what would run next, in order")
    jb_show = jb_sub.add_parser("show", help="one job plus the task timeline it wrote")
    jb_show.add_argument("job")
    jb_logs = jb_sub.add_parser(
        "logs", help="stdout/stderr (or the error) of a finished job"
    )
    jb_logs.add_argument("job")
    jb_run = jb_sub.add_parser("run", help="execute queued jobs (drain by default)")
    jb_run.add_argument("--once", action="store_true", help="run at most one job")
    jb_run.add_argument("--max-jobs", type=int, help="stop after this many jobs")
    jb_run.add_argument(
        "--max-seconds", type=float, help="stop claiming new work after this long"
    )
    jb_run.add_argument(
        "--concurrency", type=int, help="override scheduler.max_concurrent_jobs"
    )
    jb_run.add_argument("--kind", choices=["command", "workflow", "research"])
    jb_pause = jb_sub.add_parser(
        "pause", help="pause a queued job, or request a running one stop"
    )
    jb_pause.add_argument("job")
    jb_resume = jb_sub.add_parser(
        "resume", help="requeue a paused job (continues from its cursor)"
    )
    jb_resume.add_argument("job")
    jb_cancel = jb_sub.add_parser(
        "cancel", help="cancel a job (kills a running command)"
    )
    jb_cancel.add_argument("job")
    jb_cancel.add_argument("--reason")
    jb_retry = jb_sub.add_parser("retry", help="requeue a failed/interrupted job")
    jb_retry.add_argument("job")
    jb_retry.add_argument(
        "--force", action="store_true", help="retry even when attempts are used up"
    )
    jb_sub.add_parser("stats", help="counts by status and kind")
    jb_recover = jb_sub.add_parser(
        "recover", help="requeue jobs whose worker disappeared"
    )
    jb_recover.add_argument(
        "--stale-after",
        type=int,
        help="a live worker is considered stale after this many seconds",
    )
    jb_sub.add_parser("reap", help="fail running jobs whose hard deadline has passed")


def cmd_jobs(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.jobs
        runner = ws.scheduler
        if manager is None or runner is None:
            return fail(
                "the job scheduler is not available in this workspace", EXIT_UNAVAILABLE
            )
        command = args.jobs_command

        if command == "submit":
            payload: dict[str, Any] = {}
            if args.job_kind == "command":
                payload["command"] = args.job_command
                if getattr(args, "cwd", None):
                    payload["cwd"] = args.cwd
            elif args.job_kind == "research":
                payload["question"] = args.question
                payload["mode"] = args.mode
                payload["urls"] = list(args.url or [])
                payload["max_subquestions"] = args.max_subquestions
                payload["use_model"] = not bool(args.no_model)
                if not args.title:
                    args.title = f"research: {args.question}"[:120]
            else:
                payload["workflow"] = args.workflow
                payload["approve"] = bool(args.approve)
            if getattr(args, "payload", None):
                try:
                    extra = json.loads(args.payload)
                except ValueError as exc:
                    return fail(f"--job-json is not valid JSON: {exc}", EXIT_USAGE)
                if not isinstance(extra, dict):
                    return fail("--job-json must be a JSON object", EXIT_USAGE)
                payload.update(extra)
            job = manager.enqueue(
                args.job_kind,
                args.title,
                payload,
                priority=args.priority,
                timeout=args.timeout,
                max_attempts=args.max_attempts,
                project_id=args.project,
                dedupe_key=args.dedupe_key,
            )
            if args.json and args.run:
                pass  # one JSON document, emitted by _drain_jobs below
            elif args.json:
                emit_json(job.to_dict())
            else:
                queued = manager.stats()["queued"]
                emit(
                    f"{job.id}  {job.kind}  {job.status}  queue #{job.queue_seq}  {job.title}"
                )
                emit(
                    f"  timeout {job.timeout_seconds}s  attempts {job.attempts}/{job.max_attempts}"
                    f"  priority {job.priority}  ({queued} queued)"
                )
                emit(
                    f"  run it with: archx-agent jobs run   (or inspect: jobs show {job.id})"
                )
            if args.run:
                return _drain_jobs(ws, args, manager, runner, submitted=job)
            return EXIT_OK

        if command == "list":
            rows = manager.list(status=args.status, kind=args.kind, limit=args.limit)
            if args.json:
                emit_json([row.to_dict() for row in rows])
            else:
                if not rows:
                    emit("no jobs")
                else:
                    emit(
                        table(
                            [
                                [
                                    row.id,
                                    row.kind,
                                    row.status,
                                    row.queue_seq,
                                    f"{row.attempts}/{row.max_attempts}",
                                    row.title[:40],
                                    row.created_at[11:19],
                                ]
                                for row in rows
                            ],
                            ["job", "kind", "status", "seq", "att", "title", "created"],
                        )
                    )
            return EXIT_OK

        if command == "queue":
            rows = manager.queue()
            if args.json:
                emit_json([row.to_dict() for row in rows])
            else:
                if not rows:
                    emit("the queue is empty")
                else:
                    emit(
                        table(
                            [
                                [
                                    row.queue_seq,
                                    row.priority,
                                    row.kind,
                                    row.title[:44],
                                    row.id,
                                ]
                                for row in rows
                            ],
                            ["seq", "priority", "kind", "title", "job"],
                        )
                    )
            return EXIT_OK

        if command == "show":
            job = manager.require(args.job)
            data: dict[str, Any] = job.to_dict()
            if job.task_id:
                found = ws.tasks.find(job.task_id)
                if found.is_ok:
                    data["task"] = found.value.to_dict()
                    data["timeline"] = ws.tasks.timeline(job.task_id)
            if job.kind == "workflow" and job.payload.get("workflow"):
                workflow = ws.workflows.find(str(job.payload["workflow"]))
                if workflow is not None:
                    data["workflow"] = workflow.to_dict(with_definition=False)
                    data["steps"] = [
                        {
                            "seq": step.seq,
                            "kind": step.kind,
                            "status": step.status,
                            "title": step.title,
                            "error": step.error,
                        }
                        for step in ws.workflows.steps(workflow.id)
                    ]
            if args.json:
                emit_json(data)
            else:
                emit(f"{job.id}  {job.kind}  [{job.status}]  {job.title}")
                emit(
                    f"  queue #{job.queue_seq}  priority {job.priority}"
                    f"  attempts {job.attempts}/{job.max_attempts}"
                )
                if job.timeout_seconds:
                    emit(
                        f"  deadline {job.deadline or '-'}  (timeout {job.timeout_seconds}s)"
                    )
                if job.worker:
                    emit(f"  worker {job.worker}  pid {job.pid}")
                if job.cursor:
                    emit(f"  cursor: {job.cursor} step(s) done")
                if job.message:
                    emit(f"  message: {job.message}")
                if job.error:
                    emit(f"  error: {job.error}")
                if job.task_id:
                    emit(f"  task: {job.task_id}")
                emit("")
                timeline = data.get("timeline") or []
                if timeline:
                    emit("  timeline:")
                    for entry in timeline:
                        emit(
                            f"    {entry['seq']:>3}  {entry.get('kind', ''):<20} {(entry.get('detail') or '')[:90]}"
                        )
                for step in data.get("steps") or []:
                    emit(
                        f"  step {step['seq']}: {step['kind']} [{step['status']}] {step['title']}"
                    )
            return EXIT_OK

        if command == "logs":
            job = manager.require(args.job)
            result = job.result or {}
            if args.json:
                emit_json(
                    {
                        "job_id": job.id,
                        "status": job.status,
                        "error": job.error,
                        "result": result,
                    }
                )
                return EXIT_OK
            if result.get("stdout"):
                emit(result["stdout"].rstrip())
            if result.get("stderr"):
                emit("-- stderr --")
                emit(result["stderr"].rstrip())
            if job.result and "exit_code" in job.result:
                emit(
                    f"-- exit {job.result['exit_code']} in {job.result.get('duration_ms', 0):.0f}ms --"
                )
            if job.error:
                print(f"error: {job.error}", file=sys.stderr)
            if not result.get("stdout") and not result.get("stderr") and not job.error:
                emit("(no output recorded)")
            return EXIT_OK

        if command == "run":
            return _drain_jobs(ws, args, manager, runner)

        if command == "pause":
            job = manager.require(args.job)
            paused = manager.pause(job.id)
            if paused.status == "running":
                emit(
                    f"{paused.id}  pause requested; it stops at the next step boundary"
                )
            else:
                emit(f"{paused.id}  {paused.status}")
            return EXIT_OK

        if command == "resume":
            job = manager.require(args.job)
            resumed = manager.resume(job.id)
            emit(
                f"{resumed.id}  {resumed.status}  (continues from step {resumed.cursor})"
            )
            return EXIT_OK

        if command == "cancel":
            job = manager.require(args.job)
            cancelled = manager.cancel(
                job.id, reason=args.reason or "cancelled by the user"
            )
            emit(
                f"{cancelled.id}  {cancelled.status}"
                + (
                    "  (cancel requested; a running command is killed)"
                    if cancelled.status == "running"
                    else ""
                )
            )
            return EXIT_OK

        if command == "retry":
            job = manager.require(args.job)
            retried = manager.retry(job.id, force=args.force)
            emit(
                f"{retried.id}  {retried.status}  attempts {retried.attempts}/{retried.max_attempts}"
            )
            return EXIT_OK

        if command == "stats":
            stats = manager.stats()
            if args.json:
                emit_json(stats)
            else:
                emit(
                    f"jobs: {stats['total']}  queued {stats['queued']}  running {stats['running']}"
                    f"  paused {stats['paused']}"
                )
                for status, count in sorted(stats["by_status"].items()):
                    emit(f"  {status:<12} {count}")
                for kind, count in sorted(stats["by_kind"].items()):
                    emit(f"  {kind:<12} {count}")
            return EXIT_OK

        if command == "recover":
            recovered = manager.recover(stale_after=args.stale_after)
            if args.json:
                emit_json(recovered)
            else:
                emit(
                    f"requeued {recovered['requeued']}  interrupted {recovered['interrupted']}"
                    f"  left alone {recovered['skipped']}"
                )
                for job_id in recovered["requeued_ids"]:
                    emit(f"  requeued  {job_id}")
                for job_id in recovered["interrupted_ids"]:
                    emit(f"  interrupted  {job_id}")
            return EXIT_OK

        if command == "reap":
            reaped = manager.reap_expired()
            if args.json:
                emit_json(reaped)
            else:
                emit(f"failed {reaped['expired']} job(s) whose deadline had passed")
                for job_id in reaped["ids"]:
                    emit(f"  timed out  {job_id}")
            return EXIT_OK
    return EXIT_USAGE


def _drain_jobs(ws, args: argparse.Namespace, manager, runner, submitted=None) -> int:
    """Run queued work and report every job it touched."""
    once = bool(getattr(args, "once", False))
    max_jobs = 1 if once else getattr(args, "max_jobs", None)
    results = runner.drain(
        max_jobs=max_jobs,
        max_seconds=getattr(args, "max_seconds", None),
        concurrency=getattr(args, "concurrency", None),
        kinds=[args.job_kind] if getattr(args, "job_kind", None) else None,
    )
    stats = manager.stats()
    if getattr(args, "json", False):
        payload: dict[str, Any] = {
            "ran": [job.to_dict() for job in results],
            "stats": stats,
        }
        if submitted is not None:
            payload["submitted"] = submitted.to_dict()
        emit_json(payload)
    else:
        if not results:
            emit("no queued jobs ran")
        else:
            emit(
                table(
                    [
                        [
                            job.id,
                            job.kind,
                            job.status,
                            f"{job.attempts}/{job.max_attempts}",
                            (job.error or job.message or "")[:44],
                        ]
                        for job in results
                    ],
                    ["job", "kind", "status", "att", "note"],
                )
            )
        emit(
            f"queue: {stats['queued']} queued, {stats['running']} running,"
            f" {stats['paused']} paused"
        )
    if any(job.status in ("failed", "cancelled") for job in results):
        return EXIT_ERROR
    if stats["queued"] or stats["running"] or stats["paused"]:
        return EXIT_DEGRADED
    return EXIT_OK
