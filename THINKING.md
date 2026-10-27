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
