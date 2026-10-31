# Repository audit and requirements comparison

Audit date: 31 October 2026. Initial cleanup comparison baseline: `7ccce20`, after
the M01–M41 scoped roadmap closure; later continuations are recorded separately below. This report distinguishes recorded historical evidence from checks on the
cleanup. The cleanup is not a new claim that every product ambition is delivered.

Current verification: [chat usability correction](#user-reported-gui-correction) and
[worker policy and admission](#worker-policy-and-admission). Previous completed local results remain below.
Earlier checkpoint sections retain their historical measurements.

## Method and limits

The file inventory reads every Git-tracked and non-ignored new file sequentially,
records its purpose, size and SHA-256, and runs checks appropriate to its format.
Python is parsed for syntax, duplicate dictionary keys and overridden definitions;
Bash and JavaScript receive syntax checks; Markdown links are checked for existing
local file targets. The inventory excludes itself to avoid a self-referential hash.
See [the per-file inventory](audit/files.tsv). Reproduce it with:

```bash
python scripts/audit_repository.py --out docs/audit/files.tsv
```

This is **not** a claim of exhaustive manual semantic review or complete runtime
coverage of every line. Static inspection was followed by targeted review of module
responsibilities, configuration, imports, dead-code findings, storage, permission
boundaries, CLI arguments, GUI routes and assets, scripts, roadmap claims and guides.
The feature suites exercise real files, databases, subprocesses and loopback services;
protocol stubs and simulated models remain explicitly labelled. Neither a green test
suite nor reading every file proves all possible behaviour correct. Document-link
checks do not validate external sites or every Markdown anchor.

## Confirmed defects and cleanup

* Removed shadowed `gui.host`, `gui.port` and extension-directory settings. Effective
  defaults remain loopback, port 8765, and support for an ephemeral port 0.
* Removed the overridden duplicate `ToolManager.roots` and unreachable repeated
  provider lookup in workspace composition.
* Imported the missing `Iterator` type in SDK streaming code; annotations now resolve.
* Removed unused imports, dead bindings and constant-false expressions. Calls that
  validate objects, register handlers or write records were preserved.
* Fixed SQLite busy-commit retries. A transaction body now runs once; COMMIT retries
  keep the active transaction rather than rolling back and trying to yield again.
  Regression tests cover recovery and exhaustion without replaying caller effects.
* Fixed a privacy-boundary bug: a DNS hostname beginning with `127.` is no longer
  mistaken for loopback. Classification uses literal IP addresses or exact localhost;
  unspecified bind addresses do not qualify as local endpoints. The helper lives below
  providers/transports rather than introducing an upward adapter dependency.
* Made `automations.enabled` effective at dispatch, worker and queued-execution gates.
  It preserves definitions/queued jobs and does not kill already-running commands.
* Removed the unused workflow-validation argument and the nonexistent initialization
  layer. Architecture guards were not collected from `conftest.py`; they now run in a
  real test module, correctly resolve relative/root-alias imports, and reject upward
  imports. Interface access to adapter protocol values/availability metadata is now
  explicitly reviewed and documented in the matrix.
* Updated static GUI assertions, served-asset checks and acceptance scripts to inspect
  split view assets rather than assuming all browser code lives in `app.js`.
* Added a repeatable structural audit and ignored the local Ruff cache. No runtime
  dependency, model weight, generated wheel, database or credential was added.

Corrected documentation that claimed no queries use timestamps, all operations use
`Result`, and the browser never retains its raw token. The actual client uses tab-scoped
`sessionStorage` as well as a cookie; the guide now says so. Reserved wake-word/audio
preferences and `gui.theme` remain accepted for compatibility, but their descriptions
now state that no corresponding backend action exists (browser themes are local).

Callback parameters required by standard-library interfaces in `adapters/net_fetch.py`
remain intentionally present; Vulture reports those as unused. They are not removable
parameters. Historical run logs and reports are evidence, not redundant source code.

## Responsibility-based file layout

The previous CLI entry point was about 6,800 lines. It now dispatches commands; a small
root-parser module registers command modules, each of which owns its arguments and
handler. Shared output/permission helpers live in `cli/support.py`. The full help tree
was compared before and after the split and was unchanged.

The previous HTTP server was about 2,100 lines. It now owns sockets, authentication,
dispatch and static serving. HTTP values and route metadata live in `gui/protocol.py`;
feature endpoints live in `gui/routes/`. API errors and HTTP values remain available
from the original `gui.server` import path.

The previous browser script was about 3,400 lines. The shell now owns navigation,
requests and shared state; `view-ui.js` owns reusable UI/Markdown helpers; individual
views own their controls. Script order is explicit in the page, checked in the smoke
runner and packaged in the dependency-free wheel. There is no new bundler or framework.

The 5,136-line verification transcript was split into historical run chapters under
`docs/verification/`; the original file is an index with milestone anchors. Current
guides no longer present the first build environment as today's CI environment.
Historical reports retain their original results and have a clear historical notice.

### Second pass: domain and application responsibilities

The follow-up replaces 17 further concentrated modules with feature packages: memory,
context, learning, providers, tasks, permissions, jobs, tools, workflows, workspace
composition, research, execution, coding, datasets, training, geometry and SDK transport.
Every operation has an internal owner; public composed types remain importable from
their original module paths. These parts share existing state and collaborators; they
are not being advertised as independently isolated services.

Schema migrations now each own a versioned file behind an explicitly ordered manifest.
The first 30 migration names, versions and SQL tuples retain their original fingerprint.
Automation persistence moved into `managers/automations.py`; trigger polling and tool
access remain in application. AST extraction checks preserved 456 methods and 254 global
definitions, with reviewed return-annotation/private-record qualification adjustments.
The boundary suite checks public imports, method ownership and all-module import safety.

The 44 former root test modules are grouped into nine responsibility suites. Shared
repository paths no longer depend on each test's folder depth. CI's named stress and
integration paths follow the new layout. Current guides use current paths; historical
transcripts intentionally retain paths from their recorded runs.

The first extraction checks found the coding service's nested record needed a new
qualification after moving files; its focused permission/edit tests exposed that error
and it was corrected. Test relocation likewise exposed a module-patching assumption in
the architecture test itself; it now patches `sys.modules[__name__]` explicitly.
These were fixed before the final full validation, not hidden by deleting checks.

### What is still not claimed

Remaining larger modules include the learning CLI command, extensions, MCP,
reproduction, model router, workflow execution, research records, GUI HTTP server,
learning/experiment/scene orchestration, configuration and scheduler. Model catalogue,
conversation and HTTP/local-tool responsibilities have since been split. Exact current
sizes are in the inventory; the stylesheet, decision log and some regression files
are longer. Splits should follow responsibilities, not arbitrary line-count targets.
This is not a claim that every file is tiny or every branch has a complete test oracle.

Use [the simple codebase map](CODEBASE_GUIDE.md) and [the technical reviewer guide](TECHNICAL_REVIEW.md)
for folder ownership, internal coupling, public interfaces and review commands.

## Requirements: what is genuinely delivered?

The broad product areas are recorded in README, PLAN, MODES and the decision log.
There is no separately versioned, user-approved original requirements baseline in the
checkout. Therefore the following is a comparison against those recorded ambitions,
not a fabricated line-by-line certification against an unavailable original brief.

| Product area | Implemented and exercised | Missing, narrower or not established |
|---|---|---|
| Local-first foundation | configuration, SQLite persistence, journalling, replay, traces, secrets references, backup/restore | universal OS/interpreter certification; hostile multi-user hardening |
| Conversation and model access | persistent chat, streaming, routing, provider/consent gates, optional vendor clients | quality guarantees for arbitrary models; every provider/model version |
| Memory and context | six memory kinds, versioning, retrieval budgets, five context strategies | default embeddings are lexical; optional semantic quality is not established by combined CI |
| Tools, approvals and extensions | tool registry, capability grants, stdio MCP, trusted extensions, recorded denials | tools/local commands are not an OS-level untrusted-code sandbox |
| Tasks, workflows and jobs | artifacts, content versions, reproduction assessments, approved plans, subagents, queue recovery/deadlines | reproduction can be partial/impossible; not every nondeterministic task is replayable |
| Research | local documents and supplied URLs, plans, citations, coverage and explicit completion | general web search/crawling; autonomous experimental research |
| Learning | goals, questions, hints, exact/self grading and spaced practice | model grading, media teaching and richer learner profiles |
| Coding and experiments | directory sessions, permissioned edits/runs, checks, parameterized experiments and recorded metrics | full IDE/debugger/LSP; arbitrary safe untrusted execution |
| Play | three rule-checked games and one reproducible simulation | general game engines or open-ended simulations |
| Voice and media | byte-level measurements, provenance and human-written transcripts | speech recognition, synthesis, microphone/wake-word pipeline, OCR/video |
| Data preparation | text-corpus filtering, deduplication, stable splits, manifests | general multimodal/tokenized training-data pipeline |
| Training | real small n-gram and centroid CPU trainers, metrics and artifacts | transformer training, LoRA/fine-tuning, GPU orchestration |
| Remote compute | approved bundles, compatible worker protocol, returned artifact verification | cloud provisioning, managed credentials and production fleet operation |
| Execution targets | recorded backend commands, probes/refusals, remote push/pull | universal Docker/Windows/WSL/VMware/VirtualBox installation validation; snapshot isolation |
| Blender and scenes | six primitives, measured meshes, OBJ/STL/SVG/script export, task linkage, actual Blender CPU render evidence | general 3D editor, materials/animation, arbitrary imported geometry, async/recoverable render queue |
| Automations | interval, once and file-hash polling, atomic dispatch, permission recheck, explicit worker | cron/timezones, external events and managed background service |
| Distribution | dependency-free core wheel, packaged GUI and isolated-wheel smoke | published release, signed installers and desktop/OS certification |

**Conclusion:** the scoped roadmap has no open milestones; the broader product still
has meaningful gaps. Scope reduction and an honest refusal are useful behaviour, but
are not substitutes for the absent capability. Completing those gaps requires explicit
prioritization and acceptance criteria, not changing a roadmap label.

## Was Blender actually checked?

**Yes, in the recorded CI—not as a desktop UI session.** CI #26, run `40914694127`
on implementation `48dd607`, installed official `bpy==4.2.0` plus native libraries
and rendered a cube through Blender's actual Cycles CPU engine. It produced a 64×64
PNG, 4,883 bytes, SHA-256
`ffe179acb67b8ab98b66feee3e6012151ea3a03292fa2e394e82ec87ea215e1f`.
The hash identifies that output; it is not a cross-machine determinism guarantee.

The operating path is:

1. Create a scene and add primitive objects; validate the document and measure meshes.
2. Grant the required file/command capabilities, enable execution and configure Blender.
3. Export OBJ and a Blender Python script that imports the mesh and sets camera,
   lighting, resolution and renderer.
4. Invoke the configured executable through the execution service with background
   flags. The CI adapter imports real bpy and executes that generated script.
5. Require a fresh PNG, record its bytes/hash and execution outcome, and attach the
   result to the scene's task when one is associated.

The fresh local audit environment did **not** install bpy or launch desktop Blender.
Its normal renderer regression/acceptance path uses a labelled stand-in to test argv,
refusal and output handling. These are separate kinds of evidence. Standalone desktop
binaries, other Blender versions, Eevee and GPU rendering remain unverified. Full
setup and commands are in [Scenes and Blender](SCENES.md).

## Verification of this cleanup

The earlier second-pass gate (before the runtime/domain continuation below) passed:

| Check | Final result |
|---|---|
| Full pytest suite with branch measurement | **1,985 passed**, 2 optional Cohere/Pydantic deprecation warnings, **477.50 seconds** |
| All acceptance procedures | **25/25 exit codes 0**; seven older transcript-style procedures do not publish assertion totals |
| Isolated dependency-free wheel | CLI/schema/assets pass; **364 filesystem-enumerated Python modules import** without optional runtime dependencies |
| GUI smoke | **20 tabs**, forms/panels render, no page errors |
| Architecture/import/ownership regressions | Collected in the full suite; **30 targeted checks** also pass independently |
| Selected Ruff correctness checks | **0 findings** across source, tests and scripts |
| Extraction contracts | **456 methods and 254 global definitions preserved** across 17 modules, with the documented qualification/type adjustments |
| Released schema contract | Versions 1–30 and SQL fingerprint unchanged |
| Source responsibility documentation | All **364 Python source modules** have module-level responsibility documentation |
| Structural file and folder inventories | Final inventories record every current non-generated repository file/folder; self-hash excluded |
| Vulture review | Four required callback-argument notices in `net_fetch.py`, intentionally retained |

### Measured coverage, not exhaustive verification

That earlier full run measured **77.3% statement coverage** and **56.9% branch coverage**
across **364 Python source files** (20,702/26,789 statements;
4,666/8,202 branches). Coverage.py's combined figure is
72.5%. The per-file statement/branch counts and missing line ranges are in
[coverage.tsv](audit/coverage.tsv), now refreshed with the continuation run below. Ordinary measurement does not combine every CLI/worker
child process; separate acceptance procedures exercise those paths. This explains part
of the CLI shortfall, not all missing coverage. **This is not 100% verification.**

Non-interface review targets include HTTP-runtime error/stream handling, native llama.cpp
integration, local-tool refusal/platform branches, conversation/reproduction edge cases,
MCP and worker recovery. The native runtime requires separately available weights/libraries;
Windows/VM/cloud certification is not supplied by a local Linux test run. Coverage should
guide additional tests rather than justify deleting unexercised safeguards.

The first import-smoke implementation used `pkgutil`, which skipped the implicit managers
namespace. The second pass caught this blind spot, made the manager layer an explicit
package, and changed both source and wheel checks to enumerate actual Python files.
The tightened checks and final full run above were performed after that correction.

Folder ownership is in [folders.tsv](audit/folders.tsv); per-file structure/hashes are in
[files.tsv](audit/files.tsv); extraction checks are in
[refactor-contracts.tsv](audit/refactor-contracts.tsv); compact outcomes are in
[checks.tsv](audit/checks.tsv). The inventories do not pretend every file received
exhaustive manual semantic analysis or every possible execution was observed.

Historical **CI #26 belongs to the pre-audit implementation**. No fresh real-model,
real-Blender or GitHub CI run has been performed for this refactor. Local stand-in and
protocol checks do not silently replace those external integration gates.

See [the document guide](DOCUMENT_GUIDE.md) for every document's human-readable name
and purpose. Raw local logs are temporary; this report records final outcomes, and the
inventory is repeatable rather than a claim that stale hashes remain current forever.

## Runtime and domain continuation

This section records the earlier 2,049-test checkpoint. Its open findings were addressed
by the documentation-first maintenance below; its counts remain historical.

Four additional original modules are now packages: the model catalogue, conversations,
HTTP model access and local tools. Public imports remain stable; LocalToolRuntime stays
a dataclass. This brings the extraction inventory to **21 original modules**. The
contracts preserve **536 methods and 279 global definitions**; nine HTTP/local-tool
methods intentionally change and are named in the contract inventory.

Concrete corrections in this continuation:

- HTTP quota codes are inspected even when a generic message is present. Authentication
  and quota failures are not retried. Transport rejects non-object JSON and maps OS
  connection failures to domain errors; health reports unsupported endpoints cleanly.
- Shared pure validators reject malformed messages, usage, tool calls and streamed
  deltas. Invalid SSE JSON/UTF-8 is no longer silently discarded. Stream interruptions
  surface without replaying already-yielded output. Stream/tool generation parameters
  are honored consistently.
- Native reload explicitly releases the old model and clears its specification. Failed
  loads cannot retain stale loaded state; tiny-file/allocation failures update health.
  Native memory failures are classified consistently. Tests use an injected fake module,
  not actual native inference.
- Local process output spools to disk with bounded prefix reads. Limits reject zero,
  negative, boolean and non-integer values. Timeout kills a POSIX process group, with a
  Windows direct-process fallback. Tests exercise real subprocess output, environment
  filtering, refusals and descendant termination on Linux. Disk growth, deliberately
  detached children and Windows full-tree containment remain unbounded/unverified.

### Current continuation verification

Final measurements are recorded below and in `audit/checks.tsv`. Earlier tables are
historical, not substitutes for these results.

| Check | Current result |
|---|---|
| Full regression with branch measurement | **2,049 passed**, 2 optional-client deprecation warnings, **494.46 seconds** |
| New runtime/process regressions | **60 passed**; included in the full suite |
| Architecture/import/ownership guards | **34 passed** independently; also included in the full suite |
| Acceptance procedures | **25/25 exit 0**; seven historical procedures report transcript exits, not assertion totals |
| Isolated dependency-free wheel | **399 modules import**; CLI/schema/assets and pip check pass |
| GUI smoke | **20 tabs**, no page errors |
| Selected Ruff correctness and whitespace checks | No findings |
| Extraction contracts | **536 methods / 279 globals preserved across 21 originals**; 9 intentional HTTP/local-tool method changes separately named |
| Source coverage | **77.7% statements** (21,021/27,068), **57.4% branches** (4,738/8,254), across **399 files**; combined 72.9% |
| Repository inventory | **616 files**, **60 folder roles**, zero structural issues; 82 Markdown documents remain catalogued |

Coverage does not combine all CLI/worker subprocesses and is not exhaustive verification.
The settings overwrite and directory registration findings below were also reproduced
against a temporary real workspace; they are not claimed fixed by the passing suite.

### Findings open at that checkpoint (superseded by maintenance below)

These are not covered up by the structural split or by passing tests:

- The low-level conversation settings API stores only one key per conversation because
  released schema v1 makes `conversation_id` the sole primary key. A second distinct
  setting overwrites the first. Correct multi-key persistence requires an additive
  migration and upgrade tests; this continuation does not rewrite released SQL.
- Local model registration/refresh checks existence rather than regular-file identity
  and does not fully revalidate restored content. Native loading now refuses directories
  and tiny files, but catalogue state can still overstate usability. Filename claims
  and byte size never establish valid GGUF contents or inference capability.
- Native filesystem permission/stat errors, close failures and real inference still
  need deeper integration checks. MCP/worker recovery, Windows/VM behaviour and the
  original-product gaps above remain separate work.

There is no fresh real-Blender, real-native-model, vendor-cloud or GitHub CI result for
this continuation. Historical Blender evidence and its actual execution flow above are
unchanged. Every document remains named/explained in `DOCUMENT_GUIDE.md`; no extra
Markdown document was introduced by these package splits.

## Documentation-first maintenance

This is the earlier 2,095-test checkpoint. Its extension-capture follow-up is addressed
by the safety continuation below; the measurements in this section remain historical.

The user requested a complete document review **before** further behaviour changes.
All 82 Markdown documents were read/classified. Current guides were checked for local
file links and exact inline source references; archived reports/transcripts retained
their recorded results. `scripts/review_documents.py` and `audit/documents.tsv` make
that inventory repeatable. Targeted semantic review corrected stale top-level status,
the incomplete schema map, obsolete package names, command/extension isolation claims,
Docker availability assumptions, workflow scope and optional worker authentication.
These checks do not prove every sentence, code-fence example or external URL correct.

### Corrections and upgrade behaviour

- **Settings:** additive schema v31 changes settings identity to `(conversation_id, key)`.
  The surviving legacy value is copied transactionally, including orphan legacy rows;
  old overwritten values cannot be recovered. New writes use `conversation.setting`
  and require a live conversation. Tests cover independent keys, JSON values, input
  refusal, backup on real workspace upgrade, rollback on injected SQL failure, restart
  and exactly-once replay. Released migrations v1–v30 remain unchanged.
- **Startup replay:** testing actual close/open discovered replay ran before any manager
  had registered handlers, silently skipping intents. All managers now register first;
  replay precedes job/task recovery and dynamic tool restoration. An unfinished setting
  is applied once after reopening, and cannot revive a deleted conversation's settings.
- **Model catalogue:** regular-file checks refuse directory registrations. Missing,
  inaccessible, tiny and restored files are rechecked across the entire catalogue,
  including rows beyond the old 200-row default page. User disablement survives loss
  and restoration, and discovery preserves names/context/preferences. Changed identity
  resets current proof/declarations and sets a probe-id watermark; history is retained.
  Legacy observations without signatures are conservatively invalidated. Previously
  hashed files are rehashed on normal refresh/default registration. Cheap signatures
  remain metadata snapshots, not full content/GGUF validation or adversarial guarantees.
- **Native lifecycle:** stat/permission and release failures become explicit domain errors;
  loaded state clears even when closing the native object fails. Fake-dependency tests
  prove contracts, not actual resource reclamation or real inference quality.

### Verification of this maintenance tree

| Check | Final maintenance result |
|---|---|
| Documentation | **82 Markdown documents** read/classified; zero file-link/current inline source-reference findings; all named in the document guide |
| Full regression | **2,095 passed**, 2 optional-client deprecation warnings, **507.56 seconds** |
| New maintenance regressions | **46 added tests**, included in full run |
| Final targeted regressions | **117 passed**, including **38 architecture/document guards** |
| Independent stress/hostile client | **91 passed**, 51.04 seconds |
| Independent cross-interface integration | **11 passed**, 22.68 seconds |
| Acceptance procedures | **25/25 exit 0**; seven older scripts report transcript exits, not assertion totals |
| Isolated dependency-free wheel | **401 imported modules**; CLI, schema v31, pip check and GUI assets pass |
| GUI smoke | **20 tabs**, no page errors |
| Coverage | **77.9% statements** (21,163/27,178), **57.7% branches** (4,774/8,280), **401 source files**; combined 73.1% |
| Structural inventory | **623 files read**, **60 folder roles**, zero structural issues; inventory's own hash excluded |
| Extraction contracts | **524 methods / 279 globals preserved**, 21 intentional original-method changes and 2 added handlers named separately |
| Released migration contract | v1–v30 fingerprint unchanged; v31 appended, upgrade and rollback tested |
| Ruff / whitespace | Selected correctness rules and `git diff --check`: no findings |
| Dead-code review | Four required callback-argument notices retained; not misreported as zero findings |

These measurements belong to the final maintenance tree, not the interrupted preliminary
run. Ordinary coverage does not combine all CLI/worker subprocesses. Document checks do
not execute every prose example or validate external sites/anchors. Historical real-model,
Blender and CI results remain separate from these local checks.

### Remaining boundaries at that checkpoint

The extension-capture finding here is superseded by the next section. The two previously reproduced settings/catalogue bugs are fixed, not merely deferred.
No 100%-coverage, whole-product completion or OS certification is claimed. Extension
output still captures before clipping and lacks the local-tool process-group handling.
Worker bearer tokens are optional in code; an enabled execution worker without one is
unauthenticated. MCP/worker recovery, platform-native integration and the original broad
product gaps remain separate review targets. Model observations cannot remove filesystem
races. No new real-Blender, native GGUF inference, vendor-cloud or GitHub CI run occurred;
the historical real-render evidence and actual Blender flow above remain unchanged.

## Extension and worker safety continuation

The documentation gate ran before code changes: all 82 Markdown documents read/classified,
zero current local-link/source-reference findings. Disposable tools were reinstalled
without adding runtime dependencies or committing caches. The SDK baseline still passed
79 tests with the same optional-client warnings.

### Changes and responsibility review

- `helpers/processes.py` owns disk spooling, bounded prefix reads, deadlines and cleanup;
  callers own grants, environments, argv/shell policy and domain/result contracts. Local
  tools and extensions remain argv-only; opt-in worker execution remains an explicit shell.
- Extension stdout exceeding its byte budget is refused, not accepted as a clipped valid
  JSON prefix. Invalid UTF-8/deep JSON and malformed limits/argv/request/environment get
  domain errors. Stderr clipping is marked. Real subprocess tests cover megabyte output,
  input/environment handling and POSIX descendant timeout cleanup.
- The original worker module is now a responsibility package: protocol, job lifecycle,
  execution, rooted text files, HTTP/auth/framing and explicit serving. Public imports
  remain stable. Initial extraction preserved all 10 methods/6 globals exactly; hardening
  intentionally changes 8 methods/2 globals, separately named in the evidence inventory.
  Prior 21-module transformation rows remain historical evidence, not a new rerun against
  unavailable pre-extraction snapshots. Cumulative recorded preservation is 526 methods /
  283 globals across 22 originals, with 29 method and 2 global-function changes named.
- Worker HTTP refuses ambiguous/negative/oversized lengths, transfer encoding, truncated
  or invalid bodies and non-object JSON. It closes every response connection, matches
  routes exactly and applies a 10-second socket inactivity timeout. Duplicate/invalid auth
  headers are denied before body reads. Default body limit is 8,000,000 bytes, tunable by
  embedding callers through `make_server`; CLI defaults are fixed.
- File transfer enforces 2,000,000 UTF-8 bytes/file, 8,000,000 aggregate text bytes, 500 files
  and 10,000 scanned entries. Directory enumeration is streamed, not a whole rglob list.
  Symlinks outside the project, malformed types, invalid UTF-8 and overlapping target paths
  are refused. A complete write batch is preflighted before mutation. Reads do not create
  missing roots. Budgets refuse rather than silently truncate project snapshots.
- Training input is copied/validated before acceptance. Its saved identity is included in
  the artifact before artifact hashing, independent of background completion timing.
  A compatibility stamp can check—not rewrite—accepted identity. A deliberately blocked
  training test exercises the old race and caller mutation after acceptance.

### Final safety verification

| Check | Fresh result |
|---|---|
| Full pytest with branch coverage | **2,189 passed**, 2 existing optional-SDK warnings; **697.92 s** |
| Targeted final-tree safety/compatibility/architecture | **284 passed**; **93 new safety regressions** |
| Acceptance procedures | **25 exit 0** after M26 synchronization fix; 7 early procedures are transcript-style exit checks, not assertion totals |
| M26 failure and correction | Initial attempt exit 1, 2 pause/state assertions failed; bounded test-only barriers replace the timing race; **25 checks passed twice**, 36 s / 30 s |
| Independent stress / integration | **91 passed / 11 passed**, 59.83 s / 30.42 s |
| Architecture / browser | **39 passed / 20 GUI tabs**, no page errors |
| Installed wheel | **408 modules imported**, no runtime dependencies; schema/CLI/browser assets checked |
| Statement / branch coverage | **78.0% / 58.1%**; 21,374/27,403 statements, 4,861/8,370 branches; 408 measured files |
| Repository / folder / document inventories | **632 files / 61 folder roles / 82 Markdown documents**; zero structural/reference findings |
| Dead code / selected correctness / whitespace | Ruff and whitespace clean; Vulture's 4 required callback-argument notices retained |

`docs/audit/checks.tsv` records the failed first M26 attempt separately from the passing
reruns. Other 24 procedures passed in the initial batch. The fix affects only test
synchronization, not scheduler behaviour. The workspace module's startup-order docstring
was also corrected to match register-before-replay; no executable startup logic changed.
The isolated wheel was rerun afterward. Per-file coverage, final document reviews and
file/folder responsibilities are refreshed alongside these results.

### What remains outside this gate

Spool disk growth is not byte-quota controlled. POSIX timeout group termination does not
contain deliberately detached children or background children after the direct process
exits; Windows only kills the direct process. Worker jobs remain in-memory, without durable
restart recovery, admission quotas, TLS or per-user authorization. Bearer tokens remain
optional in code: `--allow-exec` without one is unauthenticated. File preflight cannot
eliminate filesystem races or roll back later I/O failures; JSON response escaping can
exceed raw text-byte budgets. A socket inactivity timeout is not a total request deadline.
No new real-model, real-Blender, vendor-cloud, Windows/VM or GitHub CI evidence is claimed.

## MCP transport lifecycle continuation

Documentation-first gate repeated on 31 October: 82 Markdown documents read/classified,
zero initial current-reference findings. The package split exposed one stale MCP source
reference in the next review; it is corrected to the package, not hidden as a passed gate.
Historical transcripts retain their old source paths and measurements.

### Confirmed gaps and fixes

- Caller timeout previously began after synchronous pipe/HTTP send/read. A non-reading
  child, slow HTTP body or blocked write could bypass that wait. A bounded asynchronous
  sender now includes queueing and transport in the caller deadline; timeouts close the
  client, drop queued payloads and fail pending calls. Idle sender threads retire.
- Split records, RPC state, MCP result/discovery interpretation, binary stdio and HTTP
  into `adapters/mcp_client/`, preserving public imports. The captured pre-change AST has
  29 methods/4 globals: final preservation is 10 methods/3 globals; 19 method changes and
  the changed parser are explicitly named. Prior rows remain historical, not freshly rerun.
  Cumulative recorded preservation is 536 methods / 286 globals across 23 originals;
  48 method / 3 global changes and 2 previously added transaction handlers are separate.
- Stdio stdout/HTTP bodies and outbound JSON default to 8,000,000 bytes; default pending
  and outbound queue limits are 32 each. Embedding constructors can tune these; CLI uses
  defaults. Stderr retains 200 entries from at-most-4,096-byte chunks, not arbitrary lines.
  HTTP error diagnostics read only a 300-byte prefix (or a smaller configured budget).
- Successful HTTP replies validate framing/completeness: duplicate/conflicting lengths
  and EOF before Content-Length are refused even if the prefix is valid JSON. Chunked
  complete replies work. Refused redirect responses are closed before storing errors.
- Strict UTF-8/JSON and RPC validation replace unbounded lines, silent malformed errors
  and accidental bool/unhashable ID handling. Invalid/deep JSON, malformed result metadata,
  oversized unterminated stdout and invalid error payloads produce domain errors, not a
  reader-thread traceback followed by an unrelated timeout. Failed thread starts clean up.
- POSIX stdio servers use owned sessions; close/timeout kills ordinary child groups and
  closes raw pipes without waiting for buffered-read locks. Windows handles direct child
  only. HTTP redirects are refused, preventing silent credential forwarding; embedded URL
  credentials and invalid headers are refused before network I/O.
- Tool/resource/prompt discovery follows unique cursors with 100-page, 10,000-item,
  aggregate re-serialized byte and whole-list time budgets. Malformed/cyclic collections,
  duplicate tool names and sanitized registry-name collisions fail before manager updates.
  No silently incomplete first-page result is treated as a complete discovery snapshot.
- Failed discovery closes the cached client; dead cached clients are closed before
  replacement. Protocol failures/dead tool-call sessions are closed; normal tool errors
  may reuse a healthy session. No failed request is automatically replayed.

### Final MCP verification

| Check | Fresh final-tree result |
|---|---|
| Full pytest with branch coverage | **2,299 passed**, **2 existing optional-SDK warnings**; **761.86 seconds** |
| Targeted compatibility/safety/architecture | **285 passed**, 51.93 s; **109 new MCP regressions** plus 1 architecture guard |
| Acceptance procedures | **25 exit 0**, including M26's 25 checks; 7 early transcript-style scripts contribute exit statuses, not assertion totals |
| Independent stress / integration | **91 passed / 11 passed**, 50.54 s / 22.42 s |
| Architecture / browser | **40 checks / 20 GUI tabs**, no page errors |
| Actual installed wheel | **413 modules imported**, no runtime dependencies; CLI/schema/browser assets verified |
| Statement / branch coverage | **78.2% / 58.5%**; 21,631/27,677 statements, 4,961/8,482 branches; 413 measured files |
| File / folder / document review | **638 files / 62 folder roles / 82 Markdown documents**, no final structural/reference findings |
| Selected Ruff / whitespace / dead-code review | Correctness/whitespace clean; Vulture reports **5** required callback-argument notices, reviewed and retained |

Two intermediate broad runs were stopped after final executable fixes (redirect response
release and HTTP framing/completeness). Neither partial run is counted as a success.
All results above use the final executable tree; the complete acceptance batch, wheel,
GUI, targeted and independent suites were rerun. The previous M26 harness failure remains
labelled historical in the checks table, not confused with this passing acceptance batch.
No runtime dependency, large artifact, schema migration or release publication is added.
`docs/audit/coverage.tsv`, `checks.tsv`, `documents.tsv`, `files.tsv`, `folders.tsv` and
`refactor-contracts.tsv` distinguish current measurements from historical transform evidence.

### Documentation corrections are not newly implemented features

Semantic cross-checks found obsolete gap statements about tool probes, GUI SSE, M40
scheduling, M35 extractors and M41 pruning; these now match the actual existing code.
MCP key-only serialization is not at-rest encryption: raw configured env/header values
are stored and can appear in journals/backups. MCP server custom binds are possible and
remain unauthenticated. Source review also identified a GUI SSE fallback repeat-POST
risk; it is a queued fault-injection/idempotency follow-up, not reproduced/fixed here.

### Remaining boundaries and review targets

MCP stdio inherits the environment and OS authority. Discovery runs a program or makes
HTTP requests; it is not harmless. Caller timeout does not undo remote side effects,
restore sessions durably or forcibly cancel every OS/resolver/header operation. A detached
child holding a pipe can leave a daemon reader until EOF; background HTTP I/O can outlive
its caller. There is no global connection/memory/process quota, Windows process-tree
containment, OS sandbox or public multi-tenant certification. Finite SSE bodies are read;
long-lived/resumable subscriptions and full JSON Schema evaluation are not supplied.
Validation preflight does not transactionally roll back later registry/database I/O.

Remaining larger modules include learning CLI (811 lines), extensions manager (687), MCP
manager (680), reproduction manager (640), routing (631) and agent orchestration (629).
Line count is a review signal, not a demand to fragment cohesive code; these are not
claimed fully restructured by the transport split. Broader original-product gaps and
historical-only Blender/native/cloud/platform evidence remain in GAPS.md.

## Broad responsibility and boundary batch

The user requested a larger pace of work, not an invented progress percentage. This batch
therefore combines four mixed-responsibility modules (2,247 original lines), two concrete
boundary defects and one server-auth/defaults gap under one final verification gate.
Coverage remains a test measurement, not a percentage of project completion. No finite,
user-approved original-product denominator is invented.

### Concrete work and contracts

| Work item | Implementation and acceptance evidence |
|---|---|
| MCP manager responsibilities | Composition/records, configuration, writes, connections, discovery, registry and calls; all 34 original manager methods / 4 globals AST-exact |
| Extension manager responsibilities | Separate records, manifest validation, installation, lifecycle, registry and writes; all 24 methods / 4 globals AST-exact |
| Reproduction responsibilities | Environment/model evidence, tool/run caveats, assessment/commands, history/verification and writes; all 17 methods / 5 globals AST-exact |
| Public compatibility | Original public imports and wildcard exports retained; ownership guards cover all three managers and MCP server |
| MCP server transports/policy | Protocol/schema and dispatch separate from HTTP/stdin; 3 methods / 1 helper preserved, 5 intentionally changed and named |
| MCP server request handling | Reject invalid RPC IDs/params/arguments, ambiguous/negative/oversized lengths, transfer encoding, invalid/deep JSON/UTF-8, truncated and idle bodies; close responses; oversized stdio line terminates without executing the tail |
| MCP server auth/defaults | Token required before non-loopback bind; optional loopback auth retained; `--token-env` avoids token values in argv; authorization checked before body reads; missing CLI host/port use configuration |
| GUI stream correctness | No automatic repeat POST after uncertain completion; retain partial output/warning, restore composer and guard concurrent same-page submit; four injected stream outcomes count requests |

The first browser fault test exposed a catch-block variable shadowing error in the change;
it was corrected before the final gate. An AST-check script also initially miscompared
multiline docstring indentation after dedenting inspected methods; module-AST comparison
confirmed the manager methods themselves are exact. Neither issue is disguised as a
successful initial check. Cumulative recorded preservation is 614 methods / 300 globals
across 27 originals, with 53 method / 3 global changes and 2 prior added handlers separate.
Older baseline rows remain historical, not freshly recreated.

### Acceptance correction, not a loosened performance target

The first M26 attempt failed its old 2,600-ms threshold at 2,664 ms. The first barrier
rerun also failed: the normal 80% declared-CPU ceiling admits only three 25% commands.
The corrected disposable fixture explicitly allows 100% for a four-child rendezvous and
restores 80%. All four must finish the barrier; no larger wall-clock threshold is used.
Both failures are retained as failures. This changes test assumptions, not scheduler
semantics, and the old timing assertion did not prove four-way concurrency.

The initial broad full run was stopped after identifying an obsolete GUI source guard
requiring the automatic replay intentionally removed by this batch. That guard now
prohibits replay and requires the uncertainty message; independent browser fault injection
counts actual POSTs and preserves a nonempty pending draft. The required fresh full run
passed below; the stopped run is not counted as a completed gate.

### Final broad verification

| Check | Final local result |
|---|---|
| Fresh full pytest with branch coverage | **2,338 passed**, **2 existing optional-SDK warnings**, **1045.00 seconds** |
| Manager contracts | **75 methods / 13 globals exact**, original public/wildcard imports retained; server **3 methods / 1 helper exact**, **5 intentional changes** |
| Targeted suites | Initial **232 passed**; post-manifest **114 passed**; overlapping subsets, not a combined unique total |
| Acceptance procedures | **25 individually pass**: original batch **24 pass / M26 fails**, then corrected M26 **25 checks pass**; both failed M26 attempts remain above |
| Independent stress / integration | **91 / 11 passed**, 74.93 s / 48.75 s |
| Architecture / Python GUI stream | **44 / 8 passed**, 4.62 s / 5.49 s |
| Browser fault injection | **20 tabs + 4 stream scenarios**; no repeat POST, nonempty pending draft preserved, composer restored, no page errors |
| Actual installed dependency-free wheel | **440 modules imported**, CLI/schema/browser assets verified |
| Statement / branch measurement | **78.4% / 58.8%**, 21,891/27,912 statements and 5,009/8,522 branches; **440 files**; not project completion |
| Structural/document inventory | **666 files / 66 folder roles / 82 Markdown documents**, no final structural/reference findings; not exhaustive manual semantic certification |
| Selected Ruff / source whitespace / dead-code review | Correctness/source whitespace clean; historical transcript spacing and TSV empty cells retained; **5** required callback notices reviewed and retained, not zero Vulture findings |

The stopped full run is excluded. All final full tests use the corrected legacy GUI guard;
application source was unchanged by that test-only correction. The other 24 acceptance
procedures, wheel and independent suites use the same application source as the corrected
M26/browser checks. Seven early transcript-style procedures contribute exit statuses, not
assertion totals. No native/platform/Blender rerun, release publication or completion
percentage is inferred. Per-file measurements and outcomes live in `docs/audit/coverage.tsv`
and `checks.tsv`; inventories and contract records retain explicit historical boundaries.

### Still open, without a fabricated percentage

Manual/API retries have no server idempotency key; browser cancellation is not implemented.
An uncertain/disconnected turn may finish and persist remotely, so users must check history.
MCP loopback may be unauthenticated; bearer tokens are shared credentials, not per-person
accounts or TLS, and no global request/thread quotas are added. Socket inactivity is not
a total tool-operation deadline. JSON response size checks are not a serialization-memory
quota. Stdio custom text streams are character-limited before the UTF-8 byte check; real
stdin uses binary reads. Durable MCP/worker recovery, OS sandbox/process containment,
native/platform/Blender validation and original-product ambitions remain separate gaps.

Larger remaining responsibility-review targets include the learning CLI, router, agent,
GUI server, research manager, learning/scenes/experiments application modules and model
CLI. The three managers named as large in the previous checkpoint are now split; that
old section is historical rather than a current unresolved list. Structural inventory is
not proof of exhaustive manual semantic correctness for every line.

## Remaining nine-owner batch

Scope fixed before implementation: router, agent, tutor, scenes, experiments, research
manager, GUI server, learning CLI and models CLI; 5,708 original lines. This closes the
previous checkpoint's named large-owner list as one batch, not nine small turns.
The baseline ledger contains 27 previously accepted originals and nine pending targets:
27/36 = 75% of this equally weighted structural list, not overall product or elapsed effort.

### Contract and failure boundaries

220 persisted contracts cover 137 methods, 51 globals, 29 CLI branches, two parser functions
and research table metadata. Seven original snapshots are independent. Router/agent's 33
contracts were recovered from untouched copies after the first generator interruption;
they are not independent pre-change proof. The generator's missing _cfg grouping and
relative-import assumptions were repaired before gates. Existing tests then found the
public Budget override regression (325 passed/1 failed); it was restored. Static review
found ResearchManager.tables missing, now restored with an explicit class-attribute test.
A temporary import omission caused 10 integration setup errors before repair. GUI lifecycle
also drops a discarded functools.partial object; the bound handler subclass is unchanged.
Initial partial full/acceptance runs are excluded; fresh final gates are required.

### Final remaining-owner verification

| Final check | Observed result |
|---|---|
| Full regression | **2,566 passed**, **2 optional-SDK warnings**, **649.74s** |
| Architecture / frozen targeted gate | **272 / 287 passed**; overlapping counts, not added together |
| Acceptance procedures | **25 exit 0** on final package source; early transcript-style exits are not assertion totals |
| Independent stress / integration | **91 / 11 passed**, 56.23s / 27.51s |
| Installed dependency-free wheel | **492 modules imported**, CLI/schema/browser assets verified |
| Browser smoke | **20 tabs + 4 stream scenarios**, no duplicate POST/page errors, pending draft retained |
| Inventories | **721 audited files / 75 folder roles / 82 Markdown documents**, zero final structural/reference findings |
| Statement / branch measurement | **78.7% / 59.1%**, 492 source files; not progress |
| Static/dead-code review | Selected Ruff clean; 5 required callback notices retained, not zero Vulture findings |

**Measured structural progress: 27/36 (75%) → 36/36 (100%), +9 accepted originals and
+25 percentage points on the fixed named large-owner list.** All nine targets named at
the preceding checkpoint are accepted together. The ledger is equally weighted by original
module, not effort, product capability or every source file. The largest remaining source
file is 581 lines (configuration), not proof that its semantics or responsibilities need
no more work. No whole-product percentage is claimed.

Contracts remain explicit: 187 independent pre-change hashes across seven originals,
33 recovered-copy contracts across router/agent, with two intentional method changes.
The original Budget failure, temporary import errors and interrupted gates remain above;
none is retroactively counted as passing. Fresh final full/acceptance/independent and
wheel results close this structural batch, not the original product.

### Still outside this structural percentage

Medium-sized owners still deserve responsibility/semantic review; no line-count threshold
proves cohesion. Full original-product completion cannot be derived from 36 source targets.
Durable replay/recovery, isolation, speech, transformer fine-tuning, cloud provisioning and
fresh Blender/native/platform certification remain explicitly open in GAPS.md. Historical
27-module AST records remain historical; the new JSON does not retrospectively strengthen
their baseline evidence. No coverage number is converted into project progress.

## Worker policy and admission

The completed 36-target structural ledger remains 36/36; this is a separate safety gap,
not a manufactured increase in that percentage. The documented open executable-worker
listener policy and unbounded background training are addressed together.

| Change | Boundary |
|---|---|
| Credential/bind validation | Executable or non-loopback/hostname listener requires token; numeric-loopback training remains optional auth; validate before listening |
| CLI credentials | Environment-name option; mutually exclusive legacy argv token; missing/invalid values fail without echo |
| Bound listener identity | Credential bytes captured; later token mutation cannot disable auth; open training cannot upgrade to an open executable listener |
| Training admission | Atomic running/retained limits; 4/128 defaults; HTTP429 before acceptance; failed thread starts remove reservations |
| Result lifecycle | Terminal work frees running capacity, not retained records; no eviction/durability; collect before planned restart |
| Operator visibility | Authenticated health capacity snapshot; no secret or result contents exposed |

Pre-freeze existing worker/remote/execution tests: 151 passed. New policy tests: 50;
combined final targeted/architecture gate: 473 passed in 50.45s. No failed attempt is
hidden or relabelled; final full gates are recorded below.

### Final verification

| Gate | Observed final result |
|---|---|
| Full pytest with branch measurement | **2,616 passed**, **2 existing optional-SDK warnings**, **591.79s** |
| Worker/remote/execution/architecture gate | **473 passed**, 50.45s, including **50 new policy/admission cases**; counts overlap full suite |
| Acceptance procedures | **25 exit 0**, including real worker training/execution; transcript-style procedures are exits, not assertion totals |
| Independent stress / integration | **91 / 11 passed**, 54.93s / 24.49s |
| Installed dependency-free wheel | **493 modules imported**, CLI/schema/browser assets verified |
| Browser smoke | **20 tabs + 4 stream scenarios**, no duplicate POST or page errors |
| Inventory | **723 audited files / 75 folder roles / 82 Markdown documents**, no final structural/reference issues |
| Statement / branch measurement | **78.8% / 59.2%**, 493 files; not progress |
| Static/dead-code review | Selected Ruff clean; five required callback notices reviewed and retained, not zero Vulture findings |

This closes the explicit listener-authentication and bounded-training acceptance criteria.
The structural ledger stays **36/36 accepted (100%)**; its percentage is not inflated for
this new safety work and is not a whole-product figure. No fresh native/platform validation
or durable/global-resource isolation is inferred. The 36-module historical/recovered-copy
contract limitations and earlier failed attempts remain in their original audit sections.

No request-handler/validation/exec concurrency ceiling, hard RAM/disk quota, TLS,
per-person accounts, OS sandbox, durable job recovery or native-platform certification
is added. Credentials are shared authority, not server identity. Direct Python execution
remains a trusted embedding API. Coverage is not product completion; the structural
percentage is unchanged and original-product gaps remain explicit in GAPS.md.

## Feature count and clarified Research acceptance

Documentation-only reconciliation, not a runtime delivery. The current working inventory
counts 41 roadmap units: 31 implemented within recorded technical scope and ten broader
areas partial, including datasets as already scoped in MODES.md. This is not evidence
that 31 original features are fully accepted or only ten implementation tasks remain.
Stale current MODES claims that Play/datasets/Blender/automations have no code were corrected.
The user explicitly requires AI research chat with general web discovery and no mandatory
URLs; current Research is incomplete. Source-analysis/report functionality remains useful
but does not meet that requirement. Acceptance criteria are in FEATURE_STATUS.md.
Previous 2,616-test/493-wheel evidence is for the preceding runtime source. Only document
reference/structural/inventory checks are refreshed here; no search engine integration,
AI research conversation or new live-web verification is claimed.

## Local testing handoff

Documentation/source-distribution handoff, not a feature release. Fresh disposable Linux
venv installed core editable source; init, scripted-model registration, explicitly simulated
chat, memory creation, keyword search and task listing all exited zero. The simulated reply
explicitly reported no inference. Real-model/native Windows/macOS setup is documented,
not freshly certified here. Corrected a stale GUI-guide automatic-replay statement to match
current no-retry behaviour. Full runtime evidence remains the prior 2,616-test gate.


## User-reported GUI correction

Earlier structural/test evidence did not establish usable chat. User screenshots showed
competing sidebars and intrusive diagnostics; code review also found dropped HTTP reasoning
fields and a model badge unrelated to request selection. The six scoped chat repairs now
have Chromium desktop/mobile checks and real-loopback HTTP→GUI→history reasoning coverage.
The broader mode complaint remains open: reports and tool forms are not equivalent to the
original conversational/autonomous product requirements. Full fresh regression evidence
for this correction is recorded in the final checkpoint, not borrowed from earlier totals.


## Completed chat-correction verification

The six-item chat-repair checklist is implemented and fixture-tested (6/6, 100% of this
bounded checklist only). Full regression: **2641 passed, 2 failed, 2 optional-SDK warnings
in 571.72s**. Both failures were obsolete UI expectations (all styles in one file and a
persistent icon rail), not silently waived runtime failures. The expectations now check
both linked stylesheets, one history sidebar and the mobile drawer. Final interface plus
architecture rerun: **452 passed in 101.90s**, including all 27 new reasoning cases. These
counts overlap and are not added. No second full-suite run after the expectation updates
is claimed.

The DOM smoke passes all 20 preserved workspace routes and four uncertain-stream cases.
Real Chromium passes desktop/light/dark and phone layout, selected-model request binding,
separate thinking, saved-history rendering, collapsed diagnostics, mobile tool navigation
and provider-interruption/no-replay behaviour. Real loopback HTTP provider fixtures cover
streaming/non-streaming reasoning fields and split leading think tags through the GUI and
database. These fixtures do not establish real-model quality or Windows compatibility.
The user's own Ollama replies are distinct real-inference evidence from their machine.

Current inventories: 730 audited files, 75 folder responsibilities, 84 Markdown documents;
zero document-reference/structural findings. A built wheel includes the new stream owner,
reasoning helper and chat stylesheet. The correction is provided as an unpublished source
ZIP, excluding environments, Git metadata, databases and credentials. No commit, push or
claim that every mode works is made. Broader mode redesign and autonomous Research remain
open; the Models form still needs a local-endpoint connection flow rather than CLI setup.
