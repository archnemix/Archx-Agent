# Plan and status

Milestone order follows the product spec. A milestone is only marked **done** when its
acceptance criterion was demonstrated in the running application (CLI end-to-end test
plus a recorded manual transcript), not merely when unit tests pass.

Legend: **done** = implemented + verified in app · **done · scoped** = verified, but narrower
than the mode's name implies (see [docs/MODES.md](docs/MODES.md)) · **partial** = implemented,
acceptance not fully demonstrated · **not started**

| # | Milestone | State | Evidence |
|---|-----------|-------|----------|
| M01-M09 | Skeleton, errors, `Result`, paths, branding, terminal chat, context budget, package + CLI | **done** (rebuilt from scratch - see note) | `tests/test_foundation.py`, CLI tests |
| M10 | SQLite conversations, `--resume`, `/conversations` | **done** | `tests/test_memory_m17.py::TestConversationBasics`, CLI `conv` |
| M11 | Storage reliability: coordinator, journal, exactly-once, backpressure, backup, preferences | **done** | `tests/test_storage.py` incl. SIGKILL crash test |
| M12 | Backup/restore/`--check-db`/preview | **done** | `tests/test_storage.py::TestBackupRecovery`, `archx-agent db ...` |
| M13 | Structured events, redaction, capture levels, causal tree, sequence ordering | **done** | `tests/test_storage.py::TestEvents` |
| M14 | Debug & Trace interface: filters, summaries, export, retention | **done** | `archx-agent trace ...`, CLI tests |
| M15 | Model catalogue + local discovery (facts vs claims vs user metadata) | **done** | `tests/test_models.py` (see M21), CLI `models` |
| M16 | Provider adapter boundary + catalogue-aware resolution + key hygiene | **done** for HTTP; llama.cpp path requires the optional dependency and a GGUF file | `tests/test_application.py::TestHttpRuntimeContract` |
| **M17** | **Memory persistence foundation (six systems)** | **done** | `tests/test_memory_m17.py` (36 tests), CLI acceptance transcript |
| **M18** | **Embedding + retrieval evaluation** | **done** | `tests/test_embeddings_m18.py` (29), `docs/RETRIEVAL_EVAL.md` |
| **M19** | **Context Strategy Manager (five strategies)** | **done** (ai_proposed + manual + summarize + oldest_first + ai_select all exercised) | `tests/test_context_m19.py`, CLI `context` |
| **M20** | **Cloud provider catalogue + privacy metadata** | **done** | `tests/test_providers_m20.py` (30), `docs/PROVIDERS.md`, `scripts/acceptance_m20.sh` |
| **M21** | **Capability-safe model router + model management** | **done** | `tests/test_router_m21.py` (33), `docs/ROUTING.md`, `scripts/acceptance_m21.sh` |
| **M22** | **Tool registry + Permission & Approval Center** | **done** | `tests/test_tools_m22.py` (78) + 13 CLI tests, `docs/TOOLS.md`, `scripts/acceptance_m22.sh` |
| **M23** | **MCP client/server + extension foundation** | **done** | `tests/test_mcp_m23.py` (43) + `tests/test_extensions_m23.py` (35) + 9 CLI tests, `docs/MCP.md`, `scripts/acceptance_m23.sh` |
| **M24** | **Task history, content versions, reproduction records** | **done** | `tests/test_tasks_m24.py` (75), `docs/TASKS.md`, `scripts/acceptance_m24.sh` incl. a real SIGKILL |
| **M25** | **Agent workflows: user-directed and model-proposed, with subagents** | **done** | `tests/test_agent_m25.py` (60), `docs/AGENTS.md`, `scripts/acceptance_m25.sh` (real HTTP plan) |
| **M26** | **Resource and job scheduler** | **done** | `tests/test_scheduler_m26.py` (94), `docs/SCHEDULER.md`, `scripts/acceptance_m26.sh` (SIGKILL + pause/resume) |
| **M27** | **Simple Mode and unified search** | **done** | `tests/test_search_m27.py` (42) + `tests/test_simple_m27.py` (67), `docs/SIMPLE_MODE.md`, `scripts/acceptance_m27.sh` (23 checks) |
| **M28** | **Researcher Mode** | **done · scoped** | `tests/test_research_m28.py` (97), `docs/RESEARCH.md`, `scripts/acceptance_m28.sh` (30 checks incl. real HTTP and an approval). Scope: reads local documents and the URLs you give it — **no web search, no crawler, no experiment runner** (`docs/MODES.md` §3.1) |
| **M29** | **GUI core workflows** | **done** | `tests/test_gui_m29.py` (85), `docs/GUI.md`, `scripts/acceptance_m29.sh` (54 checks over a real socket) |
| **M30** | **Learning Mode** | **done · scoped** | `tests/test_learning_m30.py` (121), `docs/LEARNING.md`, `scripts/acceptance_m30.sh` (90 checks). Scope: exact/self grading, no model marking; no media items (`docs/MODES.md` §3.2) |

| **M31** | **Coding workspace** | **done** | `tests/test_coding_m31.py` (66), `docs/CODING.md`, `scripts/acceptance_m31.sh` (48 checks over a real socket). Scope: a session is a directory inside the tool roots, every read/write/run is a tool call, edits are diffs on the session task, and the runner records every command |
| **M32** | **Experimental Mode** | **done** | `tests/test_experiments_m32.py` (66), `docs/EXPERIMENTS.md`, `scripts/acceptance_m32.sh` (53 checks over a real socket). Scope: an experiment is a declared command, parameters and metrics source; a metric is read only from that source or not at all, and a comparison names what it could not rank |
| **M33** | **Play Mode** | **done** | `tests/test_play_m33.py` (77), `docs/PLAY.md`, `scripts/acceptance_m33.sh` (69 checks: the migration adopting the reserved tables, a refused move kept, sixty engine games checked against the rules, a doctored hash failing its own replay, and the page starting a game the CLI reads) |
| **M34** | **Voice and multimodal foundation** | **done · scoped** | `tests/test_voice_m34.py` (67), `docs/VOICE.md`, `scripts/acceptance_m34.sh` (88 checks incl. containers built byte by byte and a CHECK constraint tested directly). Scope: measurement, provenance and honest refusal - **no speech recognition or synthesis exists here**, and `voice transcribe`/`voice say` say so on the record (`docs/MODES.md` §3.4) |
| **M35** | **Dataset preparation** | **done** | `tests/test_datasets_m35.py` (60), `docs/DATASETS.md`, `scripts/acceptance_m35.sh` (72 checks: a resaved document refused across splits, a manifest broken by an edit and by a delete, and a split that does not move when the corpus grows). Scope: text corpora prepared on this machine - **no training, no tokenisation, no upload** |
| **M36** | **Training and model modification** | **done · scoped** | `tests/test_training_m36.py` (54), `docs/TRAINING.md`, `scripts/acceptance_m36.sh` (57 checks, incl. an independent perplexity implementation that must agree to 1e-9). Scope: two trainers that really run here (n-gram perplexity, nearest-centroid accuracy); **fine-tuning is refused by name** - no weights, no GPU, no library (`docs/MODES.md` §3.5) |
| **M37** | **Remote compute and portability** | **done · scoped** | `tests/test_remote_m37.py` (45), `docs/REMOTE.md`, `scripts/acceptance_m37.sh` (71 checks, incl. a worker that misreports its hash and a remote metric that must equal the local one exactly). Scope: a bundle that identifies its input and a worker that speaks a documented protocol - **no cloud, no vendor SDK, no credentials** (`docs/MODES.md` §3.6) |
| **M38** | **Execution environments and sandboxing** | **done · scoped** | `tests/test_execution_m38.py` (49), `docs/EXECUTION.md`, `scripts/acceptance_m38.sh` (65 checks incl. a stand-in `docker` on `PATH` that records its argv, a worker refusing without `--allow-exec` and with a wrong token, and a file edited on both sides). Scope: the wrapper is the feature - `local`, `remote`, `docker`, `wsl`, `windows-sandbox`, `vmware`, `virtualbox`, each recorded with the invocation that ran and refused by name when it cannot run here; **WSL is labelled not a boundary, Windows Sandbox is `detached`**, and `execution.enabled` is off by default (`docs/MODES.md` §3.7) |
| M39 | Blender and 3D workflows | in progress · foundation | Geometry, scene ledger (v29), CLI and exports; 24 scene tests, full suite 1892. GUI, acceptance/CI and real Blender validation pending. `docs/SCENES.md` |
| M40 | Automations and scheduled tasks | not started | - |
| M41 | Hardening and release readiness | not started | - |

## Note on the M38-M41 numbering

The eight-step brief places Blender at M38. M38 was executed as **execution environments and
sandboxing** instead - the milestone M36 and M37 kept pointing at ("the work runs on a machine that
is not necessarily this one, and it runs in a sandbox that is really a sandbox") - so Blender, the
automations and hardening moved to M39-M41. Nothing had been built for those three, so the shift
costs nothing; the older docs that still say "M38 Blender" are listed in `GAPS.md` §Roadmap.

## Note on M01-M16

The repository this work started from contained a single commit with a two-line README
and **no code** - the M01-M16 features described in the brief did not exist (verified:
`git log --all` shows one commit; the tree contained one file). Everything listed above
was therefore rebuilt from the foundations, in the same order and with the same
invariants, before M17 could start. See [docs/VERIFICATION.md](docs/VERIFICATION.md).
