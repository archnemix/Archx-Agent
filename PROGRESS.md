# Progress

Last updated: M30 complete (Learning Mode), research completion, and a real Gemini provider
(the M15/M16 model-runtime boundary, extended past M30). Next: M31.

## Verified in this session

Everything below was executed in this environment and observed. Commands and outputs are
reproduced in [docs/VERIFICATION.md](docs/VERIFICATION.md).

| Milestone | What was verified | How |
|-----------|-------------------|-----|
| Gemini (M15/M16 boundary, added after M30) | a second, non-OpenAI wire protocol is a first-class runtime: `contents`/`systemInstruction`/`generationConfig` built from an Archx transcript (consecutive same-role turns merged), `candidates[0].content.parts[].text` parsed with `thought` parts skipped, `finishReason` and `usageMetadata` mapped, streaming over `alt=sse`; the key is sent only as `x-goog-api-key`, resolved from a `secret://` reference at request time, registered with the redactor and wiped on close, and a literal key is refused with exit 2; 400/401/403, 404, 429-quota, 429-burst, 5xx, non-JSON, empty-with-SAFETY and `promptFeedback.blockReason` map to distinct errors with their own retry flags; the four-rung consent ladder applies to it because the gate reads `NETWORK_RUNTIMES`; the GUI Models panel registers a model, probes it, and walks the same four rungs with the same rules | `pytest tests/test_gemini_m21.py` (56); `scripts/acceptance_gemini.sh` (60 self-checking assertions over a real socket against `scripts/gemini_protocol_stub.py`); `scripts/gui_smoke.mjs` (jsdom) |
| M28+e | a research run can be marked done and reopened: `closed_at`/`closed_note` (schema v20) are written only by an explicit close, so a run's own `status`, `coverage` and `evidence_count` are untouched by the judgement; a second close and a reopen-of-an-open run are conflicts naming the first state, not silent no-ops; `research list --closed/--open`, open/closed counts in `research stats`, `POST /api/research/{id}/{close,reopen}`, a *mark complete* prompt with an optional note and *reopen* in the page, and both directions traced | `pytest tests/test_research_close.py` (28); `scripts/acceptance_research_close.sh` (35 self-checking assertions over a real socket: the migration, a real local run, close/reopen over HTTP and the CLI, the filters, the trace, and the page wiring) |
| M30 | a learning goal carries criteria and is a record; its items carry a question, an optional answer key, an ordered hint ladder and their own SM-2-lite schedule; an answer is graded **exact** (normalised comparison against the expected answer) or **self** (1-5) and the row says which - there is no model grading; `learning.try_first` refuses a hint before the first attempt (CLI exit 3, GUI 409 `try_first`) and the ladder is revealed one level at a time; every answer returns interval, ease, streak, status, due date and the sentence explaining them; `next` says why it chose that item and refuses with exit 3 when nothing is due; a session is a real `learning` task with a summary; a plan without a model declares `planned_by = rules`, uses only the learner's own words and never invents an answer key; completion is explicit (`goal complete`), never inferred from a mastered deck; the GUI adds items, reveals hints and answers through the same service, and both directions are checked | `pytest tests/test_learning_m30.py` (121); `scripts/acceptance_m30.sh` (89 self-checking assertions incl. a refused hint, a lapse, a self-graded item, an item added in the GUI visible to the CLI, and a delete that takes the children) |
| M29 | a local GUI serves the same app over a socket: every panel (status, chat, research, search, tasks, jobs, approvals/grants, memory, models) calls the real managers, so a chat turn made in the browser is a `chat` task the CLI can show, a memory is a real memory and a research run is a real run with the same `[S<n>]` labels; the page is public but every API call needs the per-process token (header, bearer, query, or an HttpOnly SameSite cookie exchanged at `POST /api/session`); a cookie-authenticated write without `X-Archx-Request: gui` is 403, `OPTIONS` is 405 and no CORS header is ever sent; assets are served by exact name so no path escapes; web research without `net.fetch` is a 403 naming the approval, approving it in the GUI mints exactly that grant, the same request then reads a real page, and revoking removes it; a non-loopback bind without `--allow-remote` exits 2 | `pytest tests/test_gui_m29.py` (85); `scripts/acceptance_m29.sh` (55 self-checking assertions over a real socket, including the approval, a real web-research run, a spent one-shot grant and a queued job run from the page) |
| M28 | a research run stores a plan that names its author (`model`/`rules`/`user`), reads real local documents and (opt-in) real HTTP pages through the `net.fetch` capability, records every source including the ones that failed, hashes what it read, drops model quotes that are not in the excerpt, demotes uncited model prose instead of presenting it as a finding, computes coverage, writes a report with `[S<n>]` citations, attaches it to a research task as an artifact, and reports "I found no evidence" with exit 3 when there is none; `research verify` re-checks every citation independently | `pytest tests/test_research_m28.py` (97); `scripts/acceptance_m28.sh` (30 self-checking assertions incl. a real local HTTP site, an approval refusal, a spent grant, a 404, a binary page and a queued job) |
| M27 | unified search finds a query in conversations, memory, tasks, workflows, projects, artifacts, tools and files with one shared scoring rule, per-source caps and honest `degraded`/`skipped` notes; a source that fails degrades the report instead of failing the search; file search stays inside the tool roots, skips binaries/oversize/noise directories and never writes; Simple Mode classifies eight intents and prints the reason it chose one, stores `remember` as a real permanent memory with the duplicate check intact, reads `status` from the live app, and refuses a missing model, a missing grant or a checkpoint by printing the exact next command and exiting 4 without creating a grant | `pytest tests/test_search_m27.py` (42) + `pytest tests/test_simple_m27.py` (67); `scripts/acceptance_m27.sh` (23 self-checking assertions incl. approve-then-run and a spent one-shot grant) |
| M26 | a submitted job is a durable `queued` row with a deadline and an attempt budget; claiming is one transaction (six threads over 24 jobs claim each exactly once); priority and `queue_seq` decide order; `dedupe_key` makes submission idempotent; a `command` job runs a real child in its own session and records exit code, stdout, stderr and duration; a non-zero exit fails the job and its task; a `workflow` job runs an M25 workflow and still cannot bypass the permission centre; a hard deadline kills the child (`sleep 30`, timeout 1, ~1s, no process left) and fails the job; a `SIGKILL`ed worker's job is requeued while attempts remain and `interrupted` when they do not; pause stops a running workflow at a step boundary with a durable cursor, and resume continues from it without replaying a step or duplicating the task; concurrency and the CPU/memory budget limit what runs at once (measured by wall clock); `jobs run` exits 3 rather than claiming success when work remains | `pytest tests/test_scheduler_m26.py` (94); `scripts/acceptance_m26.sh` (23 self-checking assertions incl. a real SIGKILL and a cross-process pause/resume) |
| M24 | every chat turn and tool task is a durable record with a sequence-ordered timeline; terminal states are final; a task whose owner process died is marked `interrupted` on the next open (manual tasks and tasks owned by other live processes are left alone); artifacts are references with checksums; content versions are append-only with deduplication, diffs and restore-as-new-version; reproduction derives `exact`/`partial`/`impossible` from the live environment, prints the commands that would replay the task, and `--verify` detects a removed model (exit 3) or changed settings | `pytest tests/test_tasks_m24.py` (75); `scripts/acceptance_m24.sh` (real SIGKILL, re-runs a printed command) |
| M25 | workflow definitions are strict data (unknown kinds/fields/tools/variables are refused); model steps reuse the chat path and tool steps the permission centre; a model-proposed plan is stored `proposed` and cannot run without `--approve`; approving a plan grants no capability; checkpoints refuse before anything runs; subagents are child tasks with their own conversations; budgets (steps, wall clock, tokens, subagents) stop the run and name themselves; a cancel from another part of the process stops the next step | `pytest tests/test_agent_m25.py` (60); `scripts/acceptance_m25.sh` (real HTTP planning round trip) |
| M01-M09 | package installs, `archx-agent --version`, helper invariants (paths, Result, errors, tokens, redaction, config) | `pytest tests/test_foundation.py tests/test_config.py`, CLI smoke |
| M10 | conversation create/append ordering by sequence, context clear preserves history, restart-safe reading | `pytest tests/test_memory_m17.py::TestConversationBasics` |
| M11 | committed-only success, exactly-once by op id, durable two-phase + replay, backpressure=PENDING, graceful drain, multi-thread safety, **SIGKILL mid-write recovery**, multi-process writes | `pytest tests/test_storage.py` |
| M12 | backup/verify/preview/restore-aside, tamper detection, retention | `pytest tests/test_storage.py::TestBackupRecovery`, `archx-agent db ...` |
| M13 | sequence ordering, capture levels, redaction on write and export, causal tree, retention keeps errors longer | `pytest tests/test_storage.py::TestEvents` |
| M14 | trace filters, errors, summary, JSONL export, retention, tree | `archx-agent trace ...` + CLI tests |
| M15 | discovery of GGUF files, facts/claims split, states, preference per task, verification recording | `archx-agent models ...` (see model tests) |
| M16 | OpenAI-compatible HTTP runtime against a real local server: success, 401/402/404/429-rate/429-quota/500, connection refused, malformed body, key never leaked | `pytest tests/test_application.py::TestHttpRuntimeContract` |
| M17 | all six memory kinds stored/retrieved/edited/deleted through the CLI with scope + provenance, duplicate rejection, slot supersession, artifact checksum, restart survival, crash replay, every write traced | `pytest tests/test_memory_m17.py` + CLI acceptance |
| M18 | float32 vectors with model identity, embedding states, cache checksums, degraded keyword fallback, hybrid ranking, model-change staleness, cross-model refusal, full evaluation report | `pytest tests/test_embeddings_m18.py`; `archx-agent eval retrieval` |
| M19 | five strategies build manifests with reasons; oldest-first preserves history; manual selection; summarise keeps originals + source range; ai_proposed requires approval | `pytest tests/test_context_m19.py`; `archx-agent context ...` |
| M20 | provider catalogue keeps facts/claims/user confirmations apart; loopback = local (derived); remote is blocked until privacy confirmed + consent recorded + `model.local_only=false`; availability probe distinguishes reachable/auth/404/429/500/refused; quotas enforced; usage and cost attributed per request | `pytest tests/test_providers_m20.py` (30); `scripts/acceptance_m20.sh` (real HTTP server) |
| M23 | MCP client over real stdio and HTTP transports with deadlines; discovery recorded but registration requires trust+enable; every remote call needs an `mcp.call` grant; the optional MCP server is off by default, exposes a whitelist and uses the distinct `mcp-server` subject; extensions are installed/trusted/enabled separately, their manifests cannot invent capabilities or escape their directory, and their programs run with a rebuilt environment; dynamic tools are restored from the database on open | `pytest tests/test_mcp_m23.py` (43) + `tests/test_extensions_m23.py` (35) + `tests/test_cli.py::TestCliMcp/TestCliExtensions` (9); `scripts/acceptance_m23.sh` |
| M22 | tools declare capability/risk/dry-run; ungranted operations are refused with an approval id; approval mints exactly the requested grant; scoped grants (once/task/conversation/project/persistent) are checked, single-use grants consumed before the work; sandbox refuses traversal, absolute escapes and symlink escapes; argv-only processes with a denylist, minimal env and timeouts; every attempt (including denials) has a `tool_runs` row and trace events | `pytest tests/test_tools_m22.py` (78) + `tests/test_cli.py::TestCliTools` (13); `scripts/acceptance_m22.sh` (real files and processes) |
| M21 | capability states with evidence (verified/inferred/unverified/unsupported/unavailable); eligibility before score; a model whose runtime is missing is refused; probes record measurements; `require_verified` policy; remote never auto-chosen; fallback is traceable and never silent | `pytest tests/test_router_m21.py` (33); `scripts/acceptance_m21.sh` |

**Test suite: 984 tests, 0 failures, 0 skipped** on Python 3.11.2 (see note in GAPS
about 3.13 and about llama.cpp).

## Acceptance evidence

* M17: `docs/VERIFICATION.md#m17-acceptance` - each of the six kinds added, listed,
  shown with provenance, edited (version 2 + history), searched, retrieved under a budget
  and deleted, with trace events for every write.
* M18: `docs/RETRIEVAL_EVAL.md` - keyword nDCG 0.637, semantic (lexical-hash) 0.839,
  hybrid 0.850, on a 20-item corpus with 12 graded queries.
* M19: `docs/VERIFICATION.md#m19-acceptance` - manifests for all five strategies,
  including omitted reasons and proof that stored history is unchanged.
* M25: `docs/VERIFICATION.md#m25-acceptance` - a four-step user-directed workflow, a
  subagent with its own conversation, an `fs.write` refused for lack of a grant, an
  AI-directed plan parsed from a **real HTTP** response, the approval gate (exit 4), a plan
  naming a nonexistent tool refused before storage, then grant + `agent rerun`.
* M24: `docs/VERIFICATION.md#m24-acceptance` - a chat turn and a tool task become records;
  an artifact goes through v1 -> v2 -> restore-as-v3 with a real diff; a deterministic task
  reproduces `exact`; a simulated model is `partial`; removing the model makes `--verify`
  report `impossible` (exit 3); a **real SIGKILL** of a process that started a task leaves
  it `interrupted` on the next command.
* M23: `docs/VERIFICATION.md#m23-acceptance` - a real MCP server process is discovered,
  trusted, enabled, then refused until `mcp.call` is granted; a real extension program runs
  only after install+trust+enable+grant; and our own MCP server (in a separate process) is
  driven by our own client, with a second, independent denial for the `mcp-server` subject.
* M22: `docs/VERIFICATION.md#m22-acceptance` - a real write is refused, approved, then
  really written; the single-use grant is spent; a read in another conversation is
  denied; traversal/absolute/symlink escapes are refused; a real subprocess runs, a real
  failing command is a failed run, a real `sleep 30` is killed at 2s, and `sudo`/`dd` are
  refused in a way that cannot be approved.
* M26: `docs/VERIFICATION.md#m26-acceptance-transcript` - four one-second commands finish in
  about a second at concurrency 4, `sleep 30 --timeout 1` is killed in about a second with
  nothing left behind, a workflow is paused by one process and resumed by another with every
  step run exactly once, a `SIGKILL`ed worker's job is recovered on attempt 2, and an
  ungranted `fs.write` step fails the job without writing a file.
* M30: `docs/MODES.md` is the honest index - every mode's purpose, its controls, the tools
  behind them, and the two `partial` marks (Research: no web search, crawl or experiments;
  Learning: no model grading, no media). The GUI sidebar groups modes/work/control, the top bar
  lists each mode's tools from live data, the palette has dark and light variants, and
  `tests/test_gui_m29.py` now also fails if a class in the page has no rule behind it.
* M29: `docs/VERIFICATION.md#m29-acceptance-transcript` - a fresh home, the installed
  console script, and a real socket: the page and its assets served with the security
  headers, the API refusing an unauthenticated request, a chat turn recorded as a task, a
  memory the CLI can show, a duplicate refused with 409, one search across the sources, web
  research refused with an approval, approved in the GUI, the same request then reading a
  real local page and verifying its citations, the one-shot grant spent, a standing grant
  revoked, a queued job run from the page, the cookie/CSRF boundary in both directions, and
  the port closed on Ctrl-C.
* M28: `docs/VERIFICATION.md#m28-acceptance-transcript` - a rules plan and a user-directed
  plan, an extractive report whose citations all resolve, a question with no evidence
  (incomplete, exit 3), web research refused for lack of `net.fetch` with no grant created,
  then granted and reading two real pages (titles, checksums) while recording a 404 and a
  binary page as failures, a private address refused even with the grant, the same question
  queued and run as a `research` job, and a delete that removes the run and its sources.
* M27: `docs/VERIFICATION.md#m27-acceptance-transcript` - one `search` returns a memory, a
  conversation, two tasks, a workflow and a file for the same word, names the source counts,
  reports `keyword-only` and skips a binary file; `simple ask` answers the same question with
  the reason; `remember` stores a fact and a preference and reports the duplicate on a second
  attempt; `status` reads real counts and labels the test double; a workflow refused for a
  missing `fs.read` prints `approvals approve ap_...`, creates no grant, and afterwards the
  approved run completes exactly once and the one-shot grant is spent.
* M21: `docs/VERIFICATION.md#m21-acceptance` - a discovered GGUF is refused because
  llama.cpp is missing (not routed to and silently failed), a probe flips `inferred` to
  `verified`, `require_verified` refuses then allows, a remote model is never chosen
  automatically, and a dead endpoint falls back visibly.
* M20: `docs/VERIFICATION.md#m20-acceptance` - a real OpenAI-compatible HTTP server is
  registered as a local provider, probed, chatted through, and charged for; a cloud
  provider is refused until confirmed + consented; a remote model is refused while
  `local_only` is true.

## Next steps (in order)

1. M31: Coding workspace - editing, running and testing code under the permission centre,
   with diffs as artifacts and reproducible tasks.
2. M32 onward per PLAN.md.

## Known breakage

None known. `GAPS.md` lists limitations (no reachable model weights, single Python
version, no model grading in Learning Mode by design).
