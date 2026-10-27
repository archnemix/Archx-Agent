"""The scheduler: what actually runs a job, with a hard deadline.

The queue (:class:`~archx_agent.managers.jobs.JobManager`) decides *what* runs and
records what happened. This module decides *how*, and it is deliberately the only
place that spawns processes or owns threads.

Kinds
-----
``command``
    a real child process. It runs in its own session so a timeout can kill the whole
    process group; a partial line of output is still captured. Its task is of type
    ``automation`` and its exit code, stdout and stderr are recorded on the job.
``workflow``
    an M25 workflow. The job is a *scheduling* wrapper: the workflow keeps its own
    task, conversation, step rows and permission checks. Pausing stops at a step
    boundary and stores the cursor; resume continues from the first step without a
    succeeded row.

Deadlines
---------
Every job carries an absolute ``deadline`` computed when it was claimed. A child
process is killed at that deadline (SIGKILL to its process group). An in-process
workflow cannot have a thread killed safely, so the deadline is checked at each step
boundary *and* by any worker that calls ``reap_expired`` - the job is failed, never
left running in the table.

Concurrency
-----------
``drain`` runs up to ``scheduler.max_concurrent_jobs`` jobs at once, and only claims a
job whose resource estimate fits what is left of ``scheduler.cpu_limit_percent`` and
``scheduler.memory_limit_mb``. Estimates are the job's own declared cost, not a
measurement; the observed duration and peak RSS are recorded afterwards so the
estimate can be corrected with evidence.
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now, parse_iso

from archx_agent.managers.jobs import Job

MAX_OUTPUT_CHARS = 20_000


class JobStopped(Exception):
    """The runner stopped its own work: ``reason`` is ``pause`` or ``cancel``."""

    def __init__(self, reason: str, *, message: str, cursor: int = 0) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.cursor = int(cursor)


@dataclass
class JobRun:
    job_id: str
    kind: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    cursor: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "cursor": self.cursor,
        }


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n[... truncated {len(text) - limit} character(s)]", True


def _peak_rss_mb() -> float | None:
    """Best-effort RSS of this process; used as the observed cost, not a limit."""
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:  # noqa: BLE001 - not available everywhere
        return None
    # Linux reports kilobytes, macOS bytes.
    return round(value / 1024.0, 1) if os.uname().sysname == "Linux" else round(value / (1024.0**2), 1)


class JobRunner:
    """Claims jobs and runs them. One per process is enough; it is thread-safe."""

    def __init__(
        self,
        workspace,
        *,
        worker: str | None = None,
        poll: float = 0.05,
        kinds: Sequence[str] | None = None,
    ) -> None:
        self.ws = workspace
        self.jobs = workspace.jobs
        self.worker = worker or self.jobs.instance
        self.poll = float(poll)
        self.kinds = tuple(kinds) if kinds else None
        self._stop = False

    # -- config ------------------------------------------------------------
    def _cfg(self, key: str, default: Any) -> Any:
        try:
            return self.ws.config.get(key)
        except Exception:  # noqa: BLE001
            return default

    def stop(self) -> None:
        """Stop claiming new work (in-flight jobs are allowed to finish)."""
        self._stop = True

    # -- admission ---------------------------------------------------------
    def _free(self, in_flight: Iterable[Job]) -> tuple[float, float]:
        cpu_limit = float(self._cfg("scheduler.cpu_limit_percent", 80))
        mem_limit = float(self._cfg("scheduler.memory_limit_mb", 2048))
        used_cpu = sum(float(job.resource_estimate.get("cpu_percent", 0)) for job in in_flight)
        used_mem = sum(float(job.resource_estimate.get("memory_mb", 0)) for job in in_flight)
        return max(0.0, cpu_limit - used_cpu), max(0.0, mem_limit - used_mem)

    def will_admit(self) -> bool:
        """Could anything be claimed right now? (used by ``jobs run --once``)."""
        return self._free(self.jobs.running())[0] > 0

    # -- one job -----------------------------------------------------------
    def execute(self, job: Job) -> Job:
        """Run one job. A queued job is claimed first, so the record is consistent."""
        if job.status == "queued":
            claimed = self.jobs.claim(worker=self.worker, job_id=job.id)
            if claimed is None:
                raise ConflictError(
                    f"job {job.id} could not be claimed: it is {self.jobs.get(job.id).status}"
                )
            job = claimed
        elif job.status != "running":
            raise ConflictError(f"job {job.id} is {job.status}; only a claimed job can run")
        handler: Callable[[Job], Mapping[str, Any] | None] = {
            "command": self._run_command,
            "workflow": self._run_workflow,
        }.get(job.kind, None)  # type: ignore[assignment]
        if handler is None:  # pragma: no cover - enqueue validates the kind
            self.jobs.fail(job.id, f"no runner for job kind {job.kind!r}")
            return self.jobs.get(job.id)
        try:
            result = handler(job) or {}
        except JobStopped as stop:
            if stop.reason == "pause":
                self.jobs.stop(
                    job.id, status="paused", message=stop.message, cursor=stop.cursor
                )
            else:
                self.jobs.stop(
                    job.id, status="cancelled", message=stop.message, cursor=stop.cursor
                )
            return self.jobs.get(job.id)
        except ApprovalRequiredError as exc:
            self.jobs.fail(job.id, f"approval required: {exc.message}")
            return self.jobs.get(job.id)
        except Exception as exc:  # noqa: BLE001 - a job failure is data, not a crash
            message = getattr(exc, "message", None) or str(exc)
            output = getattr(exc, "result", None)
            self.jobs.fail(job.id, message, result=output)
            return self.jobs.get(job.id)
        finished = self.jobs.finish(job.id, result=dict(result))
        self._close_command_task(finished, result)
        return finished

    def _close_command_task(self, job: Job, result: Mapping[str, Any]) -> None:
        """Close the task a command job owns, now that the job is completed."""
        if not job.task_id:
            return
        found = self.ws.tasks.find(job.task_id)
        if not found.is_ok or found.value.terminal:
            return
        stdout = str(result.get("stdout") or "").strip()
        self.ws.tasks.complete(
            job.task_id,
            summary=stdout[:500] or f"exit {result.get('exit_code', 0)}",
            outputs=[job.id],
            resource_use={
                "duration_ms": result.get("duration_ms"),
                "exit_code": result.get("exit_code"),
            },
        )

    # -- command jobs ------------------------------------------------------
    def _run_command(self, job: Job) -> Mapping[str, Any]:
        payload = job.payload
        raw = payload.get("command")
        if isinstance(raw, str):
            argv = shlex.split(raw)
        elif isinstance(raw, (list, tuple)) and raw:
            argv = [str(part) for part in raw]
        else:
            raise ValidationError("a command job needs payload.command (string or list)")
        if not argv:
            raise ValidationError("a command job needs a non-empty command")
        cwd = payload.get("cwd") or None
        if cwd and not os.path.isdir(str(cwd)):
            raise ValidationError(f"working directory does not exist: {cwd}")
        if shutil.which(argv[0]) is None and not os.path.isabs(argv[0]):
            raise ValidationError(f"command not found: {argv[0]}")

        task = self._ensure_task(job, "automation", f"job: {job.title}")
        self.jobs.link_task(job.id, task.id)
        started = time.perf_counter()
        deadline = self._deadline_ts(job)
        env = dict(os.environ)
        for key, value in dict(payload.get("env") or {}).items():
            env[str(key)] = str(value)

        proc = subprocess.Popen(  # noqa: S603 - argv comes from the user's own job
            argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
        self._log(task.id, "command_started", " ".join(argv)[:500])
        timed_out = False
        cancelled = False
        try:
            while True:
                code = proc.poll()
                if code is not None:
                    break
                if deadline is not None and time.time() >= deadline:
                    timed_out = True
                    self._kill(proc)
                    break
                control_state = self.jobs.control(job.id)
                if control_state == "cancel":
                    cancelled = True
                    self._kill(proc)
                    break
                time.sleep(min(self.poll, 0.2))
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - a killed child that lingers
            proc.kill()
            out, err = proc.communicate()
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        limit = min(MAX_OUTPUT_CHARS, int(self._cfg("tools.max_output_bytes", MAX_OUTPUT_CHARS)))
        out, out_cut = _truncate(out or "", limit)
        err, err_cut = _truncate(err or "", limit)
        result = {
            "argv": argv,
            "exit_code": proc.returncode,
            "stdout": out,
            "stderr": err,
            "duration_ms": elapsed_ms,
            "truncated": bool(out_cut or err_cut),
            "timed_out": timed_out,
            "cancelled": cancelled,
            "env_overrides": sorted(dict(payload.get("env") or {})),
        }
        self.jobs.heartbeat(
            job.id,
            progress=1.0,
            resource_observed={"memory_mb_peak": _peak_rss_mb(), "duration_ms": elapsed_ms},
        )
        if cancelled:
            self.ws.tasks.cancel(task.id, "cancelled while the command was running")
            raise JobStopped("cancel", message="cancelled while the command was running")
        if timed_out:
            failure = ValidationError(
                f"command timed out after {job.timeout_seconds}s and was killed"
            )
            self.ws.tasks.fail(task.id, failure)
            self._log(task.id, "command_timed_out", f"after {job.timeout_seconds}s")
            failure.result = result  # type: ignore[attr-defined]
            raise failure
        if proc.returncode != 0:
            detail = (err or out or "").strip().splitlines()
            tail = detail[-1][:300] if detail else ""
            failure = ValidationError(
                f"command exited with code {proc.returncode}"
                + (f": {tail}" if tail else "")
            )
            self.ws.tasks.fail(task.id, failure)
            self._log(task.id, "command_failed", f"exit {proc.returncode}")
            failure.result = result  # type: ignore[attr-defined]
            raise failure
        self._log(task.id, "command_succeeded", f"exit 0 in {elapsed_ms:.0f}ms")
        # The task is closed by execute() *after* the job is marked completed, so the
        # timeline reads "... command_succeeded, job_completed, summary, completed".
        return result

    # -- workflow jobs -----------------------------------------------------
    def _run_workflow(self, job: Job) -> Mapping[str, Any]:
        from archx_agent.application.agent import RunPaused, WorkflowFailed

        ref = str(job.payload.get("workflow") or "")
        if not ref:
            raise ValidationError("a workflow job needs payload.workflow")
        approve = bool(job.payload.get("approve", False))
        workflow = self.ws.workflows.require(ref)
        resume = bool(job.cursor) or workflow.status == "running"
        total = len(workflow.steps) or 1
        deadline = self._deadline_ts(job)

        def control(completed: int) -> str | None:
            if deadline is not None and time.time() >= deadline:
                # Raising here fails the workflow and its task through the ordinary
                # error path - a deadline must not look like a clean cancel.
                raise TimeoutError(
                    f"job {job.id} exceeded its {job.timeout_seconds}s deadline after "
                    f"{completed} step(s)"
                )
            self.jobs.heartbeat(
                job.id,
                progress=min(0.99, completed / total),
                message=f"step {completed}/{total}",
                cursor=completed,
            )
            return self.jobs.control(job.id)

        try:
            run = self.ws.agent.run(
                workflow.id, approve=approve, resume=resume, control=control
            )
        except RunPaused as paused:
            self.jobs.link_task(job.id, paused.task_id)
            raise JobStopped(
                "pause",
                message=f"paused after step {paused.cursor}",
                cursor=paused.cursor,
            ) from paused
        except WorkflowFailed as exc:
            if exc.task_id:
                self.jobs.link_task(job.id, exc.task_id)
            raise ValidationError(exc.message) from exc
        except TimeoutError as exc:
            raise ValidationError(str(exc)) from exc

        self.jobs.link_task(job.id, run.task_id)
        if run.status == "cancelled":
            raise JobStopped("cancel", message="the workflow was cancelled")
        return {
            "workflow_id": run.workflow_id,
            "task_id": run.task_id,
            "steps": len(run.steps),
            "tokens": run.tokens,
            "elapsed_ms": run.elapsed_ms,
            "summary": run.summary[:500],
        }

    # -- claiming / draining -----------------------------------------------
    def run_once(self) -> Job | None:
        """Claim and run one job in this thread. Returns ``None`` if nothing fits."""
        free_cpu, free_mem = self._free(self.jobs.running())
        if free_cpu <= 0:
            return None
        job = self.jobs.claim(
            worker=self.worker, cpu_free=free_cpu, memory_free=free_mem, kinds=self.kinds
        )
        if job is None:
            return None
        return self.execute(job)

    def drain(
        self,
        *,
        max_jobs: int | None = None,
        max_seconds: float | None = None,
        concurrency: int | None = None,
        kinds: Sequence[str] | None = None,
    ) -> list[Job]:
        """Run queued jobs, up to ``concurrency`` at a time, until the queue is empty.

        ``max_seconds`` stops *claiming* new work at the deadline; jobs already in
        flight are awaited so nothing is left half-done behind a process exit.
        """
        concurrency = int(concurrency or self._cfg("scheduler.max_concurrent_jobs", 2))
        concurrency = max(1, min(concurrency, 64))
        kinds = tuple(kinds) if kinds else self.kinds
        deadline = time.monotonic() + float(max_seconds) if max_seconds else None
        done: list[Job] = []
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="archx-job") as pool:
            futures: dict[Future, Job] = {}

            def collect() -> None:
                for future in list(futures):
                    if not future.done():
                        continue
                    job = futures.pop(future)
                    try:
                        done.append(future.result())
                    except Exception:  # noqa: BLE001 - execute() already recorded it
                        done.append(self.jobs.get(job.id))

            while True:
                collect()
                if max_jobs is not None and len(done) >= max_jobs:
                    break
                if self._stop:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                room = concurrency
                if max_jobs is not None:
                    room = min(room, max_jobs - len(done) - len(futures))
                if room > 0:
                    free_cpu, free_mem = self._free(futures.values())
                    if free_cpu > 0:
                        job = self.jobs.claim(
                            worker=self.worker,
                            cpu_free=free_cpu,
                            memory_free=free_mem,
                            kinds=kinds,
                        )
                        if job is not None:
                            futures[pool.submit(self.execute, job)] = job
                            continue
                if not futures:
                    break
                time.sleep(self.poll)
            for future, job in list(futures.items()):
                try:
                    done.append(future.result())
                except Exception:  # noqa: BLE001
                    done.append(self.jobs.get(job.id))
        return done

    # -- helpers -----------------------------------------------------------
    def _deadline_ts(self, job: Job) -> float | None:
        if not job.deadline:
            return None
        try:
            return parse_iso(job.deadline).timestamp()
        except ValueError:  # pragma: no cover - defensive
            return None

    def _ensure_task(self, job: Job, kind: str, title: str):
        if job.task_id:
            found = self.ws.tasks.find(job.task_id)
            if found.is_ok and not found.value.terminal:
                return found.value
        task = self.ws.tasks.create(
            kind,
            title[:200],
            start=True,
            project_id=job.project_id,
            metadata={"job_id": job.id, "kind": job.kind},
        )
        self.jobs.link_task(job.id, task.id)
        return task

    def _log(self, task_id: str | None, kind: str, detail: str | None = None) -> None:
        if not task_id:
            return
        try:
            self.ws.tasks.log(task_id, kind, detail=detail)
        except Exception:  # noqa: BLE001 - a closed task must not stop the job
            return

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        """Kill the child *and its children*: the whole process group."""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except ProcessLookupError:  # pragma: no cover
                pass


__all__ = ["JobRun", "JobRunner", "JobStopped", "MAX_OUTPUT_CHARS"]
