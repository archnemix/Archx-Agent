# Task history, versions and reproduction (M24)

Three related records, each with one job:

| record | answers | table |
|--------|---------|-------|
| **task** | what work happened, in what order, and what came out of it? | `tasks`, `task_log`, `artifacts` |
| **version** | what did this content look like before, and can I get it back? | `version_records` |
| **reproduction** | could this task be run again, and what would stop it? | `reproduction_records` |

They are not a second history of anything: tool runs already point at a task
(`tool_runs.task_id`), trace events already carry `task_id`, and messages already have ids.
M24 adds the durable task record and the two things that were missing: **content versions**
and an **honest reproduction assessment**.

## Tasks

A task has a type (`chat`, `tool`, `agent`, `research`, `coding`, `training`, ...), a
status (`queued`, `running`, `completed`, `failed`, `cancelled`, `interrupted`), the
conversation/project/parent it belongs to, the model and tools it used, resource use,
input and output references, unresolved questions and a free-form metadata blob.

```bash
archx-agent tasks list                       # newest first, by insertion sequence
archx-agent tasks list --status failed --type agent
archx-agent tasks show <task>                # fields, timeline, tool runs, artifacts
archx-agent tasks start --type tool --title "rebuild the index"
archx-agent tasks log <task> --kind step --detail "half way"
archx-agent tasks complete <task> --summary "done"
archx-agent tasks fail <task> --error "provider outage"
archx-agent tasks cancel <task> --reason "not now"
archx-agent tasks question <task> --text "which dataset?"
archx-agent tasks resolve <task> 0
archx-agent tasks stats
```

Every chat turn is a task when `tasks.auto_record_chat` is true: created before the model is
called, completed only after the reply was stored, and marked failed with the error when
the turn raises. `ChatService.send(..., task_id=...)` attaches a turn to an existing task
instead - that is the seam M25 (agent workflows) will use.

### Ordering is a sequence

`tasks` rows are ordered by their insertion rowid, and a task's own steps live in
`task_log` with an `AUTOINCREMENT` key. Two steps in the same millisecond still have a
defined order, and `tasks timeline` never reorders itself when the clock is coarse.

### Terminal states are final

Completing, failing or cancelling a finished task is a `ConflictError`, not a silent
overwrite. Asking a task to complete twice is a bug in the caller and should be visible.

### Interruption is recorded, never guessed

A task left `running` by a process that no longer exists is marked `interrupted` when the
workspace next opens (`tasks.interrupt_stale_on_open`, on by default), with the reason
recorded. Three cases are distinguished:

* a task owned by **another live process** is left alone - that process may still be working
  (the warning says so);
* a task the user tracks **manually** (`archx-agent tasks start`) is left alone, because the
  CLI process that created it exits by design;
* everything else is interrupted.

A task that was killed is therefore never reported as completed, and a task another process
is still working on is never declared dead behind its back.

## Artifacts

An artifact is a **reference** to a file, not a copy:

```bash
archx-agent tasks attach <task> /path/to/report.txt --kind report
```

The row records the absolute path, the path relative to the workspace home (when it is
inside), size, MIME type and SHA-256. Attaching the same path again records a new content
version. Deleting the artifact row never deletes the user's file; if the file disappears,
`tasks show` and `artifacts` report `MISSING` and reproduction refuses to claim it can
recreate the output.

Artifacts live outside the database on purpose: a GB-scale output should not be duplicated
into SQLite.

## Versions

A version belongs to a subject (`artifact`, `project_file`, `prompt`, `memory`, `document`,
`report`, `dataset`, `config`, `other`) and to a subject id - for files, the absolute path,
so re-attaching the same file continues the same history.

```bash
archx-agent versions record document notes --content "first draft"
archx-agent versions record document notes --file ./notes.md --note "after review"
archx-agent versions list document notes
archx-agent versions diff document notes            # previous -> latest
archx-agent versions diff document notes --from v1 --to v3
archx-agent versions show document notes v1
archx-agent versions restore document notes v1      # writes v3, history intact
archx-agent versions subjects
```

Rules:

* **append-only.** Nothing is overwritten or deleted; `restore` writes a *new* version whose
  content equals the old one and records `restored_from`.
* **identical content is not a version.** Recording the same bytes returns the existing
  version with `created=false`, so history does not fill with duplicates.
* **ordinals are the sequence.** `v1`, `v2`, `v3` ... with a unique index per subject; a
  version label can be set explicitly (`--label draft-2`) but must not collide.
* **content may be absent, but never invented.** Above `tasks.max_version_bytes` (1 MiB by
  default) only the checksum and size are stored, and `content_stored=false` says so.
  Diff and restore refuse rather than diffing an empty body.
* **explicit content that is too large is refused**, not silently reduced to a checksum:
  there is nowhere else to keep it.

## Reproduction

```bash
archx-agent tasks reproduce <task>              # assess: fidelity, reasons, commands
archx-agent tasks reproduce <task> --record     # also store the assessment
archx-agent tasks reproduce <task> --verify <reproduction>   # recompute today
```

Three fidelities, and only three:

| fidelity | meaning |
|----------|---------|
| `exact` | every ingredient is present and deterministic: same model file, same tools, same settings, nothing simulated, no open question |
| `partial` | it can be attempted, but something will differ (remote provider, simulated model, consumed single-use grant, open question, changed settings, side-effecting tools) |
| `impossible` | something essential is gone (model registration/file, a tool, a dynamic server's trust, an output artifact) |

Exit code is `0` for `exact`/`partial` and **3** for `impossible`; `--verify` exits 3 when
the fidelity got *worse* than the record.

The record stores the environment (app version, Python, platform, schema, the settings that
change behaviour and their digest, model identity and file facts, tool states with
capabilities and grants, tool roots), the reasons, and **the commands that would replay the
task** - the real `tools run` invocations with the arguments that were actually used, and
the chat message that started it. The acceptance script re-runs one of those printed
commands to prove the command is real.

`--verify` re-derives everything: it reports the recorded and current fidelity, which
issues are new or resolved, and which settings changed. Removing a model after recording
turns `partial` into `impossible`, and the CLI says which issue appeared.

### What it deliberately does not do

It does not re-run the task. Running a task again is work (M25 workflows, M26 jobs), and a
record that claims to have reproduced something it did not run would be worse than no
record. It also does not claim `exact` for anything simulated: the test double performs no
inference, so its output cannot be reproduced even in principle.

## Settings

| setting | default | meaning |
|---------|---------|---------|
| `tasks.enabled` | `true` | record task history |
| `tasks.auto_record_chat` | `true` | one task per chat turn |
| `tasks.interrupt_stale_on_open` | `true` | mark dead processes' running tasks interrupted |
| `tasks.max_version_bytes` | `1048576` | largest content a version stores |

## Schema

Schema v15 adds `task_log`, the ordering/provenance columns on `version_records`
(`ordinal`, `size`, `restored_from`, `content_stored`) and `reproduction_records`
(`app_version`, `recorded_by`), plus indexes. It does not create a second tasks table: v5
already had one, and extending it keeps a single answer to "what happened?".
