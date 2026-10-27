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
