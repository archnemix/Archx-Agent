# Automations (M40)

Automations are durable trigger definitions, not execution grants. Created schedules are disabled.
They enqueue ordinary command jobs; the existing queue owns timeouts, tasks and recovery. Enqueueing
the occurrence, recording its job ID and advancing its deadline/revision share one transaction.
Concurrent ticks cannot enqueue the same revision twice. A schedule never overlaps its own queued,
running or paused job. Missed intervals coalesce to one occurrence; they are not replayed as a backlog.

```sh
archx-agent automation add example --argv '["python3","work.py"]' --interval 60
archx-agent automation add once --argv '["python3","work.py"]' --at 2026-12-01T10:00:00Z
archx-agent automation add watcher --argv '["python3","work.py"]' --watch input.txt
archx-agent automation enable example
archx-agent automation tick                 # enqueue only
archx-agent automation serve --once         # enqueue then run automation jobs once
archx-agent automation serve --poll 5       # explicit polling worker; Ctrl-C stops it
archx-agent automation disable example
archx-agent automation show example
archx-agent automation runs example
archx-agent automation list
```

Times require a timezone and are normalized to UTC. Intervals are integer seconds, 1–31536000.
Commands are explicit JSON argv arrays: there is no implicit shell. Working directories and watches
must resolve inside tool roots. Watch creation and every poll require `fs.read`; oversized files
whose probe hashes only a prefix are refused. Watches compare content hashes, not timestamps.
Deletion is a probe refusal, not a deletion-trigger event. Transient changes between polls may be missed.

Every scheduled command checks and consumes `shell.run` permission at execution time. Enabling a
schedule does not grant that permission. Revoking it after enqueue prevents execution. Jobs record
permission failures; enabling a schedule does not auto-approve its requests. A command that fails is
not automatically retried (max_attempts=1); crash recovery is provided by the existing queue but is
not an exactly-once guarantee for external side effects. Scheduling is exactly-once per accepted
revision; an external command must still be idempotent if an operator retries it.

Disabling stops future occurrences, not accepted queue work. Use `jobs cancel JOB_ID` to cancel
accepted work. One-shots disable on dispatch; explicitly re-enabling one schedules another attempt.
Runs display the job's live status/error/task, so a queued occurrence is never called completed.
`last_status` on the definition is dispatch history, not a summary of eventual job completion.

The GUI Automations tab creates disabled schedules, lists state, enables/disables, and ticks.
Use the Jobs tab/CLI or the explicit worker to execute them. Authenticated API routes:
`GET/POST /api/automations`, `POST /api/automations/tick`, and
`POST /api/automations/{id}/enable|disable`. There is no implicit daemon at workspace startup.

Schema v30 adopts the reserved automation tables, adding revision and job linkage. Scope excludes
cron/calendar/DST syntax, cloud triggers, email/webhook delivery, directory recursion, automatic
retry policy editing and a system-service installer. These are not advertised as working.
