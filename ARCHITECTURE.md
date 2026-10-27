# Architecture

Six layers under `src/archx_agent/`. Dependency direction is enforced by
`tests/conftest.py::test_import_matrix_is_respected`, which fails the suite on an
upward import until it is reviewed and deliberately allowed.

```
interfaces      CLI (and later GUI)
   │  may import: application, managers, helpers
   ▼
application     composition root, orchestration, routing decisions
   │  may import: initialization, managers, adapters, helpers
   ▼
initialization  startup prerequisite checks (currently: startup lives in application;
   │            the layer is empty and must earn its place or be deleted - see GAPS)
   ▼
managers        domain capabilities, schema, domain queries
   │  may import: adapters, helpers
   ▼
adapters        external systems: runtimes, providers, MCP, sandboxes, media
   │  may import: helpers
   ▼
helpers         config, storage driver, journal, tracing, redaction, tokens,
                paths, vectors, backup, exceptions, Result[T]
```

`helpers/sqlite_store.py` is the **only** module allowed to import `sqlite3`
(enforced by `test_only_sqlite_store_imports_sqlite3`).

## Core invariants

### Writes
Every durable write goes through `helpers/write_coordinator.WriteCoordinator`:

* one writer thread per database file, bounded queue;
* one transaction per operation containing **the journal row, the `applied_writes`
  marker and the data** - so a crash cannot commit half of it;
* `COMMITTED` is returned only after `COMMIT` returns;
* a duplicate `op_id` returns `DUPLICATE` without writing again;
* backpressure returns `PENDING` with an error - never a fake success;
* two-phase `begin_durable` / `complete_durable` exists for long operations, with
  `replay()` repairing interrupted intents on the next open.

Managers never open connections: they receive `SqliteStore` (reads) and the coordinator
(writes). New write kinds are registered with `WriteCoordinator.register(kind, handler)`;
kind names are persisted in the journal, so renaming one requires a deliberate migration.

### Ordering
Message order is `(conversation_id, seq)` allocated inside the write transaction. Trace
order is an `AUTOINCREMENT` sequence. **No query orders by timestamp.**

### Results and errors
* data-producing operations return `Result[T]` (`Ok`/`Err`);
* action-only operations return `None` and raise on failure;
* durable writes return `WriteReceipt` (committed / duplicate / pending / failed);
* domain errors derive from `helpers.exceptions.ArchxError` with stable `code`s;
  provider failures have precise subclasses (`RateLimitedError` is distinct from
  `ModelNotFoundError`, and `retryable` is explicit).

### Tracing
`helpers/events.EventStore` writes to a separate database file. Capture levels are
`summary` < `detailed` < `diagnostic`. Payloads are redacted **before** storage and
again on export. Correlation fields: `conversation_id`, `message_id`, `task_id`,
`run_id`, `parent_id`, `tool_call_id`, `project_id`. Causality uses `parent_id`, not
timestamps. We never store private chain-of-thought; goaled/decision/evidence/result
fields are recorded instead.

### Configuration
`helpers/config.py` declares every setting in one `SPEC` table with type, default,
validator and description. Precedence: defaults → `config.json` → `ARCHX_*` env
variables → explicit overrides. Unknown keys are hard errors naming the file and key.
`secret://env/NAME` and `secret://file/PATH` references are resolved at use time; secret
values are never printed, and logs/exports are grep-checked in tests.

### Paths
Anything derived from user input, imports, tool arguments or model output goes through
`helpers/paths.child_path` / `resolve_within`, which reject `..` traversal, absolute
escape, and symlink escape before any IO.

## Data model (SQLite)

| Version | Contents |
|---------|----------|
| 1 | conversations, messages, conversation settings |
| 2 | projects |
| 3 | memory: `memories`, `memory_history`, `memory_sources`, `memory_retrievals`, `learning_events` |
| 4 | context manifests, summaries |
| 5 | tasks, artifacts, version records, reproduction records |
| 6 | permission grants, tool runs, MCP servers/tools, extensions |
| 7 | jobs (scheduler) |
| 8 | research, learning goals/lessons, experiments, games, media jobs, datasets, transforms, training, remote, automations |
| 9 | embeddings, retrieval runs |
| 10 | model catalogue, capability tests, providers, provider usage, credential references |
| 11 | context proposals |

Migrations are applied in order with a **pre-migration backup**; a database whose schema
is newer than the build is refused (downgrade would corrupt data).

## The six memory systems

| kind | scope | injected | lifetime | extra rules |
|------|-------|----------|----------|-------------|
| active | conversation, task | yes | TTL (default 240 min) | needs a conversation or task; `slot` supersedes |
| permanent | global | yes | until edited | limited categories; credentials refused |
| archival | global, project, conversation | **never** | retention (default 365 d) | provenance required |
| project | project | yes | project lifetime | requires `project_id`; never mixes projects |
| solution | global, project | verified/reported only | retired when disproven | requires problem, solution, verification; `verified` requires evidence |
| learning | learner | yes | decays | requires topic; permanent labels refused |

Every record carries `source`, `provenance` (origin, recorded_at, ids), `confidence`,
timestamps, `version`, and a checksum used for duplicate detection. Edits snapshot the
previous row into `memory_history`. Whole artifacts live on disk with the path recorded
in SQLite and a checksum verified on read.

## Retrieval

`adapters/embedding_runtime.py` defines the provider protocol. Vectors are stored as
`float32` BLOBs with dimension **and model id**; comparisons across models are refused.
States are `embedded` / `awaiting` / `failed`; un-embedded items remain findable by
keyword, and degraded retrieval says so. Hybrid search blends semantic and lexical
signals; recency and usage bonuses are deliberately excluded from blended ranking.
Details and measured quality: [docs/RETRIEVAL.md](docs/RETRIEVAL.md),
[docs/RETRIEVAL_EVAL.md](docs/RETRIEVAL_EVAL.md).

## Context strategies

`managers/context.py` implements five strategies behind one budget model
(`context_limit - output_budget - reserve`, with a memory share). All of them:

* use the real tokenizer when available, otherwise a documented approximation that
  over-estimates;
* never truncate the current request - they raise `ContextOverflowError` with numbers;
* never drop pinned content silently;
* never orphan half of a tool call/result pair;
* record a persisted manifest (included, omitted, reasons, tokens) and a trace event;
* never delete history: summarising and excluding only affect the window.

## Providers, privacy and consent (M20)

`managers/providers.py` is the single catalogue of endpoints (local and cloud). It keeps
three things apart and never lets them drift into each other:

* **facts** - `base_url`, `is_local` (derived from a loopback URL), availability results
  from a real probe;
* **claims** - vendor privacy statements, with `claim_source` and `verified = 0`;
* **user metadata** - what the user confirmed (`privacy_confirmed`), consent
  (`consent_at`, `consent_version`), prices, quotas.

`Workspace.assert_remote_allowed` is the enforcement point, called from `runtime_for`, so
every interface (CLI today, GUI later, tools later) goes through it:

```
loopback endpoint                      -> allowed
remote endpoint + model.local_only     -> PermissionDeniedError
remote endpoint, no registered provider-> ConsentRequiredError
provider privacy unconfirmed           -> PrivacyUnknownError
provider consent missing/outdated      -> ConsentRequiredError
```

Consent is versioned (`CONSENT_VERSION`); bumping the version invalidates every stored
consent, and the error tells the user to confirm again. Quotas are enforced by Archx
before the request (`QuotaExhaustedError`); cost is only reported when the user supplied
prices, and is labelled an estimate. Usage events are append-only per request, so a
provider that starts failing shows up in the same table as the successful calls.

## Model runtime boundary

`adapters/model_runtime.py` defines `ModelRuntime` (`load`, `unload`, `health`, `chat`,
`stream`, `tokenizer`, `capabilities`). Implementations:

* `LlamaCppRuntime` - in-process GGUF; raises a precise error when the optional
  dependency or the file is missing (never pretends to work);
* `HttpChatRuntime` - OpenAI-compatible endpoint; classifies 401/402/404/429/5xx/
  timeouts into distinct domain errors with `retryable` flags;
* `ScriptedRuntime` - a labelled test double, disabled unless explicitly enabled.

The catalogue (`managers/models.py`) keeps **facts** (observed), **claims** (from
filenames/cards/providers) and **user metadata** (preferences) in separate columns, and
separates `verification_state` (`verified`/`inferred`/`unverified`/`unsupported`/
`unavailable`) from runtime state (`usable`/`disabled`/`missing`/`invalid`).

## Extension points

New capability = new manager + migration block + registered write kinds + adapter
behind a protocol if it talks to an external system. New interface = another module
under `interfaces/` that composes the same `application.Workspace`. No second copy of
storage, permissions, tracing, routing or task history is permitted.
