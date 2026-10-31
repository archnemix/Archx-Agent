# Tools and permissions

Archx Agent does not have a "run anything" switch. Every tool declares what it needs, and
every protected operation is checked against a recorded decision. This document describes
how a request travels, what the records look like, and what is deliberately impossible.

## The pieces

| piece | where | what it owns |
|-------|-------|--------------|
| tool registry | `managers/tools/` | built-in tool specs, argument validation, execution order, run records |
| execution adapter | `adapters/local_tools/` | rooted file IO and permitted local child processes (not an OS sandbox) |
| permission centre | `managers/permissions/` | capabilities, grants, approvals, the check, denials |
| CLI | `tools`, `permissions`, `approvals` | the same operations for a human |

The adapter executes; it never decides. The registry decides *when* to ask and *what* it
asked for; it cannot create a grant. The permission centre is the only writer of
`permission_grants`, and it only writes when a user (or an approval the user made) is the
origin.

## Capabilities

| capability | risk | effect | what it allows |
|------------|------|--------|----------------|
| `fs.read` | low | reads | read and list files inside the tool roots, and measure their bytes |
| `fs.write` | medium | writes | create or modify files inside the tool roots |
| `fs.delete` | high | deletes | delete files inside the tool roots |
| `shell.run` | high | executes | run a local process |
| `net.fetch` | medium | network | fetch a text document over http(s) (M28) |

`net.fetch` was declared in M22 and implemented in M28, when Researcher Mode needed it.
Until then a grant for it could only be refused honestly; now the grant is what lets a fetch
happen at all. The tool refuses non-http(s) schemes, credentials in a URL, private/loopback
addresses (unless `tools.fetch_allow_private_hosts` is set deliberately), non-text content
types, redirect chains longer than `tools.fetch_max_redirects`, and bodies over
`tools.fetch_max_bytes`. Each redirect hop is re-checked, because the target is chosen by the
remote server.

## Built-in tools

| tool | capability | risk | dry run | inputs |
|------|-----------|------|---------|--------|
| `fs.read` | `fs.read` | low | no | `path`, `start_line`, `max_lines` |
| `fs.probe` | `fs.read` | low | no | `path`, `bytes` |
| `fs.list` | `fs.read` | low | no | `path`, `limit` |
| `fs.write` | `fs.write` | medium | yes | `path`, `content`, `create_parents`, `append` |
| `fs.delete` | `fs.delete` | high | yes | `path` |
| `shell.run` | `shell.run` | high | no | `command`, `cwd`, `timeout` |
| `archx.info` | *(none)* | low | no | - |

`archx.info` exists to show the difference: a tool with no capability runs without any
grant, because it touches nothing outside the process.

Unknown arguments are an error naming the accepted ones. Models hallucinate parameter
names; silently ignoring them would mean "the write did nothing and nobody noticed".

## The order of an execution

```
tools run fs.write --arg path=notes.md --arg content=hi
  1. validate   unknown tool / unknown argument / missing argument / wrong type -> exit 2
  2. dry run    requested on a tool without a preview -> exit 2
  3. preflight  hard denials that cannot be approved (shell denylist) -> exit 4, no request
  4. check      permission centre: grant? approval? deny? -> exit 4 + approval id
  5. consume    a single-use grant is spent *before* the work starts
  6. execute    adapter enforces the roots, caps and timeouts
  7. record     tool_runs row (start + finish), tool_call + file_change events
```

Step 5 happens before step 6 on purpose: a crash or an exception mid-operation must not
hand back a fresh single-use grant.

## `fs.probe` and why it is not `fs.read`

`fs.read` returns text. A binary file is refused rather than mojibaked into the transcript, and it
stays refused - the point of a second door is not to loosen the first one. `fs.probe` is that
second door: same capability (`fs.read`), same roots, same permission centre, but it returns bytes
and facts about them instead of a decoded body.

```bash
$ archx-agent tools run fs.probe --arg path=photos/holiday.jpg
format jpeg
bytes 48213
sha256 3f0c…  (whole file)
head ff d8 ff e0 00 10 4a 46 49 46
```

`bytes` caps how much is read (default 4096, bounded by `voice.max_probe_bytes`); a hash over a
head is labelled as one (`sha256_scope: head`) because a prefix hash is a different, weaker claim
than a whole-file hash and the row should not need a footnote. The measurement itself is
`application/media.py`'s job - the tool does not decide what a file is, it hands the mode the bytes
and gets out of the way; that keeps the same parser behind the CLI, the GUI and any future adapter.

## Durations and scope

| duration | valid while | needs |
|----------|-------------|-------|
| `once` (default) | the first check consumes it | nothing |
| `task` | the same task id is in context | `--task` |
| `conversation` | inside the conversation it was granted in | `--conversation` |
| `project` | inside the project it was granted in | `--project` |
| `persistent` | until revoked (optionally `--for N` hours) | `--confirm` |

Scope is checked, not assumed: a conversation grant in `demo-1` does not apply in
`other-1`, and a task grant does not outlive its task. The default is `once`, so an
approval buys exactly one operation; repeat work should be an explicit `permissions grant`.

`persistent` without `--confirm` is refused rather than silently shortened - the user
typed "persistent", so they get told what is missing.

## Approvals

When no grant covers an operation, the check queues one request per
(capability, subject, scope, context) and returns the id:

```
denied: fs.write: fs.write is not granted for 'fs.write'; approval ap_… is pending
approve with: archx-agent approvals approve ap_…
```

`approvals approve` mints exactly what was requested. There is deliberately no parameter
to change the capability, the subject or the scope: widening authority is a separate,
explicit `permissions grant`. Requests expire after `permissions.approval_ttl_minutes`
(60), and the queue is capped by `permissions.max_pending_approvals` (25) so a loop cannot
flood it.

`permissions check` answers the same question without creating anything.

## Rooted file checks and local command limits

File tools are confined to `tools.roots` (default: `<home>/workspace`), resolved with
`resolve_within`, which rejects `..` traversal, absolute paths outside the roots, and
symlinks pointing out of the tree. `shell.run`:

* splits the command with `shlex.split` and never uses a shell, so `;` and `|` are
  arguments, not a second command line;
* refuses programs on `tools.shell_denylist` (`sudo`, `dd`, `mkfs`, …) — this refusal cannot
  be approved;
* passes a minimal environment (`PATH`, `HOME` = the Archx home, `LANG`, `TMPDIR`), so a
  secret environment variables are not inherited; this does **not** prevent reading
  credential files available to the process's OS account;
* spools stdout/stderr to temporary files and reads bounded prefixes into memory;
* kills the POSIX process group at `timeout` and reports `timed_out: true`; Windows
  currently kills only the direct process. Deliberately detached children can escape.

There is no hard spool disk quota, OS filesystem jail, shell-language containment or
complete process-tree sandbox. `shell.run` starts in a checked directory but can access
anything the executing OS account can access. The denylist is an operator guardrail,
not a way to make arbitrary code safe. Integer size/time limits must be positive. Shared mechanics live in
`helpers/processes.py`; argv parsing, grants, roots and result formatting remain owned
by the tool/adapter. The helper cannot grant permission or turn an argv call into a shell.

## Records

| record | contents |
|--------|----------|
| `permission_grants` | capability, subject, scope, expiry, `granted_by`, `approval_id`, `use_count` |
| `approval_requests` | what was asked, by whom, why, status, decision, resulting grant |
| `tool_runs` | `seq`, tool, arguments, status (`running`/`succeeded`/`failed`/`denied`), result, error, duration, `permission_id`, `approval_id`, `dry_run` |
| trace `permission` | `check` (ok/denied), `grant`, `revoke`, `approval.requested/approved/denied`, `blocked` |
| trace `tool_call` | `running` then `succeeded`/`failed`/`denied` with the result |
| trace `file_change` | path, bytes, sha256, previous sha256, for real (not dry-run) writes/deletes |

A denial is evidence, not silence: exit code 4, a stderr line naming the approval, a
`tool_runs` row with status `denied`, and a `permission` trace event.

## Commands

```bash
archx-agent tools list
archx-agent tools show fs.write
archx-agent tools run fs.read --arg path=notes.md --conversation demo-1
archx-agent tools run fs.write --arg path=notes.md --arg content=hi --dry-run
archx-agent tools runs --limit 20
archx-agent permissions capabilities
archx-agent permissions check fs.write --subject fs.write
archx-agent permissions grant fs.read --subject fs.read --duration conversation --conversation demo-1
archx-agent permissions grant fs.write --subject fs.write --duration persistent --confirm --for 8
archx-agent permissions list --capability fs.read
archx-agent permissions revoke pg_… --reason "done"
archx-agent approvals list
archx-agent approvals approve ap_…
archx-agent approvals deny ap_… --reason "not now"
```

Exit codes: `0` success, `1` the tool ran and failed (or an environment error), `2` a usage
problem (unknown argument, bad duration), `4` refused (no grant, approval pending, path
escape, denylist), `5` unavailable subsystem.

## Settings

| key | default | meaning |
|-----|---------|---------|
| `tools.roots` | `[]` → `<home>/workspace` | directories tools may touch |
| `tools.max_file_bytes` | 2 000 000 | largest file a tool reads or writes in one call |
| `tools.max_output_bytes` | 200 000 | per-stream in-memory prefix cap (marked truncated); not a disk quota |
| `tools.timeout_seconds` | 60 | default process timeout |
| `tools.shell_enabled` | true | keep `shell.run` registered (it still needs a grant) |
| `tools.shell_denylist` | sudo, dd, mkfs, … | programs refused even with a grant |
| `permissions.default_duration` | `once` | duration for grants and approval requests |
| `permissions.require_confirmation` | true | `persistent` needs `--confirm` |
| `permissions.denied_capabilities` | `[]` | capabilities refused *even with a grant* |
| `permissions.approvals_enabled` | true | queue requests instead of failing outright |
| `permissions.approval_ttl_minutes` | 60 | pending approvals expire |
| `permissions.max_pending_approvals` | 25 | queue cap |
| `permissions.max_grant_hours` | 720 | longest `--for` |

## Current limits and historical scope

* No tool-calling loop in chat. The registry and the permission centre are ready for it;
  M25 workflows can explicitly execute tool steps; this is not an autonomous chat tool loop.
* No network tool at the time: `net.fetch` was declared only, and M28 implemented it when
  Researcher Mode needed real sources (see [RESEARCH.md](RESEARCH.md)).
* MCP/extension registration is implemented with trust and enable gates; see [MCP.md](MCP.md).
* File deletion is not recursive. `shell.run` does not interpret pipelines itself, but
  an explicitly invoked interpreter can execute code or launch background processes.
* `permissions check` does not plan ahead: it answers for one capability, subject and
  context at a time.
