# Scheduling: durable jobs, concurrency and hard deadlines

A **job** is an instruction to do something. It is not a task: tasks (M24) record what
happened, jobs say what to do. Every job that runs creates or adopts exactly one task and
writes its milestones onto that task's timeline, so there is still one history.

```
submit ──► queued ──claim──► running ──ok────────► completed
             ▲  │               │  └──error──────► failed
             │  │               ├──deadline─────► failed (no retry)
             │  │               ├──pause────────► paused ──resume──► queued
             │  │               └──cancel───────► cancelled
             │  └──pause──► paused
             └──resume / recover (after a crash)
```

## What is durable

| State | Where | Survives a process exit |
|-------|-------|-------------------------|
| queue position | `jobs.queue_seq` (assigned inside the enqueue transaction) | yes |
| claim | `status`, `worker`, `pid`, `started_at`, `attempts` | yes |
| deadline | `jobs.deadline` (absolute, computed at claim time) | yes |
| progress | `progress`, `message`, `cursor` | yes |
| result | `result` JSON (exit code, stdout, stderr, timings) | yes |
| pause intent | `control = 'pause'` | yes - any worker can see it |
| the work itself | the task timeline plus the workflow's step rows | yes |

## Claiming

`claim()` runs as one journalled write: inside a single transaction it selects the best
queued row (`priority DESC, queue_seq ASC`) that fits the free resources, and marks it
`running` with `attempts + 1`, this worker's name, this pid, and a deadline. Two workers
cannot claim the same row because the read and the write are one transaction; the test
suite races six threads over 24 jobs and asserts every job is claimed exactly once.

`claim(job_id=...)` narrows the claim to one specific queued job - "run this one now" -
without letting anything else jump the queue.

## Deadlines are enforced, not recorded

* A **command** job runs in its own session; at the deadline the runner sends `SIGKILL`
  to the whole process group and fails the job with `timed out after Ns and was killed`.
  The output collected up to that point is kept in `result`.
* A **workflow** job checks its deadline at every step boundary. A step that is already
  running is allowed to finish (a thread cannot be killed safely), which is stated
  plainly in `GAPS.md`.
* Any worker that opens the workspace calls `reap_expired()`, so a deadline that passed
  while nobody was running is still turned into a `failed` row rather than a permanently
  `running` one.

Retries are **not** automatic for failures or timeouts: the job already ran, and
repeating side effects is not a scheduler's decision. `jobs retry` is explicit (and
`--force` extends the attempt budget). Automatic retry exists only for *crashes*: a
`running` row whose pid is dead is requeued while attempts remain, otherwise it becomes
`interrupted`.

## Pause and resume

`pause` on a **queued** job is immediate. `pause` on a **running workflow** records intent
(`control = 'pause'`); the runner sees it before the next step and stops cleanly:

* the workflow stays `running` (it is mid-run, and the definition is not re-approved),
* the step rows already written stay,
* the job becomes `paused` with `cursor` = the number of finished steps,
* the task stays open - and `tasks.protected_task_ids()` stops the crash sweep from
  closing it, because the job still owns it.

`resume` requeues the job; the runner continues from `cursor`, reusing the outputs of
finished steps and never replaying one. If the first attempt's task was closed anyway
(a real crash, a sweep before the pause was recorded), the resumed run gets a fresh task
with `metadata.resumed_from` pointing at the lost one - history is added to, not rewritten.

A **running command cannot be paused**: it owns a child process whose children, sockets and
temp files would be in an unknown state. The scheduler refuses with a message that says so
and suggests cancelling.

## Concurrency and admission control

```
scheduler.max_concurrent_jobs   how many jobs may run at once (default 2)
scheduler.cpu_limit_percent     the CPU budget shared by running jobs (default 80)
scheduler.memory_limit_mb       the memory budget shared by running jobs (default 2048)
scheduler.job_timeout_seconds   default hard deadline (default 3600)
scheduler.max_attempts          attempts before a crash leaves a job interrupted (default 2)
scheduler.poll_seconds          poll/child-check interval (default 0.05)
scheduler.stale_after_seconds   when another live worker's claim is considered stale (900)
scheduler.recover_on_open       requeue jobs left by a dead worker when a workspace opens
scheduler.reap_on_open          fail running jobs whose deadline already passed
```

Each job declares a resource estimate (`cpu_percent`, `memory_mb`); the defaults are 25/256
for a command and 50/512 for a workflow. A job is only claimed when its estimate fits what
is left of the budget, so a queue of memory-heavy jobs is serialised by arithmetic rather
than by hope. The estimate is a *claim*; the observed duration and peak RSS are written to
`resource_observed` afterwards. It is a scheduling hint, not a cgroup: there is no kernel
enforcement of the memory limit yet (see `GAPS.md`).

## Kinds

| Kind | What runs | Notes |
|------|-----------|-------|
| `command` | a real child process (`argv` split without a shell) | exit code, stdout, stderr, duration and env overrides recorded; a non-zero exit is a failed job |
| `workflow` | an M25 workflow through the ordinary `AgentRunner` | keeps its own task, conversation, step rows and permission checks |

Adding a kind means adding a runner in `application/scheduler.py` and a default estimate;
the queue itself does not execute anything.

## What a job can never do

* grant itself a capability (workflow tool steps still go through `ToolManager`),
* run a model-proposed plan without approval (the job fails with `approval required`),
* claim a capability through a checkpoint (a job has no human to approve one),
* report a pause or a cancel as success (`paused`, `cancelled` and `failed` are distinct),
* hide a crash: a dead worker's job is requeued or marked `interrupted`, never `completed`.

## CLI

```bash
archx-agent jobs submit command "echo hi" --title greet --timeout 30
archx-agent jobs submit workflow wf_... --approve --timeout 600
archx-agent jobs queue                 # what would run next, in order
archx-agent jobs run                   # drain (exit 1 if one failed, 3 if work remains)
archx-agent jobs run --once --concurrency 4
archx-agent jobs list --status paused
archx-agent jobs show jb_...            # job fields, cursor, task timeline, workflow steps
archx-agent jobs logs jb_...            # stdout/stderr or the error
archx-agent jobs pause / resume / cancel / retry jb_...
archx-agent jobs stats
archx-agent jobs recover                # after a crash: requeue what a dead worker owned
archx-agent jobs reap                   # fail running jobs whose deadline passed
```

`jobs run` exit codes: `0` all completed, `1` something failed or was cancelled, `2` usage,
`3` work is still queued/paused (it did not finish, and saying "ok" would be a lie).

## Traces

Job milestones are traced under the existing `task` kind: `job.queued`, `job.started`,
`job.paused`, `job.pause_requested`, `job.resumed`, `job.cancelled`, `job.cancel_requested`,
`job.completed`, `job.failed`, `job.timed_out`, `job.recovered`, `job.retried`, `job.deduped`.
The task timeline carries the human-readable version (`job_paused`, `command_started`, ...).
