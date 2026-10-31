# Architecture

Five layers under `src/archx_agent/`. Dependency direction is enforced by
`tests/architecture/test_architecture.py::test_import_matrix_is_respected`, which fails the suite on an
upward import until it is reviewed and deliberately allowed.

```
interfaces      CLI, local web GUI and MCP server
   │  may import: application, managers, helpers, adapter protocol values/metadata
   ▼
application     composition root, orchestration, routing decisions
   │  may import: managers, adapters, helpers
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

* one writer thread per coordinator/workspace, bounded queue; concurrent processes
  still rely on SQLite locking and bounded retries;
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
order is an `AUTOINCREMENT` sequence. Those causal streams do not rely on wall-clock
order. Other catalogue/listing queries do order by timestamps, often with an id tie-breaker.

### Results and errors
* helpers offer `Result[T]` (`Ok`/`Err`), but it is not a universal return convention;
* many manager/service reads return domain objects or mappings and raise on failure;
* action-only operations generally return `None` and raise on failure;
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
Protected file-tool paths go through `helpers/paths.child_path` / `resolve_within`,
which reject traversal and paths/symlinks outside the configured roots. This is not
an OS boundary for permitted subprocesses; model registration and explicitly trusted
execution paths have their own policies. Path checks do not eliminate filesystem races.

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
| 12 | provider privacy metadata and consent |
| 13 | tool permission centre: approvals, grants scope, run columns |
| 14 | MCP servers/tools and extensions |
| 15 | task history: task log, version ordinals, reproduction links |
| 16 | agent workflows: definitions and ordered step records |
| 17 | scheduler: job claims, attempts, deadlines, control, cursor, dedupe |
| 18 | research: runs and sources (plan, `planned_by`, coverage, checksums) |
| 19 | learning: sessions and attempts, plus the per-item schedule columns (M30) |
| 20 | explicit research completion/reopen state |
| 21 | coding sessions, changes and command runs |
| 22 | experiment declarations, runs and measured metrics |
| 23 | games, ordered moves and simulations |
| 24 | media measurements and human transcript provenance |
| 25 | text datasets, transforms, splits and export records |
| 26 | CPU training jobs, metrics and artifacts |
| 27 | portable remote jobs and attempts |
| 28 | execution targets, runs and synchronized files |
| 29 | scenes, objects, exports and renders |
| 30 | automation revisions, occurrence dispatch and watches |
| 31 | independent conversation setting keys, preserving legacy values |

Migrations are applied in order. Workspace upgrades attempt a pre-migration backup
when configured; backup failure is warned about and does not currently block migration. A database whose schema
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

`managers/context/` implements five strategies behind one budget model
(`context_limit - output_budget - reserve`, with a memory share). All of them:

* use the real tokenizer when available, otherwise a documented approximation that
  over-estimates;
* never truncate the current request - they raise `ContextOverflowError` with numbers;
* never drop pinned content silently;
* never orphan half of a tool call/result pair;
* record a persisted manifest (included, omitted, reasons, tokens) and a trace event;
* never delete history: summarising and excluding only affect the window.

## Providers, privacy and consent (M20)

`managers/providers/` is the single catalogue of endpoints (local and cloud). It keeps
three things apart and never lets them drift into each other:

* **facts** - `base_url`, `is_local` (derived from a loopback URL), availability results
  from a real probe;
* **claims** - vendor privacy statements, with `claim_source` and `verified = 0`;
* **user metadata** - what the user confirmed (`privacy_confirmed`), consent
  (`consent_at`, `consent_version`), prices, quotas.

`Workspace.assert_remote_allowed` is the enforcement point, called from `runtime_for`, so
model-using interfaces share the same runtime gate:

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

## Agent workflows (M25)

```
workflows row (definition = data)            managers/workflows/
   proposed -> approved -> running -> completed | failed | cancelled
workflow_steps rows (seq, kind, status, output, tokens)

AgentRunner.run(id)                          application/agent/
   model step    -> ChatService.send(...)      routing, fallback, usage, trace, task
   tool step     -> ToolManager.execute(...)   capability -> grant/approval -> run record
   memory step   -> MemoryManager.search(...)
   subagent step -> child task + conversation -> same executor (depth <= 2)
   budgets between steps: agent.max_steps / max_wall_seconds / token_budget / max_subagents
```

A definition cannot grant anything: every machine-touching step names a registry tool, so
the permission centre is unavoidable. A model-proposed plan is stored `proposed` and the
runner refuses it until a human approves; checkpoints are checked before the run starts so a
refusal cannot leave half a plan executed. The workflow row is the plan, the task row is the
run, and the conversation is the transcript - there is no fourth record.

## The GUI (M29)

```
interfaces/gui/server.py
   GuiApi    routes + auth + CSRF + error mapping        <- testable without a socket
   GuiServer ThreadingHTTPServer (loopback by default)
   assets/   index.html, app.js, view-*.js, style.css  <- no build step, no CDN
        │
        ▼  the same objects the CLI uses
   ChatService · SearchService · ResearchRunner · JobRunner · managers
```

The GUI has no layer of its own: it is an `interfaces/` module calling `application/` and
`managers/` exactly as `interfaces/cli` does. The import matrix test guards that direction,
so a GUI helper cannot reach into the database behind a manager's back.

Two properties are structural rather than promised. **Nothing is reachable without the
token**, because authentication is a single gate in `GuiApi.dispatch` and every route passes
through it. **A browser cannot write with a cookie alone**, because the CSRF check runs
before routing and the server never answers a preflight or sends an `Access-Control-*`
header - so a custom header is something only same-origin code can add.

`gui serve` flushes its banner (a piped stdout is block-buffered, and a token nobody can see
is not a token), and a non-loopback bind is refused without `--allow-remote` - the flag is
the only place where "expose this" is a decision rather than an accident.

## Learning Mode (M30)

```
learning goal/item/session/attempt  ->  managers/learning/   (rows, coordinator writes)
                                    ->  application/learning/ (grade, schedule, hint, plan)
                                    ->  CLI `learning ...`, GUI `/api/learning*`
```

* **Schema v20** adds `closed_at`/`closed_note` to a research run, so "the run finished" and
  "I am done with the question" stay two facts.
* **Schema v19** adds `learning_sessions` and `learning_attempts` and the schedule columns on
  the v8 `learning_lessons`. One migration, no renumbering.
* **The manager owns the rows; the service owns the policy.** `schedule()`, `grade_answer()`
  and `_rule_plan()` are pure functions of the item and the answer, which is why the tests can
  assert the whole schedule table without a clock.
* **A session is a task** (`tasks.create("learning", ...)`), so a sitting appears in the task
  history, has a status, and can be interrupted like any other work.
* **The GUI is a client** (M29 rule, unchanged): eight routes, all calling the same service,
  with `409 try_first` / `409 nothing_due` mirroring the CLI's exit 3.
* **Storage:** every write goes through the coordinator (`learning.*` operations), so an
  attempt row and the item's new schedule commit together; deleting a goal removes its
  children in one operation.

## Researcher Mode (M28)

```
research run                        application/researcher/
  plan     model JSON (validated) | deterministic rules | user subquestions   -> planned_by
  gather   local  SearchService over memory/conversation/task/workflow/file
           web    net.fetch tool -> permission centre -> adapters/net_fetch.py
  read     file text inside ws.tool_roots(), sha256, excerpt window
  judge    relevance = term coverage; stance needs a model AND quotes found in the excerpt
  write    managers/research/ : research_runs + research_sources (one row per attempt)
  report   extractive answer, every line [S<n>]; uncited model prose demoted
  verify   citations must resolve; claims must cite; CLI exits 3 otherwise
  record   report file (<home>/research/) + row + research task + artifact checksum
```

Three boundaries make this trustworthy rather than impressive. **The plan is data**: it is
stored, it names its author, and the first subquestion is the user's own question. **Every
source is a row**, so a failed fetch is visible rather than absent, and the excerpt that gets
quoted is hashed. **The report is checked after it is written** - `verify` is a separate
function that both the run and `research verify` call, so a hand-edited report is checked by
the same rule as a generated one.

`net.fetch` is the only new way out of the process. It lives in `adapters/` (all network code
does), is registered as a normal tool with capability `net.fetch`, and re-checks every
redirect hop's resolved addresses: a 302 to `169.254.169.254` is the classic way past a
one-time URL check. Private targets need `tools.fetch_allow_private_hosts=true` *and* the
grant, because those are different decisions.

`jobs submit research` registers the third job kind, which is the M26 extension point used as
intended: the queue knows nothing about HTTP or citations, it only knows the run is work that
can fail, and the run keeps its own record.

## Simple Mode and search (M27)

```
SearchService.search(query)            application/search.py
   sources (each owned by its manager, none copied):
     conversation  ConversationManager.search
     memory        MemoryManager.search        (semantic when an index exists)
     task          TaskManager.search          (new)
     workflow      WorkflowsManager.search     (new)
     project / artifact / tool                 (existing list/registry reads)
     file          ws.tool_roots() + SKIP_DIRS + NUL sniff + size/file budgets
   score_text(title, text, terms)  one function for every source:
     coverage of <= 8 query terms, +0.5 exact phrase, +0.75 any term in the title
   merge: sort (-score, -KIND_WEIGHT[kind], title) ; cap per_source ; cap limit
   report: hits, counts, scanned, skipped, degraded, elapsed_ms

SimpleMode.ask(line)                   application/simple.py
   detect_intent(line) -> (intent, why)
   chat      -> ws.chat.send            (M16/M19/M21)
   search    -> ws.search.search        recall -> memory only
   remember  -> ws.memory.add (permanent, preference|fact, provenance.mode=simple)
   status    -> router.route + memory.stats + tasks.stats + jobs.stats (read only)
   workflow  -> ws.workflows.create + ws.agent.run   (M25, M22 permissions apply)
   -> SimpleResult(intent, why, headline, detail, next_step, data)
```

Both are **read-only front ends over existing managers**: there is no search index, no second
store and no second permission path. That is what keeps "one search" cheap to reason about -
a hit is a row the owning manager already knows how to show, and its `ref` is a real command
(`archx-agent memory show mem_...`). A source that raises is caught: the report records
`degraded: ["<kind>: <reason>"]` and the remaining sources still answer, because a search
that fails completely because one manager is unhappy is worse than a partial answer that
says what it could not read. File search runs inside `ws.tool_roots()` (the M22 sandbox
roots), so it inherits the same boundary tools do and cannot read a path tools could not.

Simple Mode is deliberately *not* an agent: it has no free-form tool loop, no planning step
and no ability to grant a permission. Its refusals are `SimpleResult`s with a `next_step`
command, and the CLI maps an `approval_id` in the result to exit code `4`. The intent
classifier is a fixed set of rules whose matched rule becomes the `why` string shown to the
user - there is no hidden ranking to explain away.

## Job scheduling (M26)

```
jobs row            managers/jobs/
   queued -> running -> completed | failed
      ^   \-> paused -> queued            (cooperative, durable cursor)
      \----- requeued after a crash (attempts remain) / interrupted (they do not)

JobRunner.drain()   application/scheduler.py
   claim:  SELECT best queued row + UPDATE status= running   (one transaction)
   admit:  estimate fits the free share of scheduler.cpu_limit_percent / memory_limit_mb
   run:    command  -> child process in its own session, SIGKILL at the deadline
           workflow -> AgentRunner.run(control=, resume=)  step-boundary deadline check
   record: task timeline (job_started / job_paused / job_resumed / job_completed ...)
           result JSON (exit code, stdout, stderr, duration) + trace events
```

The queue owns *scheduling*; the task owns *history*. A job that runs adopts or creates
exactly one task, and every milestone it reaches is appended to that task's timeline, so
`tasks show` answer "what happened" without a second log. The claim is a single
transaction, which is what makes two workers safe; the deadline is absolute and stored,
which is what makes a hard timeout survive a crash. Pause sets a flag the runner reads at
a step boundary and records the cursor it reached; `resume` continues from that cursor and
never replays a step. See `docs/SCHEDULER.md`.

## Task history, versions and reproduction (M24)

```
chat turn / tool run / agent step
        |  TaskManager.create(kind, title)            managers/tasks/
        +-> tasks row + task_log rows (seq)          (owner: workspace instance + pid)
        +-> link(conversation, model, tool)          -> tool_runs.task_id, events.task_id
        +-> attach_artifact(path) -> checksum -> VersionManager.record  managers/versions.py
        |                                        -> version_records (ordinal, append-only)
        +-> complete / fail / (interrupt on next open if the owner died)

tasks reproduce <id> -> ReproductionManager.assess     managers/reproduction/
        reads: tasks, models, tools (+grants), mcp, extensions, config, conversations
        emits: fidelity (exact|partial|impossible), issues, environment, replay commands
```

The task is the join key: tool runs, trace events and artifacts already carry `task_id`, so
there is one history rather than four. A version belongs to a subject (file path, prompt,
memory) and is append-only; reproduction reads the *live* registry and model table rather
than a stored copy, which is the only way `verify` can tell that something disappeared.

## MCP and extensions (M23)

```
mcp add      -> record (transport, command/url, env/header KEYS)       managers/mcp/
mcp sync  -> connect -> initialize -> tools/list                       adapters/mcp_client/
                |                                                       (stdio subprocess or HTTP)
                +-> mcp_tools rows (always)  +-> registry specs (only if trusted AND enabled)
mcp call  -> ToolManager.execute("mcp.<server>.<tool>")                -> permission centre
                |                                                       capability mcp.call
                +-> client.call_tool -> remote result -> tool_runs + traces

extensions install -> manifest validated + hashed + stored             managers/extensions/
extensions trust/enable -> registry specs "ext.<ext>.<tool>"           capability from manifest
extensions call -> permission check -> subprocess (JSON in, JSON out)  adapters/extension_runtime.py
```

Two seams keep this honest:

* the **dynamic tool registry** (`ToolManager.declare_spec`/`unregister_spec`) is rebuilt
  from the database on open, so the decision ("trusted, enabled") is durable while the spec
  is derived;
* the **permission subject** is separate from the tool name for the MCP server, so a local
  grant never authorises a remote caller.

Layers: adapters speak protocols and execute; managers own records and decisions; the MCP
server lives in `interfaces` because it is another entry point into the same application.

## Tools and permissions (M22)

```
CLI / (later) a model's tool call
        |
        v
ToolManager.execute(name, arguments)          managers/tools/
  1 validate spec + typed arguments           -> ToolValidationError (usage, exit 2)
  2 refuse dry-run when there is no preview
  3 preflight hard denials (shell denylist)   -> PermissionDeniedError, no approval possible
  4 permissions.check(capability, subject, scope ids, consume=True)
        |                                       managers/permissions/
        +-- grant matches scope?  -> allowed, single-use consumed now
        +-- otherwise             -> queue one approval, refuse with its id
  5 LocalToolRuntime.<op>                      adapters/local_tools/
        roots + resolve_within, size/output caps, argv-only subprocess, timeout
  6 tool_runs row (running -> succeeded/failed/denied) + tool_call/file_change traces
```

Two boundaries matter here and are enforced by the import matrix and by tests:

* the adapter executes and never decides (it has no reference to the permission centre);
* the registry decides *when* to ask and cannot create a grant (only `PermissionManager`
  writes `permission_grants`, and only with `granted_by` of `user:*` or `approval:*`).

Grants carry a scope that is *checked* on every use (`once`, `task:<id>`,
`conversation:<id>`, `project:<id>`, `persistent`), and an approval can only mint the
capability, subject and scope that the user saw. Tool roots default to `<home>/workspace`
and every path goes through `helpers.paths.resolve_within`, which rejects traversal,
absolute escapes and out-of-tree symlinks.

## Routing (M21)

`application/router/` decides which model performs a task. Eligibility is a hard filter,
evaluated per candidate and recorded verbatim:

```
model usable?                    -> else "model is missing/invalid"
runtime can start here?          -> else "runtime unavailable: <reason>"   (no loading)
each required capability?        -> verified | inferred (unless router.require_verified)
                                  | unverified (chat only, or --allow-unverified)
                                  | unsupported/unavailable -> never
context window big enough?       -> else the numbers are reported
remote endpoint?                 -> needs router.allow_cloud AND the M20 privacy/consent gates
simulated test double?           -> needs --allow-simulated
```

Survivors are ordered by a deterministic score (capability level, task preference,
default, locality, failure history, simulated penalty). The decision - chosen model,
fallbacks, every rejection and its reason, plus the policy that was in force - is written
to the trace and returned to the caller (`ChatReply.model.routing`).

Fallback happens only for retryable provider errors, only to a model whose window can hold
the manifest already built, and it is always recorded: `model.failed`, `model.fallback`,
`fallback_from` on the reply, and a user-facing warning. Capability states are computed by
`ModelManager.capability_state` from recorded probes first, then the runtime baseline, then
declarations - a failed probe always wins.

## Model runtime boundary

`adapters/model_runtime.py` defines `ModelRuntime` (`load`, `unload`, `health`, `chat`,
`stream`, `tokenizer`, `capabilities`). Implementations:

* `LlamaCppRuntime` - in-process GGUF; raises a precise error when the optional
  dependency or the file is missing (never pretends to work);
* `HttpChatRuntime` - OpenAI-compatible endpoint; classifies 401/402/404/429/5xx/
  timeouts into distinct domain errors with `retryable` flags;
* `GeminiChatRuntime` - Google's `generateContent` / `streamGenerateContent`, a different
  wire protocol rather than a translation of the OpenAI one (see `docs/PROVIDERS.md`);
* `ScriptedRuntime` - a labelled test double, disabled unless explicitly enabled.

Every runtime that can reach a network endpoint is listed in
`Workspace.NETWORK_RUNTIMES`, and `assert_remote_allowed` gates all of them. Adding an
adapter without adding it there is the one mistake that would let a provider bypass the
consent rules, so the list is a single constant rather than a check per adapter.

The catalogue (`managers/models/`) keeps **facts** (observed), **claims** (from
filenames/cards/providers) and **user metadata** (preferences) in separate columns, and
separates `verification_state` (`verified`/`inferred`/`unverified`/`unsupported`/
`unavailable`) from runtime state (`usable`/`disabled`/`missing`/`invalid`).

## Extension points

New capability = new manager + migration block + registered write kinds + adapter
behind a protocol if it talks to an external system. New interface = another module
under `interfaces/` that composes the same `application.Workspace`. No second copy of
storage, permissions, tracing, routing or task history is permitted.

## Interface file responsibilities

The CLI entry point (`interfaces/cli/main.py`) dispatches commands. `parser.py` builds
its root parser; `support.py` holds shared formatting and permission-aware helpers.
Each module in `cli/commands/` owns one command's arguments and handler.

The GUI separates public imports (`gui/server.py`), authentication/dispatch (`gui/api/`),
HTTP transport (`gui/http.py`), socket lifecycle (`gui/lifecycle.py`), request/response
values and route metadata (`gui/protocol.py`), and feature endpoints (`gui/routes/`).
Route mixins do not authorize requests themselves: `GuiApi.dispatch` is the shared gate.
Keep these endpoint classes internal; do not invoke them to bypass dispatch.

Browser assets have no build step. `app.js` owns shell state, requests, navigation and
startup. `view-ui.js` owns DOM helpers, dialogs and Markdown. Other `view-*.js` files
register feature initializers, loaded in the order declared in `index.html`. The shell
passes an explicit shared-binding object, initializes views, then removes the temporary
registration array. The GUI smoke check follows the same script order. New scripts must
be listed in the page; the wheel includes every `assets/*.js` file.

Startup checks live in `application/workspace/`; there is no unused initialization
layer. Remaining large domain modules and the limits of this audit are listed in
[the repository audit](docs/AUDIT.md).


The architecture tests are collected from `tests/architecture/test_architecture.py`. The audit found
that their former location in `conftest.py` prevented collection, and fixed relative
import resolution as well as root-package aliases. Adapter protocol values and SDK
availability metadata are explicitly allowed at the interface boundary; network/IPC
orchestration remains application work. Loopback URL classification is a shared helper,
so adapters do not depend upward on the provider manager.


## Domain packages and review guides

Memory, context, learning, provider metadata, tasks, permissions, jobs, tools and
workflows, models and conversations now have feature packages with separate records, queries/policy and
transaction handlers. Workspace composition and the larger research/execution/coding/
dataset/training workflows likewise have focused internal parts. Geometry separates
creation, measurement and serialization; SDK transport separates vendor protocols.
Automation persistence belongs to managers, not application.

The internal parts share their composed object's collaborators; this does not promise
independent services or erase coupling. Public import surfaces remain explicit and
schema ordering remains a manifest, not filesystem discovery. See
[the technical reviewer guide](docs/TECHNICAL_REVIEW.md) for exact operation ownership,
and [the simple map](docs/CODEBASE_GUIDE.md) for an introductory explanation.

HTTP runtimes and local tools also have focused adapter packages. Shared completion
payload validators live in `adapters/chat_payloads.py`, below both HTTP/native runtimes.
Review status and active migration work are tracked in PLAN.md, not inferred from the
historical milestone descriptions above.

Conversation setting writes now use `conversation.setting` through the coordinator.
Schema v31 changes the key to `(conversation_id, key)` without changing migrations
v1–v30. The surviving legacy value is retained, including legacy orphan rows; values
already overwritten by the old implementation are unrecoverable. New writes require
an existing, non-deleted conversation. Workspace startup registers **all** manager
handlers before replaying intents, then performs job/task recovery and dynamic tool
restoration. Replaying an empty registry used to skip every pending operation.


## Shared process mechanics and remote-worker owners

`helpers/processes.py` owns disk spools, bounded output reads, waiting and timeout
termination. It owns no permission, roots, provider, extension trust or task policy.
Local tools, extension JSON execution and the worker's explicitly enabled shell keep
their own input validation, environments, domain errors and result schemas.

`application/remote_worker/` retains the old public imports while separating `worker.py`
(training job registry/identity), `protocol.py` (bundle validation), `execution.py`
(trusted shell), `files.py` (bounded rooted text transfer), `http.py` (framing/auth/routes)
and `server.py` (explicit serving lifecycle). Importing the package does not start a
worker or create a workspace. Worker jobs are not SQLite-backed durable scheduler jobs.


## MCP transport and state owners

`adapters/mcp_client/` preserves public imports while separating records, RPC queue/deadline
state, MCP result/discovery interpretation, binary stdio framing and finite HTTP JSON/SSE.
The only deliberate transport overrides are wire sending, cleanup and stdio liveness;
a collected architecture check rejects other silently shadowed operations. `managers/mcp/`
continues to own server configuration, trust/enablement, discovered tools, connection cache
and permissioned registry integration. Neither the transport queue nor session header is a
durable execution queue. A timeout is not proof that a remote side effect was cancelled.


## Broad responsibility batch

- `managers/mcp/`: composition, records/schema conversion, configuration, journalled writes,
  connection cleanup, discovery, registry restoration and invocation/status.
- `managers/extensions/`: composition, records, manifest validation, installation, lifecycle,
  registry/tool execution and journalled writes.
- `managers/reproduction/`: composition, records, environment/model evidence, tool/run
  caveats, assessment/commands, history/verification and journalled writes.
- `interfaces/mcp_server/`: public surface, schema identifiers, dispatch/permission subject,
  bounded stdio and bounded/authenticated HTTP. Non-loopback binds require a token;
  loopback remains optionally unauthenticated. No TLS/per-person authorization is implied.

The three manager moves preserve all 75 original methods and 13 globals exactly; changed
server methods are named separately. Browser transport failure is an uncertain outcome,
not permission to replay a prompt automatically. Its in-flight guard is page-local, not
server-side request deduplication.

## Worker listener policy and training capacity

`application/remote_worker/policy.py` owns credential shape and pre-bind authentication
requirements. `worker.py` owns locked training reservations, terminal records and capacity
snapshots; `http.py` authenticates before body parsing and maps full capacity to HTTP429.
`server.py`/remote CLI pass explicit limits and credentials. The CLI can resolve a token
from a named environment variable without echoing its value. Shared credentials do not
create per-person identities, encrypted transport, durable queues or command sandboxing.
