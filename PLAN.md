# Plan and status

Milestone order follows the product spec. A milestone is only marked **done** when its
acceptance criterion was demonstrated in the running application (CLI end-to-end test
plus a recorded manual transcript), not merely when unit tests pass.

Legend: **done** = implemented + verified in app · **partial** = implemented, acceptance
not fully demonstrated · **not started**

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
| M26 | Resource and job scheduler | next | - |
| M27 | Simple Mode and search | not started | - |
| M28 | Researcher Mode | not started | - |
| M29 | GUI core workflows | not started | - |
| M30 | Learning Mode | not started | - |
| M31 | Coding workspace | not started | - |
| M32 | Experimental Mode | not started | - |
| M33 | Play Mode | not started | - |
| M34 | Voice and multimodal foundation | not started | - |
| M35 | Dataset preparation | not started | - |
| M36 | Training and model modification | not started | - |
| M37 | Remote compute and portability | not started | - |
| M38 | Blender and 3D workflows | not started | - |
| M39 | Automations and scheduled tasks | not started | - |
| M40 | Hardening and release readiness | not started | - |

## Note on M01-M16

The repository this work started from contained a single commit with a two-line README
and **no code** - the M01-M16 features described in the brief did not exist (verified:
`git log --all` shows one commit; the tree contained one file). Everything listed above
was therefore rebuilt from the foundations, in the same order and with the same
invariants, before M17 could start. See [docs/VERIFICATION.md](docs/VERIFICATION.md).
