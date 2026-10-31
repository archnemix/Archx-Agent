# Plan and status

The table below records the historical scoped roadmap; its test counts belong to
those checkpoints, not the current tree. Active maintenance is tracked separately below.

Milestone order follows the product spec. A milestone is only marked **done** when its
acceptance criterion was demonstrated in the running application (CLI end-to-end test
plus a recorded manual transcript), not merely when unit tests pass.

Legend: **done** = implemented + verified in app · **done · scoped** = verified, but narrower
than the mode's name implies (see [docs/MODES.md](docs/MODES.md)) · **partial** = implemented,
acceptance not fully demonstrated · **not started**

| # | Milestone | Recorded state | Checkpoint evidence (historical counts) |
|---|-----------|-------|----------|
| M01-M09 | Skeleton, errors, `Result`, paths, branding, terminal chat, context budget, package + CLI | **done** (rebuilt from scratch - see note) | `tests/foundation/test_foundation.py`, CLI tests |
| M10 | SQLite conversations, `--resume`, `/conversations` | **done** | `tests/knowledge/test_memory_m17.py::TestConversationBasics`, CLI `conv` |
| M11 | Storage reliability: coordinator, journal, exactly-once, backpressure, backup, preferences | **done** | `tests/foundation/test_storage.py` incl. SIGKILL crash test |
| M12 | Backup/restore/`--check-db`/preview | **done** | `tests/foundation/test_storage.py::TestBackupRecovery`, `archx-agent db ...` |
| M13 | Structured events, redaction, capture levels, causal tree, sequence ordering | **done** | `tests/foundation/test_storage.py::TestEvents` |
| M14 | Debug & Trace interface: filters, summaries, export, retention | **done** | `archx-agent trace ...`, CLI tests |
| M15 | Model catalogue + local discovery (facts vs claims vs user metadata) | **done** | `tests/models/test_models.py` (see M21), CLI `models` |
| M16 | Provider adapter boundary + catalogue-aware resolution + key hygiene | **done** for HTTP; llama.cpp path requires the optional dependency and a GGUF file | `tests/foundation/test_application.py::TestHttpRuntimeContract` |
| **M17** | **Memory persistence foundation (six systems)** | **done** | `tests/knowledge/test_memory_m17.py` (36 tests), CLI acceptance transcript |
| **M18** | **Embedding + retrieval evaluation** | **done** | `tests/knowledge/test_embeddings_m18.py` (29), `docs/RETRIEVAL_EVAL.md` |
| **M19** | **Context Strategy Manager (five strategies)** | **done** (ai_proposed + manual + summarize + oldest_first + ai_select all exercised) | `tests/knowledge/test_context_m19.py`, CLI `context` |
| **M20** | **Cloud provider catalogue + privacy metadata** | **done** | `tests/models/test_providers_m20.py` (30), `docs/PROVIDERS.md`, `scripts/acceptance_m20.sh` |
| **M21** | **Capability-safe model router + model management** | **done** | `tests/models/test_router_m21.py` (33), `docs/ROUTING.md`, `scripts/acceptance_m21.sh` |
| **M22** | **Tool registry + Permission & Approval Center** | **done** | `tests/tools/test_tools_m22.py` (78) + 13 CLI tests, `docs/TOOLS.md`, `scripts/acceptance_m22.sh` |
| **M23** | **MCP client/server + extension foundation** | **done** | `tests/tools/test_mcp_m23.py` (43) + `tests/tools/test_extensions_m23.py` (35) + 9 CLI tests, `docs/MCP.md`, `scripts/acceptance_m23.sh` |
| **M24** | **Task history, content versions, reproduction records** | **done** | `tests/workflows/test_tasks_m24.py` (75), `docs/TASKS.md`, `scripts/acceptance_m24.sh` incl. a real SIGKILL |
| **M25** | **Agent workflows: user-directed and model-proposed, with subagents** | **done** | `tests/workflows/test_agent_m25.py` (60), `docs/AGENTS.md`, `scripts/acceptance_m25.sh` (real HTTP plan) |
| **M26** | **Resource and job scheduler** | **done** | `tests/workflows/test_scheduler_m26.py` (94), `docs/SCHEDULER.md`, `scripts/acceptance_m26.sh` (SIGKILL + pause/resume) |
| **M27** | **Simple Mode and unified search** | **done** | `tests/knowledge/test_search_m27.py` (42) + `tests/knowledge/test_simple_m27.py` (67), `docs/SIMPLE_MODE.md`, `scripts/acceptance_m27.sh` (23 checks) |
| **M28** | **Researcher Mode** | **done · scoped** | `tests/features/test_research_m28.py` (97), `docs/RESEARCH.md`, `scripts/acceptance_m28.sh` (30 checks incl. real HTTP and an approval). Scope: reads local documents and the URLs you give it — **no web search, no crawler, no experiment runner** (`docs/MODES.md` §3.1) |
| **M29** | **GUI core workflows** | **done** | `tests/interfaces/test_gui_m29.py` (85), `docs/GUI.md`, `scripts/acceptance_m29.sh` (54 checks over a real socket) |
| **M30** | **Learning Mode** | **done · scoped** | `tests/features/test_learning_m30.py` (121), `docs/LEARNING.md`, `scripts/acceptance_m30.sh` (90 checks). Scope: exact/self grading, no model marking; no media items (`docs/MODES.md` §3.2) |

| **M31** | **Coding workspace** | **done** | `tests/features/test_coding_m31.py` (66), `docs/CODING.md`, `scripts/acceptance_m31.sh` (48 checks over a real socket). Scope: a session is a directory inside the tool roots, every read/write/run is a tool call, edits are diffs on the session task, and the runner records every command |
| **M32** | **Experimental Mode** | **done** | `tests/features/test_experiments_m32.py` (66), `docs/EXPERIMENTS.md`, `scripts/acceptance_m32.sh` (53 checks over a real socket). Scope: an experiment is a declared command, parameters and metrics source; a metric is read only from that source or not at all, and a comparison names what it could not rank |
| **M33** | **Play Mode** | **done** | `tests/features/test_play_m33.py` (77), `docs/PLAY.md`, `scripts/acceptance_m33.sh` (69 checks: the migration adopting the reserved tables, a refused move kept, sixty engine games checked against the rules, a doctored hash failing its own replay, and the page starting a game the CLI reads) |
| **M34** | **Voice and multimodal foundation** | **done · scoped** | `tests/features/test_voice_m34.py` (67), `docs/VOICE.md`, `scripts/acceptance_m34.sh` (88 checks incl. containers built byte by byte and a CHECK constraint tested directly). Scope: measurement, provenance and honest refusal - **no speech recognition or synthesis exists here**, and `voice transcribe`/`voice say` say so on the record (`docs/MODES.md` §3.4) |
| **M35** | **Dataset preparation** | **done** | `tests/features/test_datasets_m35.py` (60), `docs/DATASETS.md`, `scripts/acceptance_m35.sh` (72 checks: a resaved document refused across splits, a manifest broken by an edit and by a delete, and a split that does not move when the corpus grows). Scope: text corpora prepared on this machine - **no training, no tokenisation, no upload** |
| **M36** | **Training and model modification** | **done · scoped** | `tests/features/test_training_m36.py` (54), `docs/TRAINING.md`, `scripts/acceptance_m36.sh` (57 checks, incl. an independent perplexity implementation that must agree to 1e-9). Scope: two trainers that really run here (n-gram perplexity, nearest-centroid accuracy); **fine-tuning is refused by name** - no weights, no GPU, no library (`docs/MODES.md` §3.5) |
| **M37** | **Remote compute and portability** | **done · scoped** | `tests/features/test_remote_m37.py` (45), `docs/REMOTE.md`, `scripts/acceptance_m37.sh` (71 checks, incl. a worker that misreports its hash and a remote metric that must equal the local one exactly). Scope: a bundle that identifies its input and a worker that speaks a documented protocol - **no cloud, no vendor SDK, no credentials** (`docs/MODES.md` §3.6) |
| **M38** | **Execution environments and sandboxing** | **done · scoped** | `tests/features/test_execution_m38.py` (49), `docs/EXECUTION.md`, `scripts/acceptance_m38.sh` (65 checks incl. a stand-in `docker` on `PATH` that records its argv, a worker refusing without `--allow-exec` and with a wrong token, and a file edited on both sides). Scope: the wrapper is the feature - `local`, `remote`, `docker`, `wsl`, `windows-sandbox`, `vmware`, `virtualbox`, each recorded with the invocation that ran and refused by name when it cannot run here; **WSL is labelled not a boundary, Windows Sandbox is `detached`**, and `execution.enabled` is off by default (`docs/MODES.md` §3.7) |
| **M39** | **Blender and 3D workflows** | **done · scoped** | Six measured primitives, task artifacts, CLI/API/GUI, OBJ/STL/SVG/scripts, local rendering; 58 tests and 59 acceptance checks. CI #26 verifies an actual 64×64 official Blender 4.2 bpy/Cycles CPU render. No animation, remote rendering or desktop-binary matrix. `docs/SCENES.md` |
| **M40** | **Automations and scheduled tasks** | **done · scoped** | Atomic interval/once/hash-watch dispatch, explicit polling worker, CLI/API/GUI, live job status and execution-time permission checks. 17 tests, 34 acceptance checks; CI #26 green. No cron/DST, cloud triggers or service installer. `docs/AUTOMATIONS.md` |
| **M41** | **Hardening and release readiness** | **done · scoped** | HTTP framing, bounded binary decoding, non-deadlocking command output, packaged GUI and isolated wheel/sdist smoke. 8 regressions; full suite 1951; CI #26 all 24 logged steps green. Source/wheel readiness, not a published installer or security certification. `docs/RELEASE.md` |

## Note on the M38-M41 numbering

The eight-step brief places Blender at M38. M38 was executed as **execution environments and
sandboxing** instead - the milestone M36 and M37 kept pointing at ("the work runs on a machine that
is not necessarily this one, and it runs in a sandbox that is really a sandbox") - so Blender, the
automations and hardening moved to M39-M41. Nothing had been built for those three, so the shift
costs nothing; the older docs that still say "M38 Blender" are listed in `GAPS.md` §Roadmap.

## Note on M01-M16

The repository this work started from contained a single commit with a two-line README
and **no code** - the M01-M16 features described in the brief did not exist (verified:
at initial inspection, `git log --all` showed one commit and the tree contained one file). Everything listed above
was therefore rebuilt from the foundations, in the same order and with the same
invariants, before M17 could start. See [docs/VERIFICATION.md](docs/VERIFICATION.md).

## Completed post-roadmap maintenance

Reviewed 30 October 2026. These tasks are not new numbered product milestones.

| Work | State | Completion criterion |
|---|---|---|
| Review every document before code changes | Done (documentation gate) | Classify current/history, verify links/code paths, correct safety/status claims; export per-document review evidence |
| Preserve multiple conversation settings | Done; final local gate passed | Append migration without changing v1–v30; retain existing value; independent keys, journal replay, restart and upgrade tests |
| Validate model files and refreshed catalogue state | Done; final local gate passed | Refuse directories; recheck missing/tiny/restored files; preserve disabled intent; avoid stale capability proofs on changed bytes |
| Finish native runtime failure cleanup | Done; final local gate passed | Map stat/close failures to domain errors; clear stale loaded state; injected-dependency regression tests |
| Restore actual workspace write-intent replay | Done; restart and final local gate passed | Register all domain handlers before replay, then recover consumers; replay settings exactly once after restart |
| Validate final tree and synchronize documents | Done; evidence refreshed | Full regression/coverage, acceptances, architecture, GUI and isolated wheel; update progress, decisions, guide/catalogue and evidence |

Final local evidence: **2,095 tests**, **25 acceptance procedures exit 0**, **38
architecture/document guards**, **91 stress / 11 integration checks**, **20 GUI tabs**
and **401 isolated-wheel imports**. All 82 Markdown documents are catalogued/reviewed;
THINKING.md, PROGRESS.md, current guides and evidence inventories are synchronized.

This earlier maintenance batch is complete, not a whole-product sign-off. Its extension
output/process follow-up is addressed below; MCP/worker recovery and real platform/native-model
integration remain separate gaps. At this earlier checkpoint worker tokens were optional; current worker-policy changes
are recorded separately below.
Broader product/platform gaps in GAPS.md remain separate from these concrete fixes.

## Completed extension and worker safety batch

Documentation review first: all 82 Markdown documents read/classified again, with no
local-link/current source-reference findings. The previous 2,095-test gate remains
labelled historical; final safety results follow.

| Work | State | Acceptance criterion |
|---|---|---|
| Extension/process output and timeout handling | Done; final local gate passed | Shared disk-spooled bounded-read runner; strict positive limits; no silently accepted truncated JSON; Linux process-group timeout tests |
| Worker responsibility boundaries | Done; final local gate passed | Separate protocol validation, execution, files, HTTP and lifecycle while retaining existing public imports |
| Worker HTTP and file refusal paths | Done; final local gate passed | Reject ambiguous/oversized/invalid bodies, malformed payloads and out-of-root symlinks; bounded file transfer; retain optional-token policy explicitly |
| Worker artifact identity race | Done; final local gate passed | Stamp the accepted bundle identity before artifact hashing, independent of completion timing |
| Acceptance pause/crash timing | Done; 25 checks pass twice | Replace sleep-based M26 synchronization with bounded test-only barriers; rerun and retain failed-attempt evidence |
| Final validation and documentation | Done; evidence refreshed | Full coverage tests, acceptances, architecture, GUI, wheel, fresh inventories, plan/progress/decision updates |

Disk spooling does not impose a disk quota or OS sandbox. Worker jobs remain in-memory,
not crash-recoverable durable jobs. Auth policy changes are not hidden inside this refactor.

Final safety gate: **2,189 tests**, 2 optional-SDK warnings; **25 passing acceptance
procedures** after fixing/recording the M26 harness race. Independent **91 stress / 11
integration / 39 architecture checks**, **20 GUI tabs**, **408 dependency-free wheel
imports**. Statement/branch coverage: **78.0% / 58.1%**. Inventories cover **632 files,
61 folder roles and 82 Markdown documents**. No fresh Blender/native/cloud/Windows/CI
certification. This closes the concrete safety batch, not the original product gaps.

## Completed MCP transport lifecycle batch — 31 October 2026

Documentation-first review: 82 Markdown documents read/classified, no current local
reference findings. The 2,189-test safety gate above is historical for this new batch.

| Work | State | Acceptance criterion |
|---|---|---|
| Transport responsibilities | Done; final local gate passed | Stable public imports; distinct records, RPC bookkeeping/surface, stdio and HTTP owners |
| Caller deadlines and shutdown | Done; final local gate passed | Start deadline before sending; blocked stdin/network cannot block caller indefinitely; fail pending calls and clean ordinary POSIX child groups |
| Bounded framing and errors | Done; final local gate passed | Byte-bounded stdout/HTTP/error bodies and stderr; malformed RPC cannot kill reader unnoticed |
| Failed-client replacement | Done; final local gate passed | Close dead cached clients and failed discovery connections before reconnecting |
| Verification and evidence | Done; evidence refreshed | New real process/socket regressions, full tests/acceptances, wheel/GUI/static checks; update guides/evidence |

No durable MCP session replay, OS sandbox, public multi-tenant certification or native
platform evidence is implied. Network resolver/header cancellation limitations must remain
explicit, even when the waiting caller has a deadline.


Final MCP gate: **2,299 tests**, 2 existing optional-SDK warnings; **25 passing
acceptance procedures**, **91 stress / 11 integration / 40 architecture checks**, **20 GUI
tabs**, **413 dependency-free wheel imports**. Coverage: **78.2% statements / 58.5% branches**.
Inventories cover **638 files / 62 folder roles / 82 Markdown documents**. The batch adds
**109 MCP regressions and 1 architecture guard**; stopped partial runs are excluded.

### Historical follow-ups discovered during the MCP client batch

The first two items are addressed by the broad batch below; recovery, containment and
original-product limits remain separate. This list records their discovery, not a second
current unresolved list.

- Reproduce GUI chat fallback after a dropped SSE final frame; avoid automatic duplicate
  turns and define explicit retry/cancellation behaviour before changing browser flow.
- Review MCP server HTTP framing/resource limits and unauthenticated custom binds separately
  from this client transport batch; preserve/explicitly decide compatibility policy.
- Continue responsibility review of the remaining larger modules named in the audit.
- Keep durable MCP/worker recovery and native/platform/Blender validation separate from
  local transport correctness and original-product scope gaps.

## Completed broad responsibility and boundary batch — 31 October 2026

No completion percentage is assigned: coverage is not product progress. Review all documents first, split MCP/extensions/reproduction managers with exact method contracts, remove automatic GUI retry after uncertain streaming completion, harden MCP server framing and defaults, and run one combined final verification gate. Remaining original-product gaps stay separate.


| Broad-batch work item | Current state | Closure criterion |
|---|---|---|
| Three large manager splits | Done; final local gate passed | All 75 methods/13 globals and wildcard exports preserved; ownership and affected suites pass |
| MCP server policy/transport separation | Done; final local gate passed | Separate protocol, dispatch, HTTP and stdio; intentional changes named |
| MCP server framing/auth/defaults | Done; final local gate passed | Bounded refusal paths, token requirement for non-loopback binds, CLI config defaults and token env |
| GUI uncertain-completion retry | Done; final local gate passed | One streaming POST only, no fallback POST, partial output retained and composer restored |
| Final combined evidence | Done; evidence refreshed | Full tests, 25 acceptances, stress/integration, architecture, GUI, wheel, final document/inventory consistency |

No project completion percentage is assigned. Remaining responsibility targets and product
capabilities are listed in the audit/GAPS, not hidden by this batch's closure.

Final broad gate: **2,338 tests**, **25 individually passing acceptance procedures**,
**91 stress / 11 integration / 44 architecture checks**, **20 GUI tabs + 4 stream
scenarios**, **440 wheel imports**. Initial M26 failures and the stopped obsolete-guard
run remain recorded, not counted as successes. Inventories: **666 files / 66 folders /
82 Markdown documents**. Original-product and remaining responsibility gaps remain open.


## Completed remaining-owner batch — fixed scope, 31 October 2026

Review all 82 documents before implementation. The fixed structural backlog is the nine
large owners named at the previous checkpoint: router, agent, learning service, scene
service, experiment service, research manager, GUI server, learning CLI and models CLI.
Acceptance requires named responsibility owners, stable public imports, captured AST
contracts, regression/acceptance/wheel checks and refreshed simple/technical guides.
Baseline: 0/9 of these remaining targets accepted (0% of this batch). Existing recorded
transformations cover 27 other original modules. For the explicitly named 36-module
structural backlog, that is 27/36 (75%) at this checkpoint, not whole-product completion.
No effort weighting, coverage-to-progress conversion or original-product percentage is
asserted. Verification and original-product gaps are separate; 100% of this structural
list would not mean exhaustive semantic review or delivery of speech/cloud/fine-tuning.

At the intermediate checkpoint, nine owners were implemented and final acceptance was pending; the completed result is below.
Focused freeze gate: 287 passed, including 272 architecture/contract cases, Budget override
and GUI socket streaming. Preserve the 325-pass/1-failure Budget regression, temporary
integration import errors, lost independent router/agent snapshot buffer and stopped
partial gates as limitations/failures. Do not promote pending work to accepted early.

### Final remaining-owner acceptance and progress

All nine fixed targets are accepted. **2,566 tests / 25 acceptances / 272 architecture
cases / 91 stress / 11 integrations / 492 installed-wheel imports** pass, plus 20 GUI
tabs and 4 stream scenarios. Full run: 649.74s, 2 warnings. The structural
ledger moves from **27/36 (75%) to 36/36 (100%)**: nine accepted modules, not an estimated
product percentage or effort measure. 721 audited files / 75 folders / 82 documents.
Two recovered-copy baseline limitations, intentional Budget/handler changes, metadata
repair, initial failures and stopped partial gates remain explicit in the audit.
Medium-sized owners and original-product gaps remain open; no fresh native certification.


## Completed worker authentication and bounded admission

Documents reviewed first (82 Markdown, zero reference findings). The completed 36-module
structural list is not reopened or relabelled product completion. Close concrete remaining
worker safety gaps together: require a token for any executable worker or non-loopback
HTTP bind, preserve unauthenticated loopback training, add environment-based CLI tokens,
validate token values, and bound active training jobs plus retained result records.
Test bind refusal before listening, auth before body/dispatch, capacity races and startup
failure cleanup. This does not add durability, TLS, per-user identity, a shell sandbox,
HTTP/exec thread quotas or a hard RAM/disk quota. At the initial checkpoint final gates
were pending; completed results are below. No overall-product percentage is assigned.

Worker policy implementation frozen: 50 new regressions; combined worker/remote/execution/
architecture suite 473 passed (50.45s). At that intermediate checkpoint full regression, acceptances, independent and wheel
checks were running; final results are below. The 36-target structural ledger
remains unchanged; this safety acceptance is separate from overall product completion.

### Final worker safety gate

**2,616 passed**, 2 existing optional-SDK warnings, **591.79s**; all 25
acceptances, 91 stress / 11 integration checks, 20 GUI tabs plus four stream scenarios
and 493 installed-wheel imports pass. The 473-test targeted gate includes 50 new policy
regressions; counts overlap, not added together. Inventories: 723 files / 75 folders /
82 documents. Credential/bind policy, CLI env resolution, locked training/retained limits
and startup-failure cleanup are accepted. Collection does not reclaim retained slots;
planned restart loses in-memory history. No durable recovery, global HTTP/exec quota,
TLS/per-person identity, RAM/disk hard cap or OS sandbox is claimed. Structural scope
remains 36/36 (100%); this is new safety functionality, not overall-product percentage.


## Research product correction and feature-count reconciliation

The user requires AI research chat with general web search, not mandatory seed URLs.
Record Research as incomplete against that requirement; its historical M28 report-workflow
checkpoint is not full product acceptance. docs/FEATURE_STATUS.md counts the 41 roadmap
units consistently: 31 implemented within recorded scope, ten broader areas partial,
including datasets (already scoped in MODES.md). These are not 31 fully accepted original
features or ten total remaining tasks. Correct stale MODES claims that Play/datasets/
Blender/automations have no code. Research acceptance: question-only AI search/discovery,
retrieved-source citations, contextual follow-ups, optional URLs, real model/search backend,
explicit failures and existing privacy/permission controls. No runtime feature is added
in this documentation correction; previous code-test evidence remains historical.


## Local testing handoff before further feature work

The user asks for the implemented feature list and instructions to test on their own
computer before directing the next implementation. Provide current source, not an implied
GitHub main/installer release. LOCAL_TESTING.md separates simulated UI/data exploration
from real local-model inference, uses disposable homes, documents Windows executable
paths and Linux-only test limitations. Core CLI install/init/simulated chat/memory/search/
task-list commands were exercised in a fresh disposable Linux environment. No Research
search/chat implementation or new full-suite/native-platform certification is claimed.


## User-reported chat usability correction — scoped implementation

User screenshots establish a usability failure despite previous automated checks: two
competing sidebars, poor message alignment, persistent full-width diagnostics and no
provider reasoning display. Redesign around one conversation sidebar, discoverable
workspace controls, right-aligned user messages, readable assistant content, actual model
selection and collapsed diagnostics. Preserve visible errors and no automatic POST replay.
Add a separate provider-emitted reasoning channel through HTTP streaming, application,
SSE, persistence and browser details; never fabricate hidden model reasoning. Verify
functional streams and real browser layout at desktop/mobile, not DOM checks alone.
This does not claim all modes or autonomous Research are fixed. Final evidence is recorded below.


### Chat correction implementation checkpoint

Six scoped repairs are implemented and fixture-tested: one history sidebar, conventional
message/composer layout, actual request model selection, returned reasoning separated and
persisted, collapsed routine notes, and mobile drawer navigation. Other workspace routes
are preserved, not declared redesigned or complete. Reasoning supports HTTP fields and
leading think tags; absent provider reasoning is never manufactured. Old discarded
reasoning is unrecoverable. Architecture checks, DOM smoke, real Chromium desktop/mobile
checks and 27 new reasoning/socket tests pass. Full regression evidence is recorded below.
The source archive for this correction supersedes the previous handoff; no GitHub push
or original-product acceptance is implied. Research autonomous web chat is still absent.


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


## Reference UI comparison requested — 31 October 2026

The user rejected feature-count-led UI work and supplied a public Drive version as a
reference for complete, coherent, usable workflows. Direct Drive access is restricted
and the Drive connector is disconnected. Add a bounded GitHub Actions retrieval on the
session branch, inventory the archive and return UTF-8 source without executing downloaded
code. Compare actual navigation, interaction paths and feature completeness before further
redesign. Download and analysis are pending; do not infer quality or behaviour from the link.
Publishing the existing saved source is needed to add the runner workflow on this branch;
main must remain unchanged. Do not commit the original download, environments or models.
