# Changelog

All notable changes. Format loosely follows Keep a Changelog; versions track the
milestone block rather than semantic-release cadence, because M01-M20 are one development series.

## [Unreleased]

### Changed
- **The GUI is rebuilt.** One shell (`index.html` + `style.css` + `app.js`, still no build
  step, no CDN and no inline style): a 258px sidebar with Modes · Work · Control that
  collapses to a 64px icon rail and remembers it, a top bar with the current mode's live tool
  chips, and three themes (dark, light, soft) as pure token swaps.
- Chat is a transcript: avatars, per-message copy on hover, markdown replies with a language
  label and copy button on every code block and copy-as-CSV / save on every table, four
  empty-state prompts that fill the composer, and three dots while a turn is in flight.
- Every panel gained the same furniture: pickers that mark the open record, sticky table
  headers, inline refusals carrying the error code, and toasts for what the server answered.
- Denying an approval, revoking a grant and cancelling a job now ask first, in a dialog that
  names what will happen; `Escape` dismisses it.
- `docs/GUI.md` rewritten for the new shell; `scripts/acceptance_m29.sh` now checks the three
  palettes and that no `style=`/`onclick=` attribute exists anywhere in the page.

### Added
- **Research closure** (schema **v20**, `RESEARCH_CLOSURE_V20`): `research close RUN [--note]`
  and `research reopen RUN`, `research list --closed/--open`, open/closed counts in
  `research stats`, `POST /api/research/{id}/{close,reopen}`, and *mark complete* / *reopen* in
  the GUI behind a note prompt. `closed_at` is written only by an explicit close, so a run's
  own status and coverage are never rewritten by a judgement call.
- `scripts/acceptance_research_close.sh` (35 self-checking assertions over a real socket) and
  `tests/test_research_close.py` (28 tests).
- `scripts/seed_demo.sh`: builds the preview workspace (`~/.archx-demo`) through the ordinary
  CLI - a scripted model, one conversation, three memories, a learning goal with a hint
  ladder and two attempts, a local research run over those memories, and a queued job.
  Idempotent, never destructive, so a restored sandbox can rebuild the demo home instead of
  losing it.

## [0.30.0] - M30 Learning Mode

### Added
- `managers/learning.py`: goals, items, sessions and attempts as records over the v8
  learning tables, with coordinator write handlers, prefix resolution, a due query, stats,
  keyword search and a cascading delete. An item carries its own schedule: status, ease,
  interval, streak, lapses, due date and counts.
- Schema **v19** (`LEARNING_V19`): `learning_sessions` and `learning_attempts`, plus the
  columns the item schedule needs on the v8 tables. No migration was renumbered.
- `application/learning.py`: `grade_answer` (exact / self only), the SM-2-lite `schedule`
  with a returned `why`, `next_item`/`ask`, `hint` with `learning.try_first`,
  `start_session`/`review`/`end_session`, `plan` (model JSON validated, rules fallback with
  the reason), and `report`/`write_report`. Refusals: `HintBeforeAttempt`, `NothingToStudy`.
- CLI: a `learning` group - `goal {create,list,show,edit,complete,delete}`,
  `item {add,list,edit,delete}`, `plan`, `next`, `ask`, `hint`, `answer`,
  `session {start,list,end}`, `review`, `stats`, `search`, `report`. A hint before an attempt
  exits 3; nothing-to-study exits 3.
- `learning item edit`: `--prompt`, `--expected`, `--hint` (replace), `--add-hint` (append),
  `--clear-hints`, `--explanation`, `--subtopic`. The ladder cap applies here too.
- GUI: a **Learning** tab (goals, criteria, next-up with the `why`, add an item, per-click
  hint rung, answer form, item/schedule table, sessions, propose-items, start-a-review) and
  eight `/api/learning*` routes, including `POST /api/learning/goals/{id}/items`.
- Config: `learning.active_goal_limit`, `learning.try_first`, `learning.daily_review_limit`,
  `learning.max_hints`, `learning.mastery_streak`, `learning.start_ease`, `learning.min_ease`,
  `learning.max_plan_items`.
- `docs/LEARNING.md`, `tests/test_learning_m30.py` (121 tests), `scripts/acceptance_m30.sh`
  (89 checks on a fresh home, half through a real socket).

### Changed
- **The GUI was rebuilt around modes.** A left rail groups the panels into Modes (Chat,
  Research, Learning), Work (Search, Tasks, Jobs) and Control (Access, Memory, Models,
  Status); the header names the mode, says what it is for, and lists the tools *that mode*
  has from live data (`net.fetch: not granted`, `model: none usable`, `grading: exact or
  self`). Same shell everywhere, different controls - which is what makes the modes
  comprehensible rather than ten tabs.
- A tokenised stylesheet: four surface levels, three text levels, semantic colours, one
  accent per mode; a dark palette and a light palette (`data-theme`), following the system
  preference on first visit and remembering the choice.
- Chat is a two-pane workspace with a docked composer (Ctrl+Enter sends) that shows a
  thinking indicator instead of a fake percentage, and only auto-scrolls when you were
  already at the bottom. `Ctrl/Cmd+K` jumps to search. The sidebar collapses to an icon rail
  and stays collapsed.
- `docs/MODES.md`: the forty milestones, every mode's purpose and controls, and an explicit
  account of what "done" does **not** mean for Research (no web search, no crawl, no
  experiments) and Learning (no model grading, no media).
- The hint refusal no longer points at a command that did not exist.
- The due query now returns something already seen and due before brand-new material.
- `McpStdioClient` waits for a child's real exit status before saying the connection closed,
  so a server that dies during the handshake is reported with its status, not as a mystery.

### Notes
- There is no model grading, and no path that implies one: an answer is checked against an
  expected answer or rated by the learner, and the row says which.
- Completing a goal is an explicit act against the learner's criteria; a mastered deck does
  not complete anything.

## [0.29.0] - M29 GUI core workflows

### Added
- `interfaces/gui/`: a local web GUI served by the app itself - status, chat, research,
  search, tasks, jobs, approvals/grants, memory and models. Every control calls the same
  managers the CLI calls; the GUI adds no tables and no second permission path.
- `interfaces/gui/server.py`: `GuiApi` (routes, auth, CSRF, error mapping - no sockets, so it
  is testable) and `GuiServer` (a threading HTTP server, loopback by default).
- Static assets served from package data by exact name: one HTML page, one stylesheet, one
  script. No framework, no build step, no CDN, no inline script, CSP `'self'` only.
- Per-process access token, presented as a query parameter, a bearer header, a custom header,
  or exchanged for an `HttpOnly; SameSite=Strict` cookie at `POST /api/session`. Cookie writes
  must carry `X-Archx-Request: gui`; `OPTIONS` is refused and no CORS headers are ever sent.
- CLI: `gui serve [--host] [--port] [--allow-remote] [--token] [--open/--no-open]` and
  `gui routes`. A non-loopback bind without `--allow-remote` exits 2.
- Config: `gui.host`, `gui.port`, `gui.allow_remote`, `gui.open_browser`,
  `gui.session_minutes`, `gui.max_body_bytes`.
- `docs/GUI.md`, `tests/test_gui_m29.py` (85 tests), `scripts/acceptance_m29.sh` (54 checks
  over a real socket, including an approval and a real web-research run).

### Changed
- `gui serve` flushes its banner, so the token is visible when stdout is a pipe.
- The permission centre's `net.fetch` comment no longer says nothing implements it.

### Notes
- Binding beyond loopback is deliberately awkward: the token becomes the only boundary
  between that network and the user's data.
- The GUI is a client, not a second application: deleting it would not remove a capability.

## [0.28.0] - M28 Researcher Mode

### Added
- `managers/research.py`: research runs and sources as records - question, mode, plan,
  `planned_by`, coverage, evidence count, limitations, the report itself, and every source
  (including the ones that could not be read) with kind, ref, status, error, checksum,
  relevance, stance and the model's quotes.
- `application/researcher.py`: the pipeline - plan (validated model JSON or deterministic
  rules, or the user's own subquestions), gather (local search and/or web), read (hashed
  excerpts), judge (stance and relevance, with fabricated quotes dropped), synthesise
  (extractive answer cited line by line; uncited model prose demoted), verify (every
  citation must resolve, every claim must cite).
- `adapters/net_fetch.py` + a real `net.fetch` tool: http(s) only, no credentials in URLs,
  loopback/private/link-local/reserved addresses refused unless explicitly allowed, manual
  redirects with a hop limit re-checked per hop, byte limit, content-type allowlist, sha256,
  HTML-to-text, and every call behind the `net.fetch` capability.
- CLI: `research run|list|show|sources|report|verify|search|stats|delete`, with
  `--mode local|web|mixed`, `--url`, `--urls-from`, `--subquestion`, `--no-model`,
  `--format`, `--out`, `--allow-private-hosts`, and exit codes `0/3/4/2/1`.
- `jobs submit research` - a research run can be queued (M26's first new job kind).
- Schema v18: `research_runs` gains `mode`, `plan`, `planned_by`, `coverage`,
  `evidence_count`, `report`, `error`, `model_id`, `settings`, `updated_at`;
  `research_sources` gains `kind`, `ref`, `status`, `error`, `checksum`, `bytes`,
  `relevance`, `credibility`, `claims`, `subquestion`.
- Config: `paths.research`, `research.*` (8 keys) and `tools.fetch_*` (5 keys).
- `docs/RESEARCH.md`, `scripts/acceptance_m28.sh` (30 self-checking assertions).

### Changed
- `net.fetch` is no longer a declared-but-unimplemented capability; it is a working tool
  with its own limits (see `docs/TOOLS.md`).
- `research.report_format` default is now `markdown` (was an unused `html`).

### Notes
- Web research needs an explicit `net.fetch` grant; the first attempt is refused and creates
  nothing. A `once` grant is scoped to the task that asked, so a new run asks again.
- Coverage is measured, not asserted: an empty run is `incomplete` and exits 3 with a report
  whose first line is "I found no evidence".

## [0.27.0] - M27 Simple Mode and unified search

### Added
- `application/search.py`: `SearchService` - one query across eight sources (`conversation`,
  `memory`, `task`, `workflow`, `project`, `artifact`, `file`, `tool`), with one shared
  scoring function (term coverage, phrase bonus, title bonus), per-source caps, kind
  weights for cross-kind ties, project/conversation scoping, and a `SearchReport` that
  carries `counts`, `scanned`, `skipped`, `degraded` and `elapsed_ms`. A source that fails
  degrades the report instead of failing the search.
- File search inside `ws.tool_roots()` only: skip directories, dotfiles, binaries (NUL
  sniff), oversized files (`search.max_file_bytes`) and a hard file budget
  (`search.max_files`), with every skip reported. Search never writes.
- `application/simple.py`: `SimpleMode` with a closed intent set (`chat`, `search`,
  `recall`, `remember`, `status`, `workflow`, `help`, `quit`), `detect_intent()` returning
  `(intent, why)` with the reason shown to the user, and `SimpleResult` carrying
  `headline`, `detail`, `next_step` and structured `data`.
- `TasksManager.search` and `WorkflowsManager.search` so unified search reads the managers
  that already own the data instead of maintaining an index.
- CLI: `search QUERY [--kind ...] [--limit] [--per-source] [--project] [--conversation]
  [--no-files]`; `simple ask TEXT`, `simple status`, `simple help`, and a bare `simple`
  REPL that keeps one conversation and explains every answer.
- Config: `search.default_limit`, `search.per_source`, `search.include_files`,
  `search.max_files`, `search.max_file_bytes`.
- `docs/SIMPLE_MODE.md`, `scripts/acceptance_m27.sh` (23 self-checking assertions).

### Changed
- `WorkflowFailed` is now an `ArchxError`, so a failed workflow is reported as an error
  message with an exit code instead of escaping as a bare `Exception` traceback.
- Simple Mode refuses to escalate: a step without its grant prints
  `archx-agent approvals approve ap_...` and exits `4`, and no grant is created.
- Simple Mode's `status` labels a simulated test double as `SIMULATED - no model is run`.

### Notes
- Search is keyword-only except for memory, which uses its embedding index when one is
  configured; the report says `keyword-only` when it is not (see `GAPS.md`).
- A `once` approval is spent by the run it authorises: the next identical request asks
  again, which is the permission centre's design, not a Simple Mode regression.

## [0.26.0] - M26 resource and job scheduler

### Added
- `managers/jobs.py`: a durable queue (`queued | running | paused | completed | failed |
  cancelled | interrupted`) with priorities, a transactional claim, per-job deadlines,
  attempt budgets, cooperative pause with a cursor, idempotent submission (`dedupe_key`),
  crash recovery (`recover`) and deadline reaping (`reap_expired`).
- `application/scheduler.py`: `JobRunner` with two real kinds - `command` (a child in its
  own session, SIGKILL at the deadline, exit code/stdout/stderr/duration recorded) and
  `workflow` (an M25 workflow, with a step-boundary deadline check) - plus `drain()` with
  `scheduler.max_concurrent_jobs` and CPU/memory admission control.
- Resumable workflows: `AgentRunner.run(resume=, control=)` and `RunPaused`; a paused run
  keeps its workflow `running`, its task open and its finished steps, and resume continues
  from the first step without a succeeded row.
- `TaskManager.interrupt_stale(protect=...)` + `JobManager.protected_task_ids()` so the
  crash sweep never closes a task a paused or resumed job still owns.
- CLI: `jobs submit command|workflow`, `list`, `queue`, `show`, `logs`, `run`, `pause`,
  `resume`, `cancel`, `retry`, `stats`, `recover`, `reap` (exit `0/1/2/3`, where 3 means
  work remains).
- Schema v17: job claim columns (`attempts`, `max_attempts`, `timeout_seconds`, `pid`,
  `worker`, `requeued_at`, `control`, `cursor`, `dedupe_key`) and a queue index.
- Config: `scheduler.max_attempts`, `poll_seconds`, `stale_after_seconds`,
  `recover_on_open`, `reap_on_open`.
- `docs/SCHEDULER.md` and `scripts/acceptance_m26.sh` (23 self-checking assertions,
  including a real SIGKILL and a cross-process pause/resume).

### Notes
- Retries are automatic only for crashes (no recorded result); a failed or timed-out job is
  retried explicitly with `jobs retry`.
- A running `command` job cannot be paused; a workflow pauses at step boundaries.
- `scheduler.memory_limit_mb` is an admission-control budget over declared estimates, not a
  cgroup (see `GAPS.md`).

## [0.25.0] - M25 agent workflows

### Added
- Workflow definitions (`managers/workflows.py`): six step kinds (`model`, `tool`, `memory`,
  `note`, `checkpoint`, `subagent`), strict validation, templating
  (`{{goal}}`, `{{step.N.output}}`, `{{input.NAME}}`), ordered step records, and two built-in
  user-directed templates.
- `AgentRunner` (`application/agent.py`): sequential execution through the existing chat and
  tool paths, budgets (steps, wall clock, tokens, subagents), cancellation re-read between
  steps, an up-front checkpoint gate, and subagents as child tasks with their own
  conversations.
- AI-directed planning: a model proposes JSON, the plan is validated and stored `proposed`;
  it cannot run without `--approve`, and approval grants no capability.
- CLI: `agent plan|list|show|run|run-file|run-template|templates|approve|reject|cancel|rerun|steps|stats`.
- Schema v16: `workflows`, `workflow_steps` (53 tables).
- `docs/AGENTS.md`, acceptance script, and `--reply-file` on the protocol stub so a real
  HTTP planning round trip can be demonstrated.

### Notes
- A failed run is terminal; `agent rerun` starts a new record instead of rewriting history.
- Checkpoints are up-front gates; durable pause/resume is deferred to the scheduler (M26).

## [0.24.0] - M24 task history, content versions and reproduction

### Added
- `TaskManager` (`managers/tasks.py`): durable tasks with sequence-ordered timelines
  (`task_log`), parent/child trees, final terminal states, open questions, filters and
  statistics; artifacts as references with checksum, size, MIME and a content version.
- `VersionManager` (`managers/versions.py`): append-only content history per subject with
  deduplication, explicit labels, unified diffs and restore-as-new-version; binary and
  oversized content recorded as checksum-only (`content_stored=false`).
- `ReproductionManager` (`managers/reproduction.py`): environment capture, fidelity
  (`exact`/`partial`/`impossible`) derived from evidence, replay commands built from the
  real tool arguments, `--record` and `--verify`.
- Every chat turn is a task (created before the model call); a tool run inside a task is
  linked to it and logged on its timeline, denials included. `ChatService.send(task_id=...)`
  attaches a turn to an existing task.
- Interruption: on open, tasks whose owning process is gone are marked `interrupted`
  (manual tasks and tasks owned by another live process are left alone and reported).
- CLI: `tasks list|show|start|queue|complete|fail|cancel|log|question|resolve|artifacts|
  attach|reproduce|stats`; `versions list|record|show|diff|restore|subjects`.
- Schema v15: `task_log`; `version_records.ordinal/size/restored_from/content_stored`;
  `reproduction_records.app_version/recorded_by`; indexes (51 tables).
- Settings: `tasks.enabled`, `tasks.auto_record_chat`, `tasks.interrupt_stale_on_open`,
  `tasks.max_version_bytes`.
- `docs/TASKS.md` and an acceptance script that includes a real SIGKILL.

### Changed
- The package version is now reported as `0.24.0` (pyproject and `__version__` had drifted
  behind the changelog at `0.17.0`).

### Fixed
- `tasks show` crashed on the human-readable path (it read a `timeline` attribute that lives
  on the task's data, not the task object).

## [0.23.0] - M23 MCP client/server and extensions

### Added
- MCP client (`adapters/mcp_client.py`) over **stdio** (spawned process, line-delimited
  JSON-RPC, captured stderr) and **http** (JSON or SSE responses, `Mcp-Session-Id`), with
  per-request deadlines and answers to server→client requests.
- `McpManager`: server records, discovery, trust/enable, tool registration as
  `mcp.<server>.<tool>` with capability `mcp.call`, and restore-on-open.
- Optional MCP server (`interfaces/mcp_server.py`): off by default, read-only whitelist,
  distinct `mcp-server` permission subject, stdio and HTTP transports.
- Extensions (`managers/extensions.py`, `adapters/extension_runtime.py`): manifest
  validation, install/trust/enable/remove, JSON-in/JSON-out subprocess execution with a
  rebuilt environment, timeouts and output caps.
- New capabilities `mcp.call` and `process.exec`.
- `ToolManager` seams: `register_handler`, `declare_spec`, `unregister_spec`,
  `permission_subject`, plus `float`/`json` input kinds.
- Schema v14: MCP server/tool columns, extension trust columns, `extension_tools`.
- CLI: `mcp servers|add|show|enable|disable|trust|untrust|remove|sync|tools|call|serve`,
  `extensions list|install|show|trust|untrust|enable|disable|remove|tools|call`.
- Settings: `mcp.client_timeout_seconds`, `mcp.server_tools`, `extensions.enabled`,
  `extensions.directory`.
- `docs/MCP.md`, a real fixture MCP server, and the M23 acceptance script.

### Fixed
- `mcp add --command` overwrote the top-level `command` argument (the handler lookup failed
  and the CLI printed help); the flag now has its own dest.
- `config set` stored list settings as a string, so `mcp.server_tools` became a list of
  characters; list settings now accept a JSON array or comma-separated values.
- `mcp serve` complained about the whitelist before checking whether the server was
  enabled, hiding the actual reason it refused to start.
- A dynamically registered tool disappeared in the next process; trusted servers and
  extensions are now restored from the database when the workspace opens.
- `mcp call` on a tool the server never advertised said "no tool"; it now says the server
  does not expose it and lists what it does expose.

## [0.22.0] - M22 tool registry and permission centre

### Added
- `ToolManager` + `ToolSpec`: built-in tools declare capability, risk, typed inputs, side
  effects and dry-run support; strict argument validation (unknown arguments are refused);
  fixed execution order; `tool_runs` rows for every attempt, including denials.
- `PermissionManager`: capabilities, grants with six durations and real scope checks,
  single-use consumption, time-boxing, revocation, and an approval queue with TTL and a cap.
- `LocalToolRuntime`: root-confined file IO (`resolve_within`, symlink-safe), binary
  detection, size/output caps, argv-only processes with a minimal environment, timeouts and
  a denylist.
- CLI: `tools list|show|run|runs`, `permissions capabilities|list|grant|revoke|check|prune`,
  `approvals list|show|approve|deny`; exit code 4 for refusals.
- `file_change` trace events with path, bytes and sha256 for real writes and deletes.
- Schema v13: grant usage counting and approval links, `approval_requests`, `tool_runs`
  sequence/dry-run/truncation columns.
- Settings: `tools.roots`, `tools.max_file_bytes`, `tools.shell_enabled`,
  `tools.shell_denylist`, `permissions.approvals_enabled`,
  `permissions.approval_ttl_minutes`, `permissions.max_pending_approvals`,
  `permissions.max_grant_hours`.
- `docs/TOOLS.md`, M22 acceptance script.

### Changed
- `permissions.default_duration` now defaults to `once` (one approval, one operation), so
  no grant can exist without a scope that is meaningful.
- A `persistent` grant without `--confirm` is refused instead of silently shortened.

### Fixed
- A tool run interrupted by an exception left a `running` row forever; errors now close the
  run (status, error, duration) and are re-raised.
- `permissions check` claimed "approvals are disabled" when it simply does not create them.
- Unknown tool arguments were silently ignored; they are now a usage error naming the
  accepted arguments.

## [0.21.0] - M21 capability-safe model router

### Added
- `ModelRouter` with capability states (`verified`/`inferred`/`unverified`/`unsupported`/
  `unavailable`), each carrying its evidence; eligibility rules; deterministic scoring;
  recorded decisions; probes; fallback planning.
- `models route`, `models probe`, `models capabilities`; `RouterDecision` exposed on every
  chat reply as `model.routing`.
- Workspace policy keys `router.require_verified`, `router.allow_unverified_chat`,
  `router.allow_cloud`, `router.prefer_local`, `router.fallback`, `router.max_fallbacks`.
- `Workspace.runtime_availability` (cheap, no-load availability check) and
  `BaseRuntime.available()`.
- Visible fallback: `model.failed` / `model.fallback` trace events, `fallback_from` and
  warnings on the reply.
- Trace kinds `model` and `router`; `docs/ROUTING.md`; M21 acceptance script.

### Fixed
- The router could pick a model whose runtime cannot start (it ranked by score without
  checking availability); eligibility is now a filter applied before ranking.
- Registering a second remote model with the same provider and model reference silently
  overwrote the first model's endpoint; it now raises `ConflictError` naming the existing
  entry, and re-registering the identical endpoint is idempotent.
- `models add-scripted --name other` silently reused the existing test double without
  saying so.
- Error hints told users to probe capabilities that cannot be probed (`ocr`, `vision`).

## [0.20.0] - M20 providers, privacy metadata and consent

### Added
- Provider catalogue (local and cloud) with a known-template list, `api_style`, model
  family, secret references and per-provider prices.
- Privacy metadata split into vendor **claims** (with `claim_source`, `verified = 0`) and
  user **confirmations**, merged into an effective view that reports the source of every
  field.
- Consent workflow: `providers confirm`, `consent` (versioned), `revoke`; consent is
  invalidated by a version bump.
- Availability probes (`providers check`) that distinguish reachable / auth_failed /
  model_missing / rate_limited / unreachable and record latency and model count.
- Daily quotas enforced before the request; usage and cost estimates per provider, per
  model and per day.
- Enforcement in the composition root: remote endpoints require `model.local_only=false`,
  a registered provider, confirmed privacy and recorded consent.
- CLI: `providers catalogue|add|list|show|confirm|consent|revoke|enable|disable|check|quota|usage|privacy|remove|stats`.
- Schema v12: provider privacy/consent columns, `provider_checks`, usage index.
- `scripts/openai_protocol_stub.py` (a real HTTP server, explicitly not a model) and
  `scripts/acceptance_m20.sh`; `scripts/bootstrap.sh` for a reproducible dev environment.

### Fixed
- Locality was inferred from a provider label, so a model labelled `local-http` pointing
  at a remote URL was reported as local; it is now derived from the URL.
- `providers revoke <slug>` reported success while updating nothing (the caller's string
  was used as a row id). Updates now resolve the id first and fail loudly if no row was
  affected.
- `providers check` reported `reachable` for HTTP 5xx responses.

## [0.19.0] - M19 context strategies

### Added
- `ContextManager` with five strategies: `oldest_first`, `summarize`, `ai_select`,
  `manual`, `ai_proposed`.
- Persisted manifests (included/omitted items with reasons, token accounting, memory
  share) and persisted summaries with source ranges and generator identity.
- Persisted proposals: create, list, approve (by building with `--proposal`), reject.
- CLI: `context build|propose|proposals|manifests|summaries|show|reject` (schema v11).
- `ContextOverflowError` carrying token numbers, raised instead of silently truncating the
  current request or dropping pinned content.

### Fixed
- A rejected proposal could still be applied; rejection is now recorded on the proposal
  and blocks application.
- Per-message prompt overhead was not counted, so manifests could under-report tokens and
  the window could overflow; overhead is now part of the budget and the final trim removes
  the oldest droppable message, never the newest.
- Proposal omission entries omitted token counts.

## [0.18.0] - M18 embeddings and retrieval evaluation

### Added
- `helpers/vectors.py` (float32 storage, cosine, `top_k`, dimension-mismatch refusal).
- Embedding providers: `local-hash` (offline, deterministic, explicitly non-semantic),
  `sentence-transformers` (optional), OpenAI-compatible `http` (opt-in, key never stored).
- `EmbeddingManager`: upsert with model identity + source checksum, backfill, purge,
  conversation embedding, batch `memory_scores`, `retrieval_runs` log.
- Hybrid memory search (semantic + lexical + title + pinned), `mode`/`degraded`/
  `degraded_reason` reporting.
- `application/retrieval_eval.py` with precision@k, recall@k, MRR, nDCG@k; three modes;
  markdown + JSON reports.
- `data/retrieval_set.json`: 20 labelled memories, 12 graded queries.
- CLI: `embeddings status|backfill|embed-conversation|search|purge`,
  `eval retrieval --dataset ... --k ... --out ... --json [--no-scratch]`.
- Schema v9: `embeddings`, `retrieval_runs`.

### Fixed
- Keyword search could not match multi-word queries against differently ordered or
  hyphenated text (full-phrase `LIKE`); it now ORs up to 8 token `LIKE ... ESCAPE`
  clauses.
- Hybrid ranking was worse than semantic-only when recency/usage bonuses were blended in;
  blending is now relevance-only (measured nDCG 0.85 vs 0.64 for keyword).
- `memory.embedding_state` was never updated after embedding, which made hybrid search
  report itself degraded for a fully embedded corpus.
- `ARCHX_PATHS_HOME` did not influence which `config.json` was read (a second home could
  silently use another home's configuration); an explicit `--home` also lost to the
  environment. Both are fixed and covered by tests.
- `embeddings purge --json` printed prose instead of JSON.

## [0.17.0] - M17 memory persistence foundation

### Added
- Six memory systems (active, permanent, archival, project, solution, learning) with
  per-kind scope, lifetime, validation and injection rules.
- Memory history (snapshot per edit), sources, retrieval log, artifacts on disk with
  checksums, retention reporting, learner profile.
- Project identity (`ProjectManager`) and project-scoped memory.
- Conversations with sequence ordering, pinning, soft/hard delete, search, export.
- CLI: `memory add|list|show|history|search|edit|delete|retrieve|profile|policy|stats|retention`,
  `projects create|list|show|rename|archive|link`.
- Schema v2 (projects) and v3 (memory, history, sources, retrievals, learning events).

### Fixed
- Duplicate memories are refused with the existing id instead of silently duplicated;
  slot writes supersede instead of duplicating.
- Credential-shaped text is refused in memory rather than stored redacted
  (`secret://` references are accepted - they contain no secret).
- Global flags (`--json`, `--home`, `--allow-simulated`) are accepted after the
  subcommand, as users write them.

## [0.16.0] - M15/M16 model catalogue and provider boundary

### Added
- Model catalogue separating facts, filename claims and user metadata; discovery of local
  GGUF files; states (`usable`/`disabled`/`missing`/`invalid`); verification records;
  usage counters; preference per task.
- Runtime adapters: `LlamaCppRuntime` (in-process GGUF, precise error when the optional
  dependency or file is missing), `HttpChatRuntime` (OpenAI-compatible, classified
  errors), `ScriptedRuntime` (labelled test double, disabled unless explicitly enabled).
- CLI: `models discover|add-http|add-scripted|list|show|enable|disable|verify|prefer|stats`,
  `chat` (one-shot and interactive).
- Schema v10: model catalogue, capability tests, provider usage.

### Fixed
- `401`/`429`/`404`/`402`/`5xx` are no longer collapsed into one provider error; each has
  its own domain error and `retryable` flag, verified against a real local HTTP server.

## [0.14.0] - M13/M14 tracing

### Added
- Event store in its own database: sequence ordering, capture levels
  (`summary`/`detailed`/`diagnostic`), correlation ids, causal `parent_id` tree,
  redaction on write and on export, JSONL export, retention that keeps errors longer.
- CLI: `trace list|show|errors|summary|tree|export|retention`.

## [0.12.0] - M11/M12 storage reliability

### Added
- `WriteCoordinator`: one writer per database, journal + `applied_writes` in the same
  transaction (exactly-once), two-phase durable intents with replay, backpressure
  reported as `PENDING`, graceful drain.
- Backups with manifest + sha256, verify, preview, restore-aside (the replaced database is
  kept, never deleted), retention.
- CLI: `db check|vacuum|backup|backups|verify|preview|restore|retention`.

## [0.10.0] - M10 SQLite conversations

### Added
- Conversations and messages with `(conversation_id, seq)` ordering, restart-safe reads,
  `--resume`, search, export (markdown/JSON), pin, soft/hard delete.

## [0.1.0] - M01-M09 foundation

### Added
- Package layout with enforced import matrix; `Result[T]`; stable domain errors; config
  with defaults → file → env → overrides, validation and provenance; `secret://`
  references; path containment helpers; token counting; redaction; terminal chat.
- `archx-agent` console script with `init`, `info`, `doctor`, `config`.

### Notes
- The repository this work started in contained only a two-line README; all of the above
  was built here. See `docs/VERIFICATION.md`.
