# Decision log

Every non-obvious decision and *why*. Newest last within each area.

## Process

**D1. Rebuild M01-M16 from the foundations.**
The repository contained one commit with a two-line README. There was no code to verify,
so the reported status could not be trusted; rebuilding was the only way to obtain a
codebase whose behaviour I can demonstrate. Recorded in `docs/VERIFICATION.md`.

**D2. Local-first means "no network by default", enforced in code, not documentation.**
Remote embeddings require `memory.remote_embeddings=true` plus a non-loopback endpoint;
cloud model fallback requires `model.allow_cloud_fallback=true` *and*
`model.local_only=false`, which config validation rejects together by default.

**D3. One database file for domain data, a second for traces.**
Tracing must never be able to block or corrupt the primary database, and trace retention
is a different policy from data retention. The cost is that a trace cannot join the
primary DB in SQL; correlation is by id, which is enough.

**D4. Sequence columns over timestamps.**
Wall clocks go backwards (NTP, VM snapshots, dual-boot). Messages use
`(conversation_id, seq)`; events use an `AUTOINCREMENT` sequence. Timestamps are for
display only. Ids are UUIDv7-style with a process-monotonic counter, so they sort even if
the clock steps back - but they are never the primary ordering.

**D5. A single writer thread per database.**
SQLite allows one writer; letting N threads race produces "database is locked" under
load. Serialising writes through the coordinator also gives one place for backpressure,
journalling and exactly-once.

**D6. The journal row, the `applied_writes` marker and the data commit together.**
This makes replay idempotent by construction: a crash either commits all three or none.
Two-phase `begin_durable`/`complete_durable` is available for operations that are too
slow to hold a transaction open, and `replay()` repairs intents on the next open.

**D7. `PENDING` is a first-class outcome.**
A queued write is not a success. The coordinator returns `PENDING` with an error under
backpressure and the application never presents it as saved.

**D8. Restore renames the current database aside instead of deleting it.**
Restores are the highest-risk operation; keeping the replaced file (plus its WAL/SHM)
means a wrong restore is recoverable. Verified by a test that restores and asserts the
aside file exists.

## Memory (M17)

**D9. One table, six kinds, per-kind rules in code.**
Six separate tables would duplicate governance (provenance, history, sources,
retrievals, artifacts) six times. A single `memories` table with a `kind` discriminator
plus per-kind validation keeps policy distinct while governance stays in one place.

**D10. Scope is explicit and validated per kind.**
Active memory must have a conversation or task; project memory must have a project id;
learning memory defaults to the learner scope. Unscoped "global" memory is only allowed
for permanent, archival and solution kinds, which is what makes project isolation
provable (`test_project_memory_isolation`).

**D11. Edits never overwrite silently.**
`update()` snapshots the previous row into `memory_history` and increments `version` in
the same transaction. "What did this say before?" is always answerable.

**D12. Duplicate detection: exact checksum + token similarity, with an escape hatch.**
Exact duplicates are refused with the existing id. Fuzzy duplicates use
`max(jaccard, containment)` - containment because short memories make Jaccard too
lenient (a one-word memory looks dissimilar to a sentence containing it). A `slot` means
"replace this logical value", so slot writes bypass similarity and supersede instead.

**D13. Solution memory cannot be marked verified without evidence.**
The value of a solution corpus collapses if unverified guesses are indistinguishable
from tested fixes. `verification` is a required field, `verified` requires
`details.evidence`, and only `verified`/`reported` solutions are injected into context.

**D14. Learning memory refuses permanent labels.**
A single failed attempt must not define a learner. `details.permanent_label` is rejected;
`learner_profile()` reports counts and requires repeated failures before suggesting
practice.

**D15. Archival memory is never injected, even when everything else is.**
"It is stored" and "it is current" are different claims. Archival items are reachable by
search and by explicit request only.

**D16. Artifacts on disk, metadata in SQLite.**
Large blobs in SQLite bloat every backup and slow WAL checkpoints. Whole artifacts are
written atomically under the artifacts root (path containment enforced, filename
sanitised) with a checksum in the row; reads verify the checksum and refuse tampered
files.

## Embeddings (M18)

**D17. Store dimension and model id with every vector; refuse cross-model comparisons.**
Two embedding models produce incomparable spaces. Silently mixing them produces
plausible-looking nonsense, which is worse than an error. Changing the model marks old
vectors stale and excludes them from search.

**D18. Brute-force scan with a pre-filter, and a documented scale limit.**
An ANN index is a second source of truth to keep consistent, and the corpus here is
small. Measured throughput in this environment is ~50k comparisons/s per core at 256
dimensions; the pre-filter (owner type, candidate ids, recency) keeps sets to a few
thousand. Beyond ~200k embedded objects, add an index - documented rather than silently
slow.

**D19. The default offline embedder is honest about being lexical.**
`archx-hash-v1` hashes words and character trigrams. It is deterministic, dependency-free
and measurable, and it is labelled `semantic=False` everywhere. The evaluation in
`docs/RETRIEVAL_EVAL.md` records both the numbers and the caveat.

**D20. Reject `VultronRetrieverPrime-Qwen3.5-8B` for text retrieval.**
It is an 8.4B visual-document retriever producing per-token 320-dim multi-vectors scored
with MaxSim over page images - not a pooled text embedding model, and not viable on CPU
in this environment. Fallback: hash embeddings offline; `sentence-transformers` with
`bge-small-en-v1.5` (384-dim, MIT, CPU-friendly) when available; OpenAI-compatible HTTP
embeddings as the opt-in remote path. Evidence in `docs/RETRIEVAL.md`.

**D21. Hybrid ranking excludes recency and usage bonuses.**
First version added recency/access-count bonuses on top of semantic scores; measured
nDCG was *worse* than semantic alone (0.70 vs 0.84). Recency is a freshness signal, not
a relevance signal, so blending now uses semantic + lexical overlap only, with pinned
content as a small prior. Measured result: nDCG 0.850, MRR 0.917.

## Context (M19)

**D22. Budget = window - output - reserve, with a memory share inside it.**
Memory retrieval competes with live conversation for the same window. The share is a
setting (`context.memory_budget_ratio`), and memory tokens are counted inside the same
manifest.

**D23. The current request is never truncated.**
Truncating the user's own message silently changes the question. If it does not fit, the
command fails with the exact numbers (`ContextOverflowError`).

**D24. Pinned content is protected, and protected content that cannot fit is an error.**
Dropping a pin silently is worse than refusing to build. The error message says what to
unpin.

**D25. Tool calls and results are one unit.**
Removing an assistant tool-call message while keeping its result (or vice versa) creates
a prompt the model cannot parse reliably. Removal operates on grouped units.

**D26. Compaction never deletes.**
Summarise/exclude only change the *window*. Summaries store their source range and can
be traced back to the original messages (`context.summary_sources`).

**D27. `ai_proposed` requires approval and records the applied manifest.**
The proposal is persisted before approval (`context_proposals`), approval is explicit
(`--proposal <id>`), and the manifest records `proposal_id`. Nothing is applied by
proposing.

## Model runtime (M15/M16)

**D28. Facts, claims and user metadata are separate columns.**
A filename claiming `Q4_K_M` is a claim. File size is a fact. "Preferred for chat" is
user metadata. Conflating them is how a system starts advertising capabilities it does
not have.

**D29. Provide a test double, keep it quarantined.**
Without it, nothing in this offline environment could be exercised end-to-end. It is
disabled unless `--allow-simulated` / `ARCHX_ALLOW_SIMULATED=1`, labelled in output and
traces, reports `semantic=False`/`simulated=True`, and is never counted as model
verification.

**D30. HTTP error classification is part of the contract.**
A 429 must never be reported as "model does not exist", and a 401 must never be retried.
This is tested against a real local HTTP server for 401/402/404/429(rate)/429(quota)/500
plus connection refusal.

## Providers and privacy (M20)

**D34. Three gates, not one, before data leaves the machine.**
`model.local_only` (a policy switch) + registered-provider (a catalogue) + confirmed
privacy and recorded consent (an informed user). Any single gate is easy to bypass by
accident: a policy switch gets flipped once and forgotten, a catalogue entry is
paperwork, and a consent dialog is click-through. Requiring all three means an accidental
remote call needs three separate deliberate acts.

**D35. Locality is derived from the URL, never from a label.**
The first implementation trusted `provider.provider == "local"`, and the acceptance run
showed a model registered as `local-http` pointing at `api.openai.com` reported
`local: true`. It is now computed from the host: loopback (`127.0.0.0/8`, `localhost`,
`::1`) is local, everything else is remote. Same rule for `is_local` on providers, and a
`kind=local` provider with a non-loopback URL is refused at registration.

**D36. Vendor claims and user confirmations are different columns.**
A provider's privacy terms cannot be a boolean Archx "knows". `privacy` holds what the
vendor documents (with `claim_source`), `privacy_confirmed` holds what the user read and
accepted, and `effective_privacy` reports which one supplied each field. This is the same
facts/claims/user-metadata split as the model catalogue, applied to something with legal
consequences.

**D37. A loopback endpoint needs no consent ceremony.**
Mocking a consent step for traffic that cannot leave the machine trains users to click
through consent dialogs, which is the opposite of the goal. `providers consent` on a local
provider records a trace event saying consent was not required rather than writing a
meaningless timestamp.

**D38. Consent is versioned.**
`CONSENT_VERSION` is stored with the consent. When the wording or scope changes, bumping
the constant invalidates every stored consent and the error tells the user to confirm
again. Without this, a consent given for "the old terms" silently authorises the new ones.

**D39. Quotas are enforced by Archx, not hoped for from the provider.**
A provider that accepts 1000 requests and then bills for them is not a quota. Archx
refuses the request when the declared daily ceiling is reached, and records usage per
request so the number is checkable.

**D40. No built-in price list.**
Prices change without notice, and a stale table produces confident wrong numbers. Cost is
estimated only from prices the user supplies, and is labelled an estimate. This is the
same reasoning as labelling hash embeddings non-semantic: a missing number is better than
a fabricated one.

**D41. Availability checks never send prompt content.**
`providers check` probes `GET /models` (the documented, content-free endpoint) and
classifies the answer. It cannot verify that completions work, and it says so in the
output.

## Routing (M21)

**D42. Eligibility is a hard filter; score only orders the survivors.**
The first implementation scored candidates and picked the best. The acceptance run showed
it choosing a GGUF file whose runtime (`llama-cpp-python`) is not installed, because a
model with a good capability state still scored highest. A score can be tuned and argued
with; an eligibility list with recorded reasons cannot. Order: filter, then rank.

**D43. Runtime availability is part of eligibility, not a post-check.**
Offering a model whose runtime cannot start is exactly "advertising a capability you do
not have". `Workspace.runtime_availability` answers without loading weights (import check,
file existence, endpoint configured, test double enabled), because a router must be cheap
and must not allocate gigabytes to answer "may I use this?".

**D44. `inferred` exists because "verified or nothing" would be useless offline.**
Our adapter implementing chat is a real fact about our code, but it says nothing about a
specific model file. Keeping `inferred` as a separate state - and offering
`router.require_verified` for users who want the stricter line - is more honest than
either treating adapter support as verification or refusing to run anything until a probe
passes.

**D45. A failed probe beats a claim, forever.**
Once a capability has been measured as broken, later claims (a filename, a user marking it
verified, a provider's marketing) cannot reinstate it. Re-probing creates a newer row, so
the state can only improve through measurement.

**D46. No fallback on non-retryable errors.**
A 401/402/404 or an unsupported capability is a fact about configuration or policy.
Retrying it on another provider would hide an auth mistake and could send the same data to
a second vendor. Only retryable failures (network, rate limit, 5xx) fall back.

**D47. Fallback is visible or it does not happen.**
The reply carries `fallback_from` and a warning, the trace records `model.failed` and
`model.fallback` with both model ids, the failing model's failure count increases, and the
conversation switches to the model that answered. A silent substitution would make a
working model indistinguishable from a broken one.

**D48. The router may not choose a remote model on its own.**
`router.allow_cloud` defaults to false and explicit `--model` overrides it (the user asking
for a specific model is not the router choosing). Consent and `local_only` still apply to
explicit choices. This keeps "automatic behaviour" and "sending data off the machine"
strictly separate.

**D49. Probes only for capabilities something can measure.**
`chat`, `tools` and `json` are probeable by driving the runtime and inspecting the answer.
`vision`, `ocr`, audio and video have no adapter in this build, so `models probe` rejects
them by name. A green tick on an unmeasured capability is the failure mode this milestone
exists to prevent.

## Tools and permissions (M22)

**D50. The default grant is `once`.**
The first default was `task`, which failed on the very first real run: there was no task
to scope it to, so the grant was either invalid or (worse) would have applied to
everything. "One approval, one operation" is the only default that needs no context and
grants nothing extra. Convenience is then an explicit `permissions grant`.

**D51. Refuse rather than quietly narrow.**
`--duration persistent` without `--confirm` was initially downgraded to the default. That
produces a grant the user did not ask for while reporting success. It is now an error that
names the missing flag. The same rule applies elsewhere: a substitution is either visible
(a warning, a recorded `fallback_from`) or it does not happen.

**D52. Spend a single-use grant before the work, not after.**
If the grant were consumed on success, a failing tool would leave the user a token they
believe was spent, and a crash would return it. Consuming first makes the accounting
conservative: the worst case is that the user approves again.

**D53. Record the attempt before running it.**
`tool_runs` is inserted with status `running`, then finished. If the process dies mid-tool,
the database still says "this was attempted at this time with these arguments" - the
audit trail's whole purpose. The sequence column is assigned inside the write transaction
(`MAX(seq)+1`) because ordering must not depend on wall-clock timestamps.

**D54. Errors close the run and re-raise.**
"Could not complete" (missing file, escape, timeout) must not look like "completed
unsuccessfully" (exit code 1). Both end as `failed` rows; only the first raises, and the
exception carries the run so the CLI can print the same evidence. A tool result is never a
bare boolean - `queued`/`started` is not `succeeded`.

**D55. The denylist is outside the grant system.**
Some programs (`sudo`, `dd`, `mkfs`, …) are refused before the permission check. Making
them approvable would mean the approval queue was the only thing between a model and a
disk wipe. The list is configurable, but editing it is a deliberate act, and the refusal is
reported as such ("this cannot be approved") rather than as a missing grant.

**D56. Approvals cannot be widened.**
`approve()` accepts no capability, subject or scope. The request is what the user saw; the
decision is yes or no. If they want a broader grant they run `permissions grant`, which is
a distinct verb with its own flags and its own trace event. This keeps "consent" a single
immutable fact.

**D57. No shell, ever.**
`shell.run` splits with `shlex.split` and executes an argument vector. A semicolon in a
command is an argument, not a second command. The consequence - no pipes or redirects - is
accepted: the alternative is a second, unreviewed command line hidden inside a string. The
environment is rebuilt rather than inherited, so a child process cannot read the agent's
own API keys.

**D58. An unimplemented capability is declared, not hidden.**
`net.fetch` exists in the capability list with "no tool implements this yet" in its
description, so a grant or a request for it is refused with a real reason. Omitting it would
make the refusal look like a typo.

## Agent workflows (M25)

**D78. A workflow is data; the executor is the only code.**
No expression language, no embedded shell, no plugin code in a plan. Every machine-touching
step names a registry tool, so the permission centre cannot be bypassed by writing a clever
plan. The cost is expressiveness: loops and branches wait for the scheduler. The benefit is
that a plan file from anywhere - a model, a colleague, the internet - is inert until a human
approves it and the grants exist.

**D79. Model steps reuse the chat path.**
`ChatService.send` already handles routing, capability checks, fallback, context, usage and
tracing. Reimplementing a "simple" model call for agent steps would have been a second
answer to "which model, and with what budget?". The side effect is that each run gets a
conversation - which is exactly the transcript a user wants to read afterwards.

**D80. A proposed plan is stored, not executed, and approval is a separate act.**
The model is a planner, never an authority. `agent plan` writes `proposed`; `agent run`
refuses without `--approve`; approving a plan still grants no capability (demonstrated: the
approved plan stops at `fs.write` with an approval id). Two independent decisions, because a
plan that sounds reasonable is not consent to run anything.

**D81. Checkpoints are checked before the run, not during it.**
A mid-run pause would need durable resumption; without it, "approve and continue" would
either repeat earlier steps (side effects) or resume from an in-memory position that a crash
loses. Refusing up-front is honest and cheap. Durable pause/resume belongs with jobs (M26).

**D82. Budgets are checked between steps, and they name themselves.**
Thread-killing a model call is unsafe; between steps is the last clean point. Each limit
(`agent.max_steps`, `agent.max_wall_seconds`, `agent.token_budget`, `agent.max_subagents`)
produces an error that states the limit and what was reached, because "the workflow failed"
without a number is unactionable.

**D83. A failed run is terminal; `rerun` is a new record.**
Turning a failed record into a successful one would erase the failure from history - the
opposite of M24's purpose. `agent rerun` creates a new workflow with `replaces` in its
metadata, so both attempts exist and the user consciously repeats any earlier side effects.

**D84. Subagents get their own conversation, not just their own task.**
Sharing the parent's conversation would let a long subagent answer crowd out the parent's
context and make the transcript unreadable. Separate conversations keep contexts isolated;
the task tree keeps the delegation visible; nesting is capped at two because each level
multiplies cost.

**D85. The planner refuses rather than repairs.**
If the reply has no JSON, invalid JSON, an unknown field or an unregistered tool, nothing is
stored and the planning task records why. A "helpful" repair would mean running a plan the
model did not write, and the user did not read.

**D86. Templates are rendered in two passes, on purpose.**
`{{input.*}}` is substituted when a template becomes a workflow; `{{step.N.output}}` is
substituted when that step runs (it does not exist yet at creation). The first pass therefore
touches only input placeholders - replacing everything would fail on a step reference, and
silently blanking it would run a prompt with a hole in it.

## Task history, versions and reproduction (M24)

**D68. The task is the join key, not a new log.**
`tool_runs`, trace events and artifacts already had a `task_id` column that nothing filled.
Adding a "run history" beside them would have created a second answer to "what happened".
Instead the task record was wired into the columns that already existed, and chat turns and
tool calls now fill them. One join, no reconciliation.

**D69. A task is created before the work, not after it.**
A record written on success only explains success. The chat path therefore creates the task,
then calls the model, then closes the task - and closes it as *failed* with the error when
the call raises. The cost is a task row for a turn that fails; the benefit is that failure is
visible in the history instead of absent from it.

**D70. Interruption needs an owner, not a clock.**
The first version marked any `running` task as interrupted on open, which made
`tasks start` impossible: every CLI command is a new process, so the task it had just
created was "stale" before the next verb ran. A timestamp has the same problem in reverse -
a long task looks dead, a crashed one looks alive. Tasks now record their workspace instance
and pid; the sweep interrupts only tasks whose owner is *gone*, leaves manual tasks alone,
and reports tasks owned by another live process instead of taking them over.

**D71. Terminal states are final, and that is a feature.**
Completing a completed task raises `ConflictError`. Silently accepting it would let a caller
overwrite an outcome (and its outputs) after the fact, which is exactly the history damage
this milestone exists to prevent. The error names the current state.

**D72. Versions are append-only; restore is a new version.**
Rewriting history would make "what did this look like last Tuesday" unanswerable. Restoring
writes a new row with `restored_from`, so both the state and the fact that someone went back
are recorded. The cost is rows; the alternative is a lie.

**D73. Unchanged content is not a version.**
Deduplicating by checksum keeps the history meaningful: every version is a change someone
can point at. Re-attaching an untouched file returns the existing version with
`created=false` rather than adding noise.

**D74. Large content is recorded as a checksum, not truncated.**
A half-document that looks complete is worse than an honest "content not stored". Explicit
content above the limit is refused (there is nowhere else to keep it); file content above
the limit records size and checksum, because the file itself still exists. Diff and restore
refuse to operate on a body that was never stored.

**D75. Reproduction is a claim with evidence, and `exact` is hard to earn.**
Fidelity is computed from the live environment: the model must be registered and
deterministic (not a test double, not a remote endpoint that can drift), the tools must
still exist, dynamic servers must still be trusted, output artifacts must still be on disk,
there must be no unanswered question and no consumed single-use grant. Anything less is
`partial`; a missing ingredient is `impossible`. This is why a simulated model can never be
`exact` - it performs no inference, so there is nothing to reproduce.

**D76. Reproduction records commands instead of running them.**
Re-running is work, and work belongs to M25/M26. Storing the commands (built from the tool
runs' recorded arguments and the message that started the turn) makes the record actionable
without pretending it was executed; the acceptance script runs one of the printed commands
to check that the claim is true.

**D77. Artifacts stay where the user put them.**
The database stores a path, a checksum and a version; it does not swallow the file. A
gigabyte-scale output must not double the disk cost, and the user's own file layout is not
ours to rearrange. `MISSING` is a first-class state, and it blocks a claim of exact
reproduction.

## MCP and extensions (M23)

**D59. Trust, enable and permission are three separate answers.**
Earlier drafts coupled "trusted" to "registered", which made it impossible to ask a server
what it offers without granting it power. Discovery is now always allowed; registration
needs trust *and* enable; calling needs a grant. Each is a separate verb with its own trace
event, and each denial says which of the three is missing.

**D60. The MCP server's caller is a different subject.**
`mcp-server` is not the tool's own name. Without that, a user's grant for their own
`fs.read` would silently authorise anything that could reach the server port. The cost is an
extra approval the first time; the benefit is that remote authority is never implied.

**D61. A whitelist, not the registry.**
Exposing every tool because it exists would turn "run a local MCP server" into "publish
`shell.run` to anything on the machine". The default list is read-only (`fs.read`,
`fs.list`, `archx.info`) and an unknown name fails at startup instead of being ignored.

**D62. Registration is derived; the decision is stored.**
Registered tools live in memory, so a new process would forget them. Rather than making
every command run `sync`, the workspace rebuilds the registry from trusted+enabled rows on
open. This also means the two views cannot disagree: `mcp servers` counts what the registry
actually holds.

**D63. `argv[0]` is the program; the rest is data.**
The first manifest validator rejected `/usr/bin/python3` for being outside the extension
directory - which rejects every real extension. Trusting an extension means trusting its
interpreter; it does not mean letting the manifest point data files at `/etc/passwd`. The
rule is now split exactly there, and an escape attempt is still refused.

**D64. Extension programs get a rebuilt environment; MCP servers inherit it.**
An extension is untrusted code that asked for one capability, so it gets PATH/HOME/LANG/
TMPDIR and nothing else. An MCP server is a tool the user chose and configured, and it
commonly needs its own credentials from the environment - so it inherits. The difference is
explicit because a reader will otherwise assume one of the two is a bug.

**D65. A remote `isError` is a failed run.**
MCP tool errors arrive inside a successful JSON-RPC response. Treating that as success
would put a green tick on "the tool refused to do it". It becomes a failed `tool_runs` row
with the remote message, and the CLI exits non-zero.

**D66. Protocol conversations need deadlines and answers.**
A client that waits forever is worse than one that fails: the user cannot tell a slow
server from a hung CLI. Every request has a deadline, and a server→client request (even an
unknown method) gets a JSON-RPC answer so the server can move on.

**D67. `config set` must accept the shape a setting declares.**
`config set mcp.server_tools '["a","b"]'` stored a string, and the server then iterated the
characters. List settings now accept a JSON array or a comma-separated list, and malformed
JSON is a usage error. A configuration value that is the wrong shape is worse than a
refused one, because it fails later and elsewhere.

## Scheduling (M26)

**D87. The queue is not a history, so it gets no log of its own.**
A job answers "what should happen next"; a task answers "what happened". Every job that
runs adopts or creates exactly one task and appends its milestones there. The cost is that a
job which never ran (still `queued`) has no timeline, only its row and trace events. The
benefit is that there is still exactly one place to ask "what happened", and no second log
to keep in step - the same rule that M24 applied to chat, tools and workflows.

**D88. A claim is one transaction, not a select followed by an update.**
Reading the best candidate and marking it mine must be atomic or two workers can win the
same row. The claim therefore runs *inside* the coordinator's transaction (the same
`WriteCoordinator` every other write uses). The test races six threads over 24 jobs and
asserts each is claimed exactly once; a lock in Python would only have protected one process.

**D89. A deadline is an absolute timestamp stored at claim time.**
Storing a duration and re-checking it invites "did it start when I thought?". The row carries
`deadline`; the runner kills the child at it and *any* workspace open calls `reap_expired()`,
so a deadline that passes while nothing is running still becomes a `failed` row instead of a
row stuck in `running` forever.

**D90. A running command refuses pause; a workflow pauses at step boundaries.**
Freezing a process tree (`SIGSTOP`) leaves sockets, temp files and children in a state the
rest of the system cannot reason about, and a resumed `sleep` would have to be told how much
time it already served. A workflow is ours step by step, so the honest split is: pause
between steps, refuse it for a child process, and say which is which in the error message.

**D91. Retries are for crashes, not failures.**
A job that ran and failed already had its side effects. Retrying automatically would repeat
them, and "the scheduler did it twice" is never a surprise a user wants. Requeueing happens
only when the worker *disappeared* (no result was recorded) and attempts remain; a timeout
fails the job outright because we do not know what half-finished work it left.

**D92. `paused` and `interrupted` are states, not errors - and the crash sweep must know it.**
The first acceptance run resumed a paused workflow into a *new* task, because opening a
second CLI process swept the paused run's task as "interrupted". The fix is a narrow one:
`JobManager.protected_task_ids()` names the tasks a paused or resumed job still owns and
`TaskManager.interrupt_stale(protect=...)` skips them. A durable record outranks a heuristic
about pids.

**D93. "The command ran" and "the work is done" are different exit codes.**
`jobs run` exits 3 when work remains (queued, running, or paused). Exiting 0 because no job
failed would let a paused queue look finished, which is the same mistake as treating a queued
write as committed. `0` means drained, `1` means something failed or was cancelled.

**D94. Admission control is arithmetic over declared estimates, with measurements recorded.**
`cpu_limit_percent` and `memory_limit_mb` gate claims using each job's declared estimate, and
`resource_observed` records the actual duration and peak RSS afterwards. Calling it a cgroup
would be a lie; calling it nothing would let four "heavy" jobs start at once. The honest
version is a hint plus evidence to correct the hint.

**D95. Resume reuses the task when it can, and never writes into a closed record.**
A resume continues the same task (same conversation, same step rows) because that is what
"continue" means. If the first attempt's task really was closed - a hard crash, a sweep
before the pause was recorded - the resumed run gets a fresh task with
`metadata.resumed_from`, so history is appended to, never rewritten.

**D96. The scheduler lives in `application/`, the queue in `managers/`.**
The manager owns rows, transitions and recovery; the runner owns processes, threads and
signals. That split keeps `managers/` testable without spawning anything and keeps the only
`subprocess` code in one file that can be reviewed as such.

## Simple Mode and search (M27)

**D97. Search reads the managers; it does not build an index.**
An index is a second copy of the truth with its own staleness, its own schema and its own
failure mode ("why is this result missing?"). At the sizes this app produces, scanning the
managers costs milliseconds and can never disagree with `memory list`. The cost is that
search time grows linearly and file search must be budgeted (`search.max_files`); the
benefit is that a hit is a row, and `report.counts` is a fact rather than a guess.

**D98. One scoring function for every source.**
Each source could have had its own notion of relevance, which is how a merged list becomes
unexplainable. `score_text` treats title and body the same way everywhere: term coverage
(so a full match is at least 1.0), a phrase bonus, a title bonus. `KIND_WEIGHT` breaks ties
only. The cost is that a source cannot express source-specific relevance (a task's status
match counts like a memory's body match); the benefit is that "why is this first" has one
answer, and `search --json` exposes the score.

**D99. A broken source degrades the report; it never fails the search.**
Each source returns `(hits, note, consumed)` and the caller catches exceptions per source.
"Nothing found" and "I could not look" are different facts: the first is `hits == []`, the
second lands in `degraded` with the reason and is printed. The cost is that a systematic bug
in one manager shows up as a note rather than a crash; the trace and the note are how it
gets noticed. Failing the whole search because the embedding index is missing would make the
feature useless in exactly the setup most users start with.

**D100. File search inherits the sandbox roots.**
`ws.tool_roots()` is where file tools are allowed to work. Searching anywhere else would give
Simple Mode a read primitive that `fs.read` does not have - a permission bypass dressed as a
convenience. So file search reads only there, skips noise directories, refuses files with a
NUL byte, and enforces size and count budgets so a stray `node_modules` cannot turn a
question into a minute of I/O.

**D101. Search never writes.**
No "recent searches", no counters, no trace event per query. A read path that writes is a
read path that can fail for write reasons, and search is the thing a user reaches for when
something is already wrong. The property is a test (`test_search_does_not_write_anything`),
not a comment.

**D102. Simple Mode is a front door with a stated reason, not an agent.**
It has no planning loop and no free-form tool access. Every intent maps to a call that
already existed, and `detect_intent` returns `(intent, why)` so the answer shows which rule
matched. The alternative - a model deciding what the user meant - would need a model to be
configured before the app can say "you have no model configured", which is circular, and it
would make the difference between "searched" and "answered from memory" invisible.

**D103. Refusals are results, and they carry the exact next command.**
No model, no grant, a checkpoint, a missing model for a model step: each returns a
`SimpleResult` with `headline` (what happened), `detail` (why) and `next_step` (the command
that would unblock it). The CLI exits `4` when the result contains an `approval_id` so a
script can tell "answered" from "needs a human". The alternative - raising - turned the
first acceptance run into a traceback, which is how this decision got made: a friendly front
end that crashes on its most common refusal is neither friendly nor honest.

**D104. `remember` writes a real memory, with the duplicate check intact.**
A separate "simple notes" store would have been easier and would have been a second memory
system - the thing M17 spent a milestone avoiding. Simple Mode writes `permanent` memory with
`provenance.mode = "simple"`, the category inferred only from unambiguous words
(`always`/`never`/`from now on` ⇒ `preference`, otherwise `fact`), and reports a duplicate as
"I did not store that" with the existing id. If the inference is wrong the user can edit the
memory; if the store were separate, nothing else in the app could find it.

## Researcher Mode (M28)

**D105. A research plan must name its author.** `planned_by` is `model` only when a model
returned JSON that parsed and validated; otherwise it is `rules` or `user`, and the report
says which. The alternative - one plan shape with no provenance - makes "the model decided
what to investigate" indistinguishable from "a template did", and the second one is what
happens whenever a model is unavailable or verbose.

**D106. The first subquestion is the question you asked.** A decomposition that never asks
the original question answers something adjacent and looks thorough. Putting the user's own
words first also gives the rules plan a natural anchor: the other facets are chosen by the
*shape* of the question (how/what/why/should) and read as English, because a plan nobody can
read is a plan nobody can correct.

**D107. A failed source is a row, not an omission.** 404s, binary pages, refused connections
and blocked addresses are stored with `status='failed'` and the error, shown by
`research sources`, listed in the limitations, and excluded from coverage. Omitting them
would make an empty report look like a searched one; storing them makes the difference
between "nothing exists" and "I could not look" visible, which is the same distinction search
(M27) makes with `degraded`.

**D108. Quotes are matched to the excerpt; unverifiable quotes are dropped.** A model asked
to justify a stance will happily invent a sentence. Matching each `quote` against the excerpt
it was given (whitespace-normalised substring) is cheap, deterministic, and turns a
fabrication into an empty claim list. The cost is that a legitimate paraphrase is also
dropped; the benefit is that every quote in a report can be found in the source.

**D109. Uncited prose is demoted, not deleted and not trusted.** The extractive answer is
assembled from quotes, so it is always citable. Model prose gets its own section, and any
paragraph without a resolving citation moves to "statements I could not tie to a source". We
tested this with the simulated runtime, which produces exactly such prose: the guard fires on
every run and the report stays honest. Deleting it would hide that the model was asked; a
separate section keeps the audit trail and refuses the claim.

**D110. Coverage is arithmetic over subquestions, and an empty run is `incomplete`.** Not
"completed with no sources" - the CLI exits 3 and the report's first line is "I found no
evidence". The temptation to call it success because nothing errored is the exact failure
this milestone exists to prevent.

**D111. `net.fetch` is a tool, not a helper the researcher calls.** Putting HTTP in the
researcher would have created a second way to reach the network that the permission centre
does not see. As a registered tool it inherits grants, approvals, denials and run records.
The private-address check is in the adapter, because it must apply to every hop of a
redirect - a check on the URL a user typed is not the same check.

**D112. Seed URLs come from the user; Archx does not crawl or scrape a search engine.**
A crawler needs a politeness policy, a robots.txt story, rate limits, and a search backend
(none reachable here). Pretending otherwise would ship a feature that fails silently offline.
Explicit seeds are honest, verifiable in the acceptance run (a real local HTTP server), and
they compose with M23's MCP tools if someone wants a search provider later.

## Storage and config

**D31. Unknown config keys are errors.**
A typo silently doing nothing is a support burden and a security risk (e.g. a permission
setting that never applies). The error names the file, the key and the expected form.

**D32. Secrets are references only.**
Archx stores `secret://env/NAME` / `secret://file/PATH`; the value is resolved at use
time, registered with the redactor, and never written to config, traces, logs or exports.
`secret://` references are treated as safe text (they are not the secret).

**D33. Pre-migration backups are automatic (and warn if they fail).**
A schema upgrade is irreversible in the general case. The backup is best-effort: failing
to back up warns loudly but does not block the upgrade, because blocking would make the
app unusable when the backup directory is read-only.
