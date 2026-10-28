# The coding workspace (M31)

A session is a directory, a task, and a record of what happened in it. That is the whole model.
Everything below follows from it, and everything that is not in it was left out on purpose.

```bash
archx-agent code open --root . --title "fix the greeting"
archx-agent code read  <session> hello.py
archx-agent code write <session> hello.py --content 'print("hi")'
archx-agent code run   <session> "python -m pytest -q"
archx-agent code test  <session>            # the check the project calls "test"
archx-agent code diff  <session>            # the session's whole patch
archx-agent code show  <session>            # edits, runs, counts, the task
archx-agent code close <session> --note "shipped"
```

## The rule the mode exists to keep

**A session is not a way around the permission centre.** Reading a file is `fs.read`, saving one
is `fs.write`, deleting one is `fs.delete`, running something is `shell.run`. There is no private
filesystem path for the editor: the service calls `ToolManager.execute`, so the capabilities,
the grants, the approvals and the trace are the same ones `archx-agent tools run` produces.

What that looks like when it is not granted:

```text
$ archx-agent code write cs_… hello.py --file new.py
error: fs.write: fs.write is not granted for 'fs.write'; approval ap_… is pending
       (archx-agent approvals approve ap_…)
approve it with: archx-agent approvals approve ap_…
[exit 4]
```

The file is untouched, no change row exists, and the approval is a real pending request in the
Access panel. Over HTTP the same refusal is `403` with `code: approval_required`.

Two details worth knowing:

* **A write you may not read.** Editing a file you have `fs.write` for but not `fs.read` (a
  generated config, say) is allowed. The service asks the permission centre *without* creating a
  request, gets "no", and records the diff as "fs.read is not granted, so this diff shows the new
  content only". One save is one approval, not two.
* **A dry run is not offered.** `shell.run` has no preview, so the runner does not pretend to
  have one. The ledger records the attempt instead.

## The three tables (schema v21)

| table | one row per | carries |
|-------|-------------|---------|
| `code_sessions` | session | title, `root` (inside the tool roots), status (`open`/`closed`), `task_id`, `closed_at`, metadata |
| `code_changes` | edit | path, action (`create`/`modify`/`delete`), unified diff, `before_sha`/`after_sha`, added/removed lines, `artifact_id`, `tool_run_id` |
| `code_runs` | command | the command as typed, `argv` (what actually ran), `cwd`, status, exit code, duration, timeout, stdout/stderr, `artifact_id`, `replayed_from` |

Every edit attaches its diff to the session's task as an `artifact` (kind `diff`); `code diff`
attaches the session's whole patch (kind `patch`); a run with output attaches a log. That means
the ordinary task machinery works on coding work: `tasks show`, `tasks artifacts`, and
`tasks reproduce` all read the same rows.

**Why the task is `manual`.** The user works in a session across many commands, so each command
is a separate process and the process exiting is not the work ending. Without
`manual=True`, the second command would open the workspace, sweep the first process's `running`
task to `interrupted` (that is the correct behaviour for a chat turn), and the record would be
wrong. A manual task is never swept; closing the session completes it.

## The runner

```bash
archx-agent code run <session> "python -m pytest -q" --timeout 120
archx-agent code runs <session>          # the ledger, newest last
archx-agent code rerun <run>             # the same argv, in the same session, as a new row
```

Exit codes follow the run, not the API: `0` passed, `1` failed (the command's own non-zero), `3`
timeout, `4` refused. Over HTTP a failing command is `200` with `status: failed`, because the
request to run it succeeded; a refusal is `403` and a bad field is `400`.

A failed run also adds a question to the session's task (`… exited 1; fix or accept it?`), so
`tasks show` is where the loose ends are, not a second place to remember.

## Checks are the project's, not Archx's

A project declares what is worth running in `archx.checks.json` at the session root:

```json
{
  "checks": [
    {"name": "test", "command": "python -m pytest -q", "timeout": 120},
    {"name": "lint", "command": "python -m compileall -q .", "description": "syntax only"}
  ]
}
```

The parser is strict, because a typo in a test command is a wasted afternoon: unknown top-level
fields, unknown per-check fields, duplicate names, a name that is not `[a-z0-9_-]+`, a missing
command, and a timeout that is not a positive integer are all refused by name. Nothing is
auto-detected: Archx runs what you declared and does not decide what "tested" means for your
project. A project with no manifest gets the shape of one in the answer:

```text
$ archx-agent code checks <session>
no archx.checks.json in the session root; a check is a name and a command, for example
{"checks": [{"name": "test", "command": "python -m pytest -q"}]}
```

## What the mode does not do

No language server, no refactoring across files, no automatic fixing, no file watching, no
syntax highlighting beyond a monospace `<textarea>`. The GUI panel is a session list, a path
field, a read/save/delete row, a textarea, a command box and a diff — the same calls the CLI
makes. What was built instead is the boundary and the record, because those are the parts that
would be wrong to bolt on later.

## Where the evidence is

* `pytest tests/test_coding_m31.py` — 64 tests: the schema, opening and refusing to open, the
  permission behaviour (including the once-grant and the single-approval edit), edits and their
  diffs, deletes, the runner's statuses, named checks and manifest strictness, replay, the
  record, and the GUI as a client of the same service.
* `scripts/acceptance_m31.sh` — 48 assertions over a real socket with a real project, a real
  `pytest` run that fails and then passes, and a write in the page that the CLI then reads.
* `docs/VERIFICATION.md#m31-acceptance-transcript` — that run's output, verbatim.
