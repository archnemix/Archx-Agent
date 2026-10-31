# Document directory and reading guide

Start with **Project overview and getting started**, then **Repository audit and
requirements comparison** and **Known gaps and limitations**. Use the feature guide
for the command you need. Maintainers should also read **Architecture and module
boundaries**, the relevant tests, and **Design decisions and reasoning**.

The catalogue covers all 84 Markdown documents plus the licence and structured
reference/evidence files below. “Historical” means the counts, environment and status
belong to that checkpoint; they must not override current guides or become a claim
that an absent feature is implemented.

## Project and current guides

| Human-readable name | Document | Meaning and purpose |
|---|---|---|
| Architecture and module boundaries | [`ARCHITECTURE.md`](../ARCHITECTURE.md) | Explains layers, dependency rules, storage invariants and interface responsibilities for maintainers. |
| Testing on your computer | [`docs/LOCAL_TESTING.md`](LOCAL_TESTING.md) | Current-source setup, safe simulated demo, real-model connection, feature checks and platform/test limitations. |
| Current feature implementation and Research requirements | [`docs/FEATURE_STATUS.md`](FEATURE_STATUS.md) | Defines the counting units, ten partial areas and the user's required autonomous AI research chat; distinguishes milestone evidence from feature acceptance. |
| Change history | [`CHANGELOG.md`](../CHANGELOG.md) | Summarizes versioned changes; it is not a test report or release publication record. |
| Known gaps and limitations | [`GAPS.md`](../GAPS.md) | Lists absent features, safety boundaries and unverified platforms; read before assuming a capability exists. |
| Roadmap and milestone status | [`PLAN.md`](../PLAN.md) | Defines the scoped M01–M41 delivery sequence and links acceptance evidence; not an original-requirements sign-off. |
| Progress and recorded verification | [`PROGRESS.md`](../PROGRESS.md) | Summarizes milestone checkpoints and CI results, with counts tied to their historical runs. |
| Project overview and getting started | [`README.md`](../README.md) | Introduces Archx, installation and common commands; the main entry point for users. |
| Design decisions and reasoning | [`THINKING.md`](../THINKING.md) | Explains why implementation and scope choices were made; a decision log with explicit current-maintenance reasoning and preserved historical choices. |
| Agent workflows | [`docs/AGENTS.md`](AGENTS.md) | How to create, approve and execute workflows, use templates/subagents and enforce budgets. Not repository-agent instructions. |
| Codebase guide — a simple map | [`docs/CODEBASE_GUIDE.md`](CODEBASE_GUIDE.md) | Plain-English folder responsibilities, feature layout and where to start reading. |
| Technical reviewer guide | [`docs/TECHNICAL_REVIEW.md`](TECHNICAL_REVIEW.md) | Dependency rules, public/internal module ownership, composition trade-offs, persistence/execution flows and review commands. |
| Repository audit and requirements comparison | [`docs/AUDIT.md`](AUDIT.md) | Reports cleanup, file responsibilities, current verification, broader product gaps and actual Blender evidence. |
| Scheduled automations | [`docs/AUTOMATIONS.md`](AUTOMATIONS.md) | How interval, one-shot and file watches dispatch jobs, how the worker runs and how to stop scheduling. |
| Coding workspace | [`docs/CODING.md`](CODING.md) | Directory sessions, permissioned edits, diffs, commands, named checks and code-run records. |
| Text dataset preparation | [`docs/DATASETS.md`](DATASETS.md) | Scanning, filtering, deduplication, stable splits, exported records and manifest verification. |
| Document directory and reading guide | [`docs/DOCUMENT_GUIDE.md`](DOCUMENT_GUIDE.md) | This catalogue: gives every document a human-readable name and explains when to use it. |
| Execution targets and isolation limits | [`docs/EXECUTION.md`](EXECUTION.md) | Local and remote execution wrappers, probes, push/pull and what each backend does not isolate. |
| Parameterized experiments | [`docs/EXPERIMENTS.md`](EXPERIMENTS.md) | Declaring commands/parameters, measuring runs, storing metrics and comparing results. |
| Browser interface and authentication | [`docs/GUI.md`](GUI.md) | Starting the local web interface, tokens/cookies, controls, API behaviour and browser safety. |
| Learning goals and spaced practice | [`docs/LEARNING.md`](LEARNING.md) | Goals, questions, hint gating, exact/self grading, sessions and scheduling arithmetic. |
| MCP integrations and extensions | [`docs/MCP.md`](MCP.md) | Connecting stdio tool servers, trust/enable decisions, capability checks and extension manifests. |
| Modes and implemented scope | [`docs/MODES.md`](MODES.md) | Maps the product areas to actual controls and tools, and explains deliberately narrower delivery. |
| Games and simulations | [`docs/PLAY.md`](PLAY.md) | The supported rule-checked games, engine moves, simulation parameters, history and replay limits. |
| Model providers, privacy and consent | [`docs/PROVIDERS.md`](PROVIDERS.md) | Registering endpoints/SDK clients, secret references, privacy metadata and remote-use approval gates. |
| Hardening and distribution readiness | [`docs/RELEASE.md`](RELEASE.md) | Source/wheel verification, packaging and explicit limits: no installer or published-release claim. |
| Remote bundles and compatible workers | [`docs/REMOTE.md`](REMOTE.md) | Preparing/approving portable jobs, dispatching them and verifying returned artifacts. |
| Evidence-based research | [`docs/RESEARCH.md`](RESEARCH.md) | Plans, local documents/supplied URLs, source measurements, citation checks, reports and completion decisions. |
| Memory retrieval and embedding choices | [`docs/RETRIEVAL.md`](RETRIEVAL.md) | Lexical/default and optional semantic embedding paths, hybrid retrieval and their limits. |
| Retrieval quality measurement | [`docs/RETRIEVAL_EVAL.md`](RETRIEVAL_EVAL.md) | The checked-in retrieval corpus, evaluation method and recorded scores; not a general semantic-quality guarantee. |
| Capability-aware model selection | [`docs/ROUTING.md`](ROUTING.md) | How models are filtered, ranked, probed and refused, and when fallback is permitted. |
| Scenes, geometry exports and Blender | [`docs/SCENES.md`](SCENES.md) | Primitive scenes, measurements, exports, task artifacts, local render setup and real-render CI evidence. |
| Durable job scheduling | [`docs/SCHEDULER.md`](SCHEDULER.md) | Queue claims, concurrency/resource estimates, deadlines, retries, pause/resume and crash recovery. |
| Simple requests and unified search | [`docs/SIMPLE_MODE.md`](SIMPLE_MODE.md) | The plain-request front door, intent explanations and search across workspace records/files. |
| Task history, artifact versions and reproduction | [`docs/TASKS.md`](TASKS.md) | Inspecting timelines, attaching/versioning artifacts and assessing whether a task can be reproduced. |
| Tools, grants and approvals | [`docs/TOOLS.md`](TOOLS.md) | Tool capabilities, risk, permission scopes, dry runs, protected filesystem operations and recorded refusals. |
| Small CPU trainers and training limits | [`docs/TRAINING.md`](TRAINING.md) | N-gram/centroid training, preflight, metrics and artifact verification; explains why transformer fine-tuning is absent. |
| Historical verification index | [`docs/VERIFICATION.md`](VERIFICATION.md) | Links the archived transcripts while retaining milestone anchors; not a live claim that every run was repeated. |
| Media measurement and speech limitations | [`docs/VOICE.md`](VOICE.md) | Supported byte-level media checks, transcript provenance and recorded refusal of unavailable speech functions. |
| CI evidence and how to read it | [`docs/ci/README.md`](ci/README.md) | Explains recorded GitHub runs, model/SDK/Blender checks, logs and evidence retrieval. |

## Historical milestone reports

| Human-readable name | Document | Meaning and purpose |
|---|---|---|
| Gemini — a real second provider | [`docs/reports/GEMINI.md`](reports/GEMINI.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M17 — Memory persistence foundation | [`docs/reports/M17.md`](reports/M17.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M18 — Embedding and retrieval evaluation | [`docs/reports/M18.md`](reports/M18.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M19 — Context Strategy Manager | [`docs/reports/M19.md`](reports/M19.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M20 — Cloud provider catalogue and privacy metadata | [`docs/reports/M20.md`](reports/M20.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M21 — Capability-safe model router | [`docs/reports/M21.md`](reports/M21.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M22 — Tool registry + permission centre | [`docs/reports/M22.md`](reports/M22.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M23 — MCP client/server + extension foundation | [`docs/reports/M23.md`](reports/M23.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M24 — task history, content versions and reproduction | [`docs/reports/M24.md`](reports/M24.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M25 — agent workflows (user-directed and AI-directed) | [`docs/reports/M25.md`](reports/M25.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M26 — resource and job scheduler | [`docs/reports/M26.md`](reports/M26.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M27 — Simple Mode and unified search | [`docs/reports/M27.md`](reports/M27.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M28 — Researcher Mode | [`docs/reports/M28.md`](reports/M28.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M29 — GUI core workflows | [`docs/reports/M29.md`](reports/M29.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| M30 — Learning Mode | [`docs/reports/M30.md`](reports/M30.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| SDK transports - | [`docs/reports/SDK.md`](reports/SDK.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |
| Status report — SDKs, CI, and what is left | [`docs/reports/STATUS.md`](reports/STATUS.md) | Historical checkpoint: implementation scope, tests and limitations at that report’s date. Use current guides for today’s status. |

## Historical verification transcripts

| Human-readable name | Document | Meaning and purpose |
|---|---|---|
| Chat streaming, over a real socket — recorded verification | [`docs/verification/chat-streaming-over-a-real-socket.md`](verification/chat-streaming-over-a-real-socket.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| Gemini acceptance transcript — recorded verification | [`docs/verification/gemini.md`](verification/gemini.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M17–M19 and initial environment — recorded verification | [`docs/verification/m17-m19-and-initial-environment.md`](verification/m17-m19-and-initial-environment.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M20 acceptance transcript — recorded verification | [`docs/verification/m20.md`](verification/m20.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M21 acceptance transcript — recorded verification | [`docs/verification/m21.md`](verification/m21.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M22 acceptance transcript — recorded verification | [`docs/verification/m22.md`](verification/m22.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M23 acceptance transcript — recorded verification | [`docs/verification/m23.md`](verification/m23.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M24 acceptance transcript — recorded verification | [`docs/verification/m24.md`](verification/m24.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M25 acceptance transcript — recorded verification | [`docs/verification/m25.md`](verification/m25.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M26 acceptance transcript — recorded verification | [`docs/verification/m26.md`](verification/m26.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M27 acceptance transcript — recorded verification | [`docs/verification/m27.md`](verification/m27.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M28 acceptance transcript — recorded verification | [`docs/verification/m28.md`](verification/m28.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M29 acceptance transcript — recorded verification | [`docs/verification/m29.md`](verification/m29.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M30 acceptance transcript — recorded verification | [`docs/verification/m30.md`](verification/m30.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M31 acceptance transcript — recorded verification | [`docs/verification/m31.md`](verification/m31.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M32 acceptance transcript — recorded verification | [`docs/verification/m32.md`](verification/m32.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M33 acceptance transcript — recorded verification | [`docs/verification/m33.md`](verification/m33.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M34 acceptance transcript — recorded verification | [`docs/verification/m34.md`](verification/m34.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M35 acceptance transcript — recorded verification | [`docs/verification/m35.md`](verification/m35.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M36 acceptance transcript — recorded verification | [`docs/verification/m36.md`](verification/m36.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M37 acceptance transcript — recorded verification | [`docs/verification/m37.md`](verification/m37.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M38 acceptance transcript — recorded verification | [`docs/verification/m38.md`](verification/m38.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M39 GUI/acceptance checkpoint (not milestone completion) — recorded verification | [`docs/verification/m39-gui-acceptance-checkpoint-not-milestone-completion.md`](verification/m39-gui-acceptance-checkpoint-not-milestone-completion.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| M39–M41 final combined gate — recorded verification | [`docs/verification/m39-m41-final-combined-gate.md`](verification/m39-m41-final-combined-gate.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| SDK acceptance transcript — recorded verification | [`docs/verification/sdk.md`](verification/sdk.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| The GUI rebuild and the Research completion model (schema v20) — recorded verification | [`docs/verification/the-gui-rebuild-and-the-research-completion-model-schema-v20.md`](verification/the-gui-rebuild-and-the-research-completion-model-schema-v20.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |
| Tool calling, measured for the first time — recorded verification | [`docs/verification/tool-calling-measured-for-the-first-time.md`](verification/tool-calling-measured-for-the-first-time.md) | Preserved command output and observed results for this run, including its old counts and environment. Evidence, not a current guarantee. |

## Document review policy

All Markdown documents are read by the documentation review procedure. Current guides
are checked for local links and explicit source-file references; archived reports and
transcripts retain the paths and counts of their run. Historical decision/changelog
entries likewise must not be rewritten as though old results came from the current tree.
Read `docs/audit/documents.tsv` for per-document classification and check outcomes.
Mechanical checks do not prove all prose or command examples correct; safety/status
corrections are also reviewed against the relevant implementation.

## Licence, data and structured evidence

| Human-readable name | File | Meaning and purpose |
|---|---|---|
| MIT licence | [`LICENSE`](../LICENSE) | Legal permission and warranty limits for using and distributing the code. |
| Package and tool configuration | [`pyproject.toml`](../pyproject.toml) | Package version, supported Python floor, optional dependencies, console entry point and test/package settings. |
| Retrieval evaluation corpus | [`data/retrieval_set.json`](../data/retrieval_set.json) | Machine-readable queries/relevance expectations used to measure retrieval; not model weights. |
| Per-document review | [`docs/audit/documents.tsv`](audit/documents.tsv) | Every Markdown document, title, current/history classification, hash and link/source-reference findings. |
| Per-file structural audit | [`docs/audit/files.tsv`](audit/files.tsv) | One row per audited file: size, hash, purpose, structural checks and result; excludes its own hash. |
| Per-file measured coverage | [`docs/audit/coverage.tsv`](audit/coverage.tsv) | Statement/branch evidence and missing line ranges from the final measured test run; not a claim of exhaustive coverage. |
| Extraction preservation checks | [`docs/audit/refactor-contracts.tsv`](audit/refactor-contracts.tsv) | Counts and outcomes of AST comparison evidence for 27 original modules (prior rows historical); preserved bodies and intentional hardening changes are distinguished. |
| Remaining-owner preservation contracts | [`docs/audit/orchestration-contracts.json`](audit/orchestration-contracts.json) | AST hashes for nine named owners; independent snapshots, recovered-copy limitations and intentional changes are explicit. |
| Fixed large-owner cleanup progress | [`docs/audit/cleanup-progress.tsv`](audit/cleanup-progress.tsv) | The 36 named originals and their baseline/current acceptance states. Percentage applies only to this fixed structural backlog, not product completion. |
| Folder responsibility inventory | [`docs/audit/folders.tsv`](audit/folders.tsv) | Every non-generated repository folder and its ownership role. |
| Final local audit check outcomes | [`docs/audit/checks.tsv`](audit/checks.tsv) | Full-suite/static/GUI/wheel results and final exit status for all 25 acceptance procedures; historical CI is explicitly separate. |
| CI run history | [`docs/ci/RUNS.tsv`](ci/RUNS.tsv) | Compact history of recorded runs and check summaries. |
| Selected CI run metadata | [`docs/ci/meta.tsv`](ci/meta.tsv) | The commit, branch, run times and failure count for the selected historical run. |
| Selected CI step outcomes | [`docs/ci/status.tsv`](ci/status.tsv) | Per-step exit outcomes for the selected historical CI run. |
| Real model execution proof | [`docs/ci/model-proof.json`](ci/model-proof.json) | Structured evidence of the model/runtime used in the recorded CI run. |
| Historical tunnel endpoint | [`docs/ci/tunnel-url.txt`](ci/tunnel-url.txt) | The URL used by a recorded public-tunnel test; not a live service address. |

`.github/workflows/model-matrix.yml` is executable CI configuration, `.ci/trigger`
requests a run, and `.gitignore` excludes local/generated artifacts. They are not
user guides. Verification scripts are executable procedures, indexed with every
other source file in the per-file audit. No temporary test logs, build artifacts or
local environments are part of this document catalogue.
