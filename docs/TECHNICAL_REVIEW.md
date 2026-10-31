# Technical reviewer guide — structure, contracts and verification

This guide describes the current implementation layout. For a nontechnical map, use
[the simple codebase guide](CODEBASE_GUIDE.md). Feature-specific behaviour remains in
its feature guide; this document does not replace the requirements/gaps assessment.

## 1. Repository responsibilities

```text
src/archx_agent/
  interfaces/      entry points, parsing, HTTP transport and presentation
  application/     use-case orchestration and feature-local computation
  managers/        persistence, domain state and domain constraints
  adapters/        external protocols, runtimes and vendor-specific decoding
  helpers/         cross-domain infrastructure and reusable primitives
tests/             responsibility-grouped regressions and shared fixtures
scripts/           repeatable verification, setup and maintenance procedures
data/              small checked-in retrieval evaluation corpus
docs/              current guides, compact evidence and labelled historical records
.github/           CI configuration
.ci/               CI trigger input
```

The import matrix is collected and tested in `tests/architecture/test_architecture.py`.
Helpers cannot import upward; adapters cannot import managers/application/interfaces;
managers cannot import application/interfaces; application cannot import interfaces.
Interfaces may read adapter protocol values and SDK availability metadata. This is an
explicit exception, not permission to implement model/network orchestration in a view.
The guard checks static imports, including relative and root-package aliases; it is not
a proof against dynamic import tricks or runtime policy bypasses.

## 2. Public imports and internal implementation

Existing public entry points remain usable, for example:

```python
from archx_agent.application.workspace import Workspace, open_workspace
from archx_agent.managers.memory import MemoryManager
from archx_agent.managers.schema import MIGRATIONS, SCHEMA_VERSION
from archx_agent.adapters.sdk_transport import SdkTransport, transport_for
```

Package `__init__.py` files are declarative compatibility surfaces. They do not create
a workspace, discover migrations from a directory, or use wildcard imports. New code
should import the public surface unless it intentionally depends on an internal part.
Test doubles patch a function's canonical implementation module, not a re-export that
no longer owns that function's globals.

| Package | Composition/public type owner | Internal responsibilities |
|---|---|---|
| `managers/mcp/` | `manager.py` / `McpManager` | server records/configuration, writes, connection cache, discovery, registry restoration and calls |
| `managers/extensions/` | `manager.py` / `ExtensionManager` | records, manifests, installation, trust/lifecycle, registry/execution and writes |
| `managers/reproduction/` | `manager.py` / `ReproductionManager` | records, environment/model evidence, tool/run caveats, assessment, history/verification and writes |
| `interfaces/mcp_server/` | `server.py` / `ArchxMcpServer` | permission subject/whitelist and dispatch; separate protocol/schema, HTTP and stdio |
| `managers/models/` | `manager.py` / `ModelManager` | filename claims, records, local discovery, remote registration, metadata, capabilities, queries and writes |
| `managers/conversation/` | `manager.py` / `ConversationManager` | records, messages/context state, lifecycle, search/export, settings and writes |
| `adapters/http_runtime/` | `runtime.py` / `HttpChatRuntime` | transport/retry, status classification, completion/tool payloads, streaming and lifecycle |
| `adapters/mcp_client/` | public stdio/HTTP clients; RPC base and surface mixin | bounded queued sends, pending IDs/deadlines, records, paginated discovery, binary stdio cleanup, finite HTTP JSON/SSE and redirect refusal |
| `adapters/local_tools/` | `runtime.py` / `LocalToolRuntime` | limits, rooted paths, reading/writing, hashing, output clipping and process execution |
| `managers/memory/` | `manager.py` / `MemoryManager` | records, creation, writes, queries, ranking, lifecycle, retrieval, learner events |
| `managers/context/` | `manager.py` / `ContextManager` | builder, five strategy implementations, proposals, summary/manifest history, writes |
| `managers/learning/` | `manager.py` / `LearningManager` | goals, items, sessions/attempts, queries, row types, transaction handlers |
| `managers/providers/` | `manager.py` / `ProviderManager` | catalogue, privacy/consent, usage/quota, probes, administrative changes, writes |
| `managers/tasks/` | `manager.py` / `TaskManager` | lifecycle/recovery, timeline, artifacts, queries, writes |
| `managers/permissions/` | `manager.py` / `PermissionManager` | capabilities, grants, decisions, approvals, transaction handlers |
| `managers/jobs/` | `manager.py` / `JobManager` | submission/claim, lifecycle, controls, recovery, queries, writes |
| `managers/tools/` | `manager.py` / `ToolManager` | registry, input validation, permissioned execution/refusal, dispatch and history |
| `managers/workflows/` | `manager.py` / `WorkflowManager` | step validation, rendering, lifecycle, ordered history, queries, writes |
| `application/remote_worker/` | `worker.py` / `Worker` | accepted training identity/state, bundle validation, trusted shell execution, bounded text transfer, HTTP/auth/framing, explicit serving |
| `application/workspace/` | `workspace.py` / `Workspace` | lifecycle, lazy service access, embedding/tool construction and model access |
| `application/researcher/` | `runner.py` / `ResearchRunner` | plans, source acquisition, judgements, cited reporting and persistence orchestration |
| `application/execution/` | `service.py` / `ExecutionService` | probes, invocation generation, local/detached runs, remote requests, synchronization |
| `application/coding/` | `service.py` / `CodingWorkspace` | sessions/roots, edits/diffs/artifacts, command/check execution |
| `application/datasets/` | `service.py` / `DatasetService` | scan/measurement, cleanup, splitting/leak checks, exports/verification and queries |
| `application/training/` | `service.py` / `TrainingService` | preflight, execution, artifacts, evaluation and the two CPU algorithms |
| `application/geometry/` | function API in `__init__.py` | transforms, mesh, primitives, vectors, measurements, camera and format-specific exporters |
| `adapters/sdk_transport/` | `transport.py` / `SdkTransport` | registry, error classification, compatibility checks and vendor implementations |

### Why composed implementation parts?

Manager and service parts are internal mixins with one operation owner. They reuse the
existing instance's coordinator, store, configuration and collaborators. They do not
introduce competing instances, new persistence paths or a dependency-injection framework.
This keeps existing public APIs and method calls stable while separating files by job.

This is **not** a claim of independent service isolation: parts still call other methods
on the same object. Changing that coupling into explicit collaborator interfaces would
be a separate API/design change. Instantiate the composed public type, not an individual
mixin. `tests/architecture/test_module_boundaries.py` rejects silent method shadowing within these packages.

## 3. Critical flows and ownership

### Workspace startup

`open_workspace` delegates to the composed workspace. `lifecycle.py` resolves configuration,
creates directories, backs up/migrates the database, opens traces, creates coordinators,
constructs managers, registers write handlers and replays interrupted intents. `services.py`
provides application services lazily. `models/` owns availability, registration, privacy,
runtime construction and routing entry points. It is not another model catalogue.

### Durable writes

A manager validates input and submits a named operation through `WriteCoordinator`.
Its `writes.py` handlers receive the existing transaction wrapper. Journal, idempotency
marker and data commit together. Only `helpers/sqlite_store.py` imports the SQLite driver.
BEGIN/COMMIT contention is retried separately; caller code is not replayed by yielding a
transaction twice. External effects are not made atomic merely by storing their ledger.

`managers/automations.py` owns automation rows and atomic job/occurrence dispatch.
`application/automations.py` owns trigger polling, file probes and worker orchestration.
The old application import of `AutomationManager` remains a compatibility alias.

### Models and vendor clients

Application policy decides whether model use is permitted. The shared URL helper uses
literal IP classification/exact localhost, not a `127.` DNS-prefix heuristic. Vendor
modules only implement client setup, request/response shapes, tool calls and stream
parsing. Moving vendor handling does not bypass consent or make a remote endpoint local.

### Runtime payloads and failures

`adapters/chat_payloads.py` is a pure validator shared by HTTP and native adapters. It
checks response/usage types, tool-call shape and streamed deltas, reporting domain
errors instead of incidental Python exceptions. HTTP 429 quota codes take precedence
over retryable rate limits, even when the message is generic; authentication remains
non-retryable. Streaming errors are surfaced without replaying partial output.
Stream and tool requests now honor top-p, stop, seed and token budgets.

Native reload unloads/closes the previous model before attempting replacement; failed
loads leave no stale specification. Missing/tiny files and allocation failures show
unhealthy status. Filesystem inspection and native-close errors are mapped to domain failures; cleanup
clears loaded state even if native release throws. Native tests inject a fake optional module: they establish lifecycle
and error contracts, **not real GGUF inference or model quality**.

### Files and command execution

Coding, dataset, research and training services use the existing permissioned tools.
The execution package separates environment probes, invocation generation, running,
remote calls and push/pull ledgers. `LocalToolRuntime` remains a dataclass and validates
positive integer limits. Its process runner uses argv without a shell, closes stdin,
passes a small explicit environment, spools stdout/stderr to temporary disk files and
reads only bounded prefixes. Timeout kills the POSIX process group; Windows uses a
direct-process fallback. Detached descendants can escape group termination. There is
**no hard spool disk quota and no OS sandbox**. No detached run is relabelled as a
completed render/job.

### Geometry and Blender

Geometry computes vertices, faces, measurements, camera projection and export bytes.
Its Blender exporter emits scripts; `SceneService` requests actual rendering through
execution and checks fresh output. Geometry does not import bpy. Historical official
bpy/Cycles CPU evidence is separate from this refactor's ordinary stand-in tests.

### Shared child-process mechanics and worker boundaries

`helpers/processes.py` centralizes disk-spooled stdin/stdout/stderr, bounded prefix reads
and timeout cleanup. Callers keep policy: local tools and extensions use argv, while
worker execution explicitly requests a trusted shell. Extensions refuse oversized stdout
instead of parsing a valid-looking clipped prefix, validate UTF-8 and mark clipped stderr.
Spool files have no hard disk quota; Windows only kills the direct process, and deliberately
backgrounded/detached descendants can survive. No OS sandbox or revoked file permissions
is implied by a rebuilt environment.

Worker HTTP now validates framing before reading bounded JSON, closes each connection,
and applies a socket inactivity timeout. File transfer uses bounded reads/streamed entry
scanning, refuses outside symlinks, and validates the whole write batch before mutation.
I/O failure partway through a valid batch is not rolled back; filesystem races remain.
Accepted input is copied and its identity included before the result digest is computed.
Jobs remain in-memory; optional bearer tokens, quotas and public deployment are not made
safe by a structural split. Limits and configuration scope are in REMOTE.md.

## 4. Schema and compatibility checks

`managers/schema/__init__.py` explicitly orders migrations. Each released migration has
its own `vNN_*.py` file; filenames do not determine execution order. The first 30 versions,
names and SQL statement tuples retain SHA-256
`02f00c5fe7977fc04fd1caa8c625492805c08d7626bfb2ff2d6a901c19d04a98`
under the canonical serialization in `test_module_boundaries.py`.
Schema v31 is appended: independent conversation-setting keys replace the single-key
shape through an atomic table rebuild, retaining the surviving legacy row. Prior
values already overwritten by v1 cannot be recovered. No foreign-key constraint is
retroactively applied to legacy orphan rows. New settings writes validate the live
conversation and use a journalled transaction handler; upgrade, rollback, backup,
restart and durable replay are tested. Append versions, never edit old migration SQL.

The transformation inventory now covers 27 originals, with recorded preservation of
614 methods / 300 globals. It names 53 intentional original-method changes, 3 changed
global functions and 2 prior added transaction handlers separately. This batch compares
captured MCP/extensions/reproduction managers: all 75 methods / 13 globals are exact.
The captured MCP server preserves 3 methods / 1 helper; 5 server methods intentionally
change. Original wildcard exports remain identical. Earlier 23 transformation rows are
historical baseline evidence, not freshly rerun from missing snapshots.

## 5. Review and verification workflow

```bash
.venv/bin/python -m pytest -ra
.venv/bin/python -m pytest tests/architecture tests/system -ra
.venv/bin/python -m pytest --cov=archx_agent --cov-branch \
  --cov-report=json:/tmp/archx-coverage.json
.venv/bin/python scripts/review_documents.py --out docs/audit/documents.tsv
.venv/bin/python scripts/audit_repository.py --out docs/audit/files.tsv
.venv/bin/python scripts/coverage_inventory.py --input /tmp/archx-coverage.json \
  --out docs/audit/coverage.tsv
bash scripts/release_check.sh
ARCHX_JSDOM_DIR=/path/to/jsdom-install node scripts/gui_smoke.mjs
```

Development prerequisites: Python 3.11+, the `dev` extras (including pytest-cov),
and the optional `sdks` extras for the complete SDK matrix. Structural JavaScript
checks need Node; the GUI smoke needs a separately installed jsdom. Wheel checks
need `build`, `wheel` and modern setuptools. These are verification tools, not new
mandatory Archx runtime dependencies.

All 25 `scripts/acceptance_*.sh` procedures are also run locally. Seven early procedures
are transcript-style checks with exit status rather than assertion totals. SDK/protocol
stubs and simulated models remain labelled; they are not vendor/model-quality evidence.
The CI workflow's named stress/integration paths follow the reorganized test suites.

Read `docs/audit/coverage.tsv` per file, not just the overall percentage. It distinguishes
executed and missing statements/branches. Ordinary coverage may not combine CLI or other
child-process execution; acceptance results provide separate evidence. An uncovered line
is a review target, not proof it was never exercised; a covered line is not proof that
all outcomes were asserted. `docs/audit/files.tsv` is structural inventory, not manual
semantic certification. Final results and remaining risks are in [the audit](AUDIT.md).

## 6. Maintenance rules

- Put a new operation in the feature that owns its policy; do not add another global helper bucket.
- Keep transaction handlers in the manager feature and tool/network orchestration in application.
- Keep a single implementation owner per composed method; do not rely on inheritance order to hide duplicates.
- Do not split a cohesive file just to satisfy an arbitrary line count; do split unrelated I/O, policy and formatting responsibilities.
- Preserve public imports deliberately. Update internal test patch targets when ownership moves.
- Add tests for changed branches and run independent acceptance procedures, not just import smoke.
- Keep generated models, caches, build products, databases and temporary logs outside source control.


### Earlier local review gates (historical)

The previous documentation-first gate passed 2,095 tests and 401 wheel imports. The new
extension/worker batch records its own final results in
[the safety audit](AUDIT.md#extension-and-worker-safety-continuation) and
`docs/audit/checks.tsv`; earlier counts must not be substituted for the current tree.

Previous safety checkpoint: **2,189 tests**, 2 optional-SDK warnings; **25 passing acceptance procedures**
after a recorded M26 fixture failure and two successful barrier-based reruns. Independent
checks pass **91 stress / 11 integration / 39 architecture / 20 GUI tabs / 408 wheel
imports**. Coverage measures **78.0% statements / 58.1% branches** in 408 modules, not
complete line/branch or native-platform certification. Inventories cover 632 files,
61 folder roles and 82 Markdown documents.

### MCP caller deadlines versus OS cancellation

The RPC deadline begins before JSON submission and includes bounded queueing, blocked
stdin writes and HTTP exchanges. One transient daemon sender per client serializes wire
I/O/session headers and retires when idle. A timeout closes the client, drops queued bytes
and fails pending calls, without replaying requests. Stdio raw pipes avoid buffered-reader
close deadlocks, and POSIX cleanup targets the owned session group. Windows only handles
the direct child. Detached descendants or an uncancellable DNS/header operation can leave
background work alive after the caller returns: this is not a global resource governor.

Discovery has page/item/aggregate-byte and whole-list timeout budgets. Schema errors,
repeated cursors and sanitized registry-name collisions fail before manager updates.
Later registry/database I/O is not a single atomic discovery transaction. HTTP redirects
are refused rather than forwarding authentication; only finite JSON/SSE bodies are read.
MCP manager policy and inherited child credentials remain explicit in [MCP.md](MCP.md).

The completed MCP client gate is recorded in [the MCP audit](AUDIT.md#mcp-transport-lifecycle-continuation)
and `docs/audit/checks.tsv`; previous results above must not be substituted for it.

Historical MCP client gate: **2,299 tests**, 2 existing optional-SDK warnings; **25 acceptance
procedures**, **91 stress / 11 integration / 40 architecture checks**, **20 GUI tabs**,
**413 isolated-wheel imports**. Coverage: **78.2% statements / 58.5% branches** in 413 measured
modules. Inventories: **638 files / 62 folder roles / 82 Markdown documents**. Two stopped
intermediate broad runs are excluded. Five observed callback-argument notices are kept
because their interfaces require them; this is not a zero-findings or full semantic proof.


### Broad-batch verification and limits

The broad batch is tracked separately in [its audit](AUDIT.md#broad-responsibility-and-boundary-batch).
It combines manager responsibility extraction, MCP server framing/auth/defaults and GUI
uncertain-completion behaviour. The browser tests count POSTs under injected stream
failures, not just DOM rendering. The same-page guard and removal of automatic fallback
are not server-side idempotency or model cancellation. Server response size checks occur
after JSON serialization; they are not a hard serialization-memory quota. HTTP timeout
is inactivity, not a tool execution deadline. Loopback can remain unauthenticated.

Final broad gate: **2,338 tests**, 2 existing warnings; **25 individually passing
acceptances**, **91 stress / 11 integration / 44 architecture checks**, **20 GUI tabs +
4 stream scenarios**, **440 isolated-wheel imports**. Measurement: **78.4% statements /
58.8% branches** in 440 modules, not project completion. Inventories cover
666 files / 66 folders / 82 Markdown documents. The original acceptance batch failed M26,
its first barrier also failed, and the initial full run was stopped for an obsolete
GUI replay assertion. Only the corrected fixture and fresh full result close this gate.

## Remaining-owner contracts and honest percentage scope

The previous checkpoint named nine remaining large owners, now implemented together.
Their package composition preserves public imports and original explicit wildcard exports.
CLI grammar and branch bodies are checked independently; dispatch opens one workspace and
passes its existing services into the operation handler. No second workspace per handler.
The agent resolves the public Budget override at call time. GUI lifecycle no longer creates
a partial handler that was discarded before binding the real subclass.

`docs/audit/orchestration-contracts.json` stores 220 AST contracts: 137 methods, 51 global
definitions, 29 CLI branch bodies, two parser functions and one class attribute. Seven
originals have independently saved pre-change snapshots; the first generator interruption
lost the router/agent snapshot buffer. Their 33 contracts were recovered from untouched
copies, not falsely labelled independent before/after proof. Two intentional changes are
named: public Budget hook resolution and removal of the discarded GUI partial handler.
ResearchManager.tables is explicitly preserved and tested; method-only comparison missed
that class metadata initially. Focused tests first reported 325 pass/1 Budget-hook failure;
a temporary missing import caused 10 integration setup errors. Both are retained, not
presented as passing gates. A partial full/acceptance run was stopped and restarted.

The fixed 36-module ledger in `docs/audit/cleanup-progress.tsv` has a 27/36 (75%) accepted
baseline. At the intermediate checkpoint the nine new modules remained pending until final
regression/acceptance/wheel and inventory checks passed. Even 36/36 would mean only this published structural list is done;
it does not include every medium-sized owner, exhaustive semantic review or original-product features.

Final remaining-owner gate: **2,566 tests**, 2 warnings; **25 acceptances**,
**272 architecture cases**, **91/11 stress/integration**, **20 tabs + 4 stream scenarios**,
**492 wheel imports**. Fixed structural ledger: **75% → 100% (27/36 → 36/36)**. No
whole-product percentage is derived. Inventory: 721 audited files / 75 folders / 82 documents.

## Worker policy and admission continuation

Policy changes are explicit, not hidden in the prior responsibility refactor. `Worker`
validates 1–4096 non-whitespace printable ASCII token characters and positive integer
job limits before workdir creation. `make_server` rejects tokenless executable, hostname
and non-loopback binds before socket creation. Numeric-loopback training remains optional
auth. Handler credentials are captured as bytes; mutation cannot downgrade the listener.
A tokenless training listener refuses after an in-place execution upgrade.

Training admission reserves under the job lock, counts active running jobs and all retained
records, refuses full capacity with WorkerBusy/HTTP429, and rolls back thread startup
failure. Defaults: four running / 128 retained. Completion or failure frees a running slot,
not the stored record. Health exposes a locked capacity snapshot, not credentials/results.
This is neither an HTTP/exec concurrency governor nor hard RAM/disk limits. Validation is
before training admission, and concurrent HTTP validation remains outside this quota.
Jobs still have no durable recovery, eviction API or restart replay; explicit collection
and planned restart are required at retained capacity. HTTP token rotation requires a new
server. Direct local Python APIs retain trusted-host authority.

Final worker continuation: **2,616 tests**, 2 warnings, 25 acceptances,
91 stress / 11 integrations, 20 GUI tabs plus four stream scenarios and 493 wheel imports.
473 targeted tests include 50 new cases. Inventory: 723 files / 75 folders / 82 documents.
Statement/branch measurement: 78.8% / 59.2%, not completion. The separate
36-target structural percentage remains unchanged; safety limitations above remain open.


## Chat reasoning and browser regression ownership

`src/archx_agent/adapters/reasoning.py` owns optional provider reasoning validation and
incremental leading-think-tag separation. `src/archx_agent/application/chat_stream.py`
owns channel aggregation and callbacks; it does not route models or write storage.
ChatService retains routing, context, task and message ownership. Reasoning is saved in
message metadata; normal assistant content remains the final answer. No schema migration
is needed. HTTP `stream_events()` is optional; existing runtimes keep their string-stream
contract. SDK-specific separate reasoning channels are not universally implemented.

`src/archx_agent/interfaces/gui/assets/chat.css` now owns chat styling separately from the
shared stylesheet. The one sidebar contains recent history and collapsed advanced tools.
`scripts/gui_chat_browser.mjs` is an optional real-Chromium fixture test, separate from
`scripts/gui_smoke.mjs`'s DOM/fault-injection coverage. It expects a running GUI and optional
Playwright/Chromium npm tools outside the project. On minimal Linux systems, Chromium also
needs its system shared libraries or equivalent extracted runtime libraries; the end-user
GUI has neither a Chromium nor a Node dependency. Fixtures are not inference evidence.
