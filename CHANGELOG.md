# Changelog

All notable changes. Format loosely follows Keep a Changelog; versions track the
milestone block rather than semantic-release cadence, because M01-M20 are one development series.

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
