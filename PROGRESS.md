# Progress

Latest completed local gate: **31 October 2026 — worker policy and training admission.**
**2,616 tests**, **25 acceptance procedures**, **91 stress / 11 integration checks**,
**20 GUI tabs + 4 stream scenarios** and **493 installed-wheel imports** pass. This adds
**50 worker safety regressions**; the combined targeted/architecture gate passes 473 tests.
Executable/non-loopback listeners now require credentials; training has atomic running
and retained-state limits. [Audit](docs/AUDIT.md#worker-policy-and-admission) and
[operator guide](docs/REMOTE.md) describe the deliberate compatibility changes and limits.
The fixed structural checklist remains **36/36 (100%)**, not overall product completion.
Original-product gaps and historical CI26/native evidence remain separate in [GAPS.md](GAPS.md).

## Historical milestone verification

The sections below record their own build and CI checkpoints, not a fresh execution of
every command on every edit. Counts belong to the stated run. Transcripts are indexed in
[the verification record](docs/VERIFICATION.md); post-roadmap results are in
[the audit](docs/AUDIT.md).

| Milestone | What was verified | How |
|-----------|-------------------|-----|
| Gemini (M15/M16 boundary, added after M30) | a second, non-OpenAI wire protocol is a first-class runtime: `contents`/`systemInstruction`/`generationConfig` built from an Archx transcript (consecutive same-role turns merged), `candidates[0].content.parts[].text` parsed with `thought` parts skipped, `finishReason` and `usageMetadata` mapped, streaming over `alt=sse`; the key is sent only as `x-goog-api-key`, resolved from a `secret://` reference at request time, registered with the redactor and wiped on close, and a literal key is refused with exit 2; 400/401/403, 404, 429-quota, 429-burst, 5xx, non-JSON, empty-with-SAFETY and `promptFeedback.blockReason` map to distinct errors with their own retry flags; the four-rung consent ladder applies to it because the gate reads `NETWORK_RUNTIMES`; the GUI Models panel registers a model, probes it, and walks the same four rungs with the same rules | `pytest tests/models/test_gemini_m21.py` (56); `scripts/acceptance_gemini.sh` (60 self-checking assertions over a real socket against `scripts/gemini_protocol_stub.py`); `scripts/gui_smoke.mjs` (jsdom) |
| SDK transports (added after M30) | a vendor's own client can drive the app, and there are now **eight** of them: `openai`, `anthropic`, `google-genai`, `mistralai`, `groq`, `together`, `cohere`, `ollama`. Each is registered through `models add-sdk`, resolves its key from a `secret://` reference at request time, and returns the same `ChatResult` as the hand-written clients; no client may retry (`max_retries=0`) and parameters are feature-detected per installed version; 401/403, 404, 429-quota vs 429-burst, 5xx, connection failures and empty replies map to distinct domain errors however the client reports the status; `sdk` sits in `NETWORK_RUNTIMES`, so the four consent rungs apply. The new four were driven against one loopback server that speaks their real routes and the paths they requested were recorded (`POST /openai/v1/chat/completions` Groq, `POST /v1/chat/completions` Together, `POST /v2/chat` Cohere, `POST /api/chat` Ollama). Ollama is the one client whose credential is optional: a loopback daemon is `ready` with no key, a remote one is refused before the socket opens | `pytest tests/models/test_sdk_m22.py` (79); `scripts/acceptance_sdk.sh` (86 checks over a real socket, eight clients, the keyless-local case and its remote refusal, and 11 streaming tests that check every client's own event syntax) |
| M28+e | a research run can be marked done and reopened: `closed_at`/`closed_note` (schema v20) are written only by an explicit close, so a run's own `status`, `coverage` and `evidence_count` are untouched by the judgement; a second close and a reopen-of-an-open run are conflicts naming the first state, not silent no-ops; `research list --closed/--open`, open/closed counts in `research stats`, `POST /api/research/{id}/{close,reopen}`, a *mark complete* prompt with an optional note and *reopen* in the page, and both directions traced | `pytest tests/features/test_research_close.py` (28); `scripts/acceptance_research_close.sh` (35 self-checking assertions over a real socket: the migration, a real local run, close/reopen over HTTP and the CLI, the filters, the trace, and the page wiring) |
| M36 | the milestone with the same hazard M34 had - a `train` command that prints a loss curve it never measured - split along the line between what is true here and what is not: **two trainers really run**, both dependency-free and deterministic, an **n-gram language model** (add-k smoothing, scored by perplexity per split, where an unseen word is scored as `<unk>` rather than skipped, because skipping is how a model reports a number no text could produce) and a **nearest-centroid classifier** over hashed bag-of-words (scored by accuracy, labels from the record or from its parent directory, *with the rule written into the run's config*); **fine-tuning is refused by name** - `lora`/`qlora`/`full` walk a chain (the switch, the base model, the weights directory, the library, the GPU, the adapter) that is computed from the machine, so turning `training.enabled` on removes exactly that reason and the last link - no adapter can fine-tune anything - never goes away; **nothing runs until the dataset can support it** (`train preflight` checks the split, the validation records, the build *and* M35's manifest, so a corpus that drifted after its build cannot produce a number); a run's metrics are **rows** (a comparison is a query, a split with no records is absent rather than a zero, a metric that could not be measured is null), the artifact is written through `fs.write`, hashed into the row and **registered as a version**, and `train predict` re-reads it from disk; `train compare` names a winner only when every run used one method and every one produced the metric; schema v26 **adopts** v8's reserved `training_jobs` with `ALTER TABLE` and adds `training_metrics`; the GUI Train tab is the same service over HTTP | `pytest tests/features/test_training_m36.py` (54); `scripts/acceptance_m36.sh` (57 self-checking assertions over a real socket: a preflight that fails on an unsplit and then an unbuilt dataset, a perplexity recomputed by an **independent implementation** that must agree to 1e-9, a classifier predicting a label the script knows, the fine-tune chain shortening by exactly one reason when the switch flips, a refused run with no artifact that cannot be predicted from, a mixed-method comparison naming no winner, and the page running the same trainer) |
| M37 | remote compute is the easiest feature in this repository to fake - send "train this", receive a number, print the number - so the milestone is built around what a fake cannot answer: **the input is a bundle** (`remote export` writes one JSON document carrying the corpus, each record's *file* digest measured with `fs.probe` and a separate *text* digest of what `fs.read` returns, the M35 manifest checksum and the declared run, then hashes the whole thing), **the endpoint is named on the record** before anything is sent, **the artifact is hashed twice** (`claimed_sha256` from the worker, `received_sha256` measured here, in separate columns because the point is that they can disagree) and **a job that never arrives is a row** (`remote_attempts`); nothing leaves without the switch, an endpoint *and* `remote.require_approval` (on by default, so the setting is not a lie), and each refusal is stored with every reason; the worker (`archx-agent remote worker`) has no database and no tools - it re-checks the protocol, the body hash, every text digest, the rebuilt manifest and that a `train` split exists, refusing over the wire rather than with a traceback - and then calls **the same `train_records()`** the local command calls, so a remote run's perplexities are *equal* to a local run's, not close; a misreported hash produces `received`, never `verified`, and `remote verify` cannot rescue it by asking twice; schema v27 **adopts** v8's reserved `remote_jobs` with `ALTER TABLE` and adds `remote_attempts`; the GUI Remote tab (17th) is the same service over HTTP, offering only the actions the row allows | `pytest tests/features/test_remote_m37.py` (45); `scripts/acceptance_m37.sh` (71 self-checking assertions over real sockets: a bundle whose hash is the hash of its bytes, an unbuilt and then a drifted corpus refused, three refusals before anything is sent, a real worker computing a result whose perplexity equals a local run's, a lying worker stored as a disagreement, an `archx-remote/0` worker refused by both names, a dead port recorded as a failed attempt, and the page driving the same lifecycle) |
| M38 | the milestone that decides whether "sandboxed" is a feature or a word: every backend is known by name (`local`, `remote`, `docker`, `wsl`, `windows-sandbox`, `vmware`, `virtualbox`), the **wrapper is built by one pure function**, recorded on the run row and printed by `exec show` - so a target called `docker` cannot quietly run the command here; `exec targets` reports what this machine can really do, and each unusable backend is a **row with its reason** rather than an omission (WSL says *not a boundary* in the probe table itself, because `/mnt/c` is your disk; Windows Sandbox records `detached`, because it cannot report an exit code); `exec run` distinguishes **the command failed** (exit 1) from **the command never started** (exit 3, with every reason stored and a refused row that costs nothing); another machine is M37's worker with two opt-ins - `/exec` answers 403 without `--allow-exec` and 401 without the bearer token, and commands run inside `--workdir` - and `exec push`/`exec pull` keep a **hash ledger** per path (`sha256_local`, `sha256_remote`), so a file edited on both sides is a **conflict** with the local copy untouched, exit 3, and `--force` as an explicit act; `train run --target local|remote` writes one row either way (`training_jobs.target`, `remote_job_id`) and a remote run's perplexity is *equal* to a local run's because the worker calls the same trainer, while a sandbox is refused as a training target by name; schema v28 adds `execution_targets`, `execution_runs`, `execution_files` and two columns on `training_jobs`; `execution.enabled` is off by default, because a command in a sandbox is still a command; the GUI Exec tab (18th) is the same service over HTTP, offering only the actions a row allows | `pytest tests/features/test_execution_m38.py` (49); `scripts/acceptance_m38.sh` (65 self-checking assertions: a stand-in `docker` on `PATH` whose recorded argv must contain `--rm`, `--network none`, the absolute mount and the image; the same invocation replayed from another directory; a worker refusing without `--allow-exec` and refusing a wrong token; a timeout that is a row; push, edit there, pull; an edit on *both* sides that must not overwrite; the remote/local training metrics compared for equality; and `exec stats` counting what the ledger holds) |
| M35 | a corpus prepared so that every decision survives the run: **every candidate is a row**, so a file a rule removed keeps `status = 'dropped'`, the rule and the reason (`dataset explain dr_…` prints one sentence built from the record), and `dataset records --status dropped` is the audit; a directory is walked one `fs.list` per level (a depth bound and a refusal on a truncated listing, because a silently truncated scan is a dataset with holes), each file measured by `fs.probe` and read by `fs.read`, and **a text suffix that hides binary bytes is binary in fact** - the refusal becomes the reason; **the split is a function of the record, not of its position** (`bucket = hash(seed + ':' + sha256)`), so byte-identical files cannot cross splits by construction and adding a file tomorrow does not move today's `train` rows; the leak the hash *cannot* see - one document resaved with different whitespace or case - is found by a normalised hash recorded at scan time, refused with the crossing pair named, and closed by `clean --normalize`; **the manifest is a claim that can fail**: `build` writes the JSONL export through `fs.write`, records a sha256 over the manifest's sorted lines, and `verify` re-reads the files, prints stored vs recomputed and names the record that changed or vanished (CLI exit 3: nothing broke, the corpus moved - a dataset never built cannot claim agreement); `--require-license` **refuses** rather than inventing a license, and an unstated one is written as `unknown`; schema v25 **adopts** v8's reserved `datasets`/`dataset_transforms` with `ALTER TABLE` and adds `dataset_records`, one row per candidate; lifecycle `draft → scanned → cleaned → split → built`; the GUI Data tab is the same service over HTTP | `pytest tests/features/test_datasets_m35.py` (60); `scripts/acceptance_m35.sh` (72 self-checking assertions over a real socket: a scan refused without `fs.read`, a resaved document refused across splits and accepted after `--normalize`, a new file that leaves the earlier assignments untouched, a manifest broken by an edit and then by a delete, a license that is refused rather than guessed, and the page driving the same pipeline) |
| M34 | a mode about media that begins by refusing to guess: **a media fact is a fact only if it was read from the file**, so `application/media.py` parses PNG (`IHDR`), JPEG (the segment chain to the start-of-frame), GIF and WAV (`fmt `/`data`, with the duration arithmetic) by hand - no PIL, no ffmpeg, no `file` binary - and refuses anything else with the bytes it began with; the file name is kept as a *claim* beside the measurement, so a PNG named `.jpg` is stored as a PNG with `name_mismatch` set and counted in `voice stats`; a file that disagrees with itself keeps both numbers (a WAV claiming 100 000 data bytes in 40 is recorded as 40 **with a note**); the same bytes are one asset (the hash decides, `--force` stores a second row); **retaining the bytes is a decision**, so `--retain` refuses before copying until `voice.retain_audio` is on, and then stores the copy under the file's own hash; asking it to hear or speak walks a chain - the switch, the model setting, the registry, the model's claim, the runtime's readiness, the adapter - and reports **every** missing link in order, computed from the workspace rather than printed from a constant, then writes the attempt to `voice_attempts` (exit 3: nothing broke, it cannot); **the only transcript it can store is one a person typed**, and that is `CHECK (source IN ('human'))` in the schema rather than a rule the service happens to keep; `fs.probe` is a new tool (capability `fs.read`) that reads a head as bytes and hashes the file, while `fs.read` still refuses to decode a binary as text; the GUI Voice tab is the same service over HTTP | `pytest tests/features/test_voice_m34.py` (67); `scripts/acceptance_m34.sh` (88 self-checking assertions over a real socket: containers generated byte by byte, the grant refusal recorded as an attempt, a png wearing a `.jpg` name stored as png with the mismatch a column, a WAV that lies about its length, a `whisper` transcript refused by the database itself, the chain shortening by exactly one reason when the switch flips, retention refused before anything is copied, and the page measuring the same bytes) |
| M33 | three small games and one simulation, chosen because they can be checked: the rules are the **only** authority on legality (`application/games.py` is pure - no workspace, no database, no model), so a mover proposes a string and `apply` answers with a position or a reason; the built-in engine picks from `legal_moves(state)`, which is why it cannot cheat by construction rather than by review, and perfect-play tic-tac-toe draws against itself; **a refused move is evidence** - it is written to `game_moves` with `legal = 0` and the rules' own reason, the board does not move and `move_count` does not advance, and the refusal is numbered from the move count rather than spending a sequence number; over HTTP a refusal is `200` with `legal: false` (a well-formed request, answered) while the CLI exits 2 so a script can branch; connect four is two plies deep and the docs say so instead of implying strength; Conway's life runs under a fixed named rule (`B3/S23`) with the population series, the final grid and a sha256 of that grid recorded, and `play replay` recomputes from the parameters alone - a doctored hash fails its own replay with both hashes printed (exit 1); parameters are validated rather than clipped, and wrapping is refused by name because this build has no torus rule; schema v23 **adopts** the `games`/`game_moves` tables reserved by v8 with `ALTER TABLE` (a reserved table is not a free table, so it is extended, never redefined under whoever has rows in it) and adds `play_sims`; the GUI Play tab is the same service over HTTP | `pytest tests/features/test_play_m33.py` (77); `scripts/acceptance_m33.sh` (69 self-checking assertions over a real socket: the migration adopting the old tables, a refused move kept with its reason and the count unmoved, a finished game refusing everything after, sixty engine games checked against the rules with no illegal move, nim's zero-XOR claim, a doctored hash failing its own replay and reproducing once restored, absurd parameters refused, the page starting a game the CLI then reads, and the record surviving a restart) |
| M32 | an experiment is a *declaration* - a command, its parameters and where the numbers come from - and the rule that shapes the mode is that **a metric is a metric only if the experiment said where it comes from**: the source is `none`, the last non-empty line of stdout as JSON, or a JSON file the run writes inside its own directory, and the runner reads only that, through `fs.read` like everything else; a source that is missing, malformed or non-numeric leaves the run with a `metrics_error` sentence and **no** metric rows, and `compare` names those runs by id with the reason instead of dropping them; a substituted parameter must be one shell-safe token and an undeclared placeholder - or a declared parameter the command never uses - is refused by name before anything runs, with no quoting behind the user's back; every run goes through `shell.run` under the permission centre (no grant is exit 4 with the approval id and a `refused` row), becomes a `experiment` task marked *manual* with its output kept as an `experiment-log` artifact, and stores its parameters, resolved command, exit code, duration and numbers as rows; `failed` and `timeout` are their own statuses, never absences; metrics are rows in `experiment_metrics`, so the ranking is a query; `compare` names the metric, the direction, the best run and every caveat (unranked runs, differing parameter shapes, failed runs); close/reopen keep the history, delete needs `--yes` and takes the runs with it; the GUI Experiment tab is the same service over HTTP | `pytest tests/features/test_experiments_m32.py` (66); `scripts/acceptance_m32.sh` (53 self-checking assertions over a real socket: the refusal before the grant, the refusal recorded as a row, real metrics from stdout and from a file, broken JSON and a missing file both named, an unsafe parameter refused before anything runs, the comparison and its notes, and the page answering the same questions) |
| M31 | a coding session is a directory, a task and a record: opening one binds a directory inside the tool roots and gives it a `coding` task marked *manual* (the user works across many commands, so the process exiting is not the work ending); **a session is not a way around the permission centre** - reading is `fs.read`, saving is `fs.write`, deleting is `fs.delete`, running is `shell.run`, so with no grant the file is untouched, the refusal names the approval (CLI exit 4, HTTP 403 `approval_required`), and one edit does not become two approval requests when the read is not allowed; every edit is a row with a unified diff, both checksums and an artifact on the task, and `code diff` is the session's whole patch as one more artifact; **the runner records every command** - the string as typed, the argv that actually ran, the directory, the exit code, the duration, the output as an artifact, and refusals as rows too; a failing command exits 1 and asks a question on the task, a timeout is `timeout` and not `failed`; a named check comes from the project's own strict `archx.checks.json` (unknown fields, duplicate names and a missing command are refused); a recorded run can be replayed (`code rerun`, with `replayed_from`); the session's task is an ordinary task, so `tasks reproduce` prints the commands and `code show` stays readable after the session is closed; the GUI panel is the same service over HTTP | `pytest tests/features/test_coding_m31.py` (66); `scripts/acceptance_m31.sh` (48 self-checking assertions over a real socket: the refusal before the grant, the write landing after the approval, the ledger, a real pytest run that fails then passes, the patch, the replay, and a write in the page that the CLI then reads) |
| M30 | a learning goal carries criteria and is a record; its items carry a question, an optional answer key, an ordered hint ladder and their own SM-2-lite schedule; an answer is graded **exact** (normalised comparison against the expected answer) or **self** (1-5) and the row says which - there is no model grading; `learning.try_first` refuses a hint before the first attempt (CLI exit 3, GUI 409 `try_first`) and the ladder is revealed one level at a time; every answer returns interval, ease, streak, status, due date and the sentence explaining them; `next` says why it chose that item and refuses with exit 3 when nothing is due; a session is a real `learning` task with a summary; a plan without a model declares `planned_by = rules`, uses only the learner's own words and never invents an answer key; completion is explicit (`goal complete`), never inferred from a mastered deck; the GUI adds items, reveals hints and answers through the same service, and both directions are checked | `pytest tests/features/test_learning_m30.py` (121); `scripts/acceptance_m30.sh` (90 self-checking assertions incl. a refused hint, a lapse, a self-graded item, an item added in the GUI visible to the CLI, and a delete that takes the children) |
| M29 | a local GUI serves the same app over a socket: every panel (status, chat, research, search, tasks, jobs, approvals/grants, memory, models) calls the real managers, so a chat turn made in the browser is a `chat` task the CLI can show, a memory is a real memory and a research run is a real run with the same `[S<n>]` labels; the page is public but every API call needs the per-process token (header, bearer, query, or an HttpOnly SameSite cookie exchanged at `POST /api/session`); a cookie-authenticated write without `X-Archx-Request: gui` is 403, `OPTIONS` is 405 and no CORS header is ever sent; assets are served by exact name so no path escapes; web research without `net.fetch` is a 403 naming the approval, approving it in the GUI mints exactly that grant, the same request then reads a real page, and revoking removes it; a non-loopback bind without `--allow-remote` exits 2 | `pytest tests/interfaces/test_gui_m29.py` (85); `scripts/acceptance_m29.sh` (60 self-checking assertions over a real socket, including the approval, a real web-research run, a spent one-shot grant and a queued job run from the page) |
| M28 | a research run stores a plan that names its author (`model`/`rules`/`user`), reads real local documents and (opt-in) real HTTP pages through the `net.fetch` capability, records every source including the ones that failed, hashes what it read, drops model quotes that are not in the excerpt, demotes uncited model prose instead of presenting it as a finding, computes coverage, writes a report with `[S<n>]` citations, attaches it to a research task as an artifact, and reports "I found no evidence" with exit 3 when there is none; `research verify` re-checks every citation independently | `pytest tests/features/test_research_m28.py` (97); `scripts/acceptance_m28.sh` (30 self-checking assertions incl. a real local HTTP site, an approval refusal, a spent grant, a 404, a binary page and a queued job) |
| M27 | unified search finds a query in conversations, memory, tasks, workflows, projects, artifacts, tools and files with one shared scoring rule, per-source caps and honest `degraded`/`skipped` notes; a source that fails degrades the report instead of failing the search; file search stays inside the tool roots, skips binaries/oversize/noise directories and never writes; Simple Mode classifies eight intents and prints the reason it chose one, stores `remember` as a real permanent memory with the duplicate check intact, reads `status` from the live app, and refuses a missing model, a missing grant or a checkpoint by printing the exact next command and exiting 4 without creating a grant | `pytest tests/knowledge/test_search_m27.py` (42) + `pytest tests/knowledge/test_simple_m27.py` (67); `scripts/acceptance_m27.sh` (23 self-checking assertions incl. approve-then-run and a spent one-shot grant) |
| M26 | a submitted job is a durable `queued` row with a deadline and an attempt budget; claiming is one transaction (six threads over 24 jobs claim each exactly once); priority and `queue_seq` decide order; `dedupe_key` makes submission idempotent; a `command` job runs a real child in its own session and records exit code, stdout, stderr and duration; a non-zero exit fails the job and its task; a `workflow` job runs an M25 workflow and still cannot bypass the permission centre; a hard deadline kills the child (`sleep 30`, timeout 1, ~1s, no process left) and fails the job; a `SIGKILL`ed worker's job is requeued while attempts remain and `interrupted` when they do not; pause stops a running workflow at a step boundary with a durable cursor, and resume continues from it without replaying a step or duplicating the task; concurrency and the CPU/memory budget limit what runs at once (measured by wall clock); `jobs run` exits 3 rather than claiming success when work remains | `pytest tests/workflows/test_scheduler_m26.py` (94); `scripts/acceptance_m26.sh` (23 self-checking assertions incl. a real SIGKILL and a cross-process pause/resume) |
| M24 | every chat turn and tool task is a durable record with a sequence-ordered timeline; terminal states are final; a task whose owner process died is marked `interrupted` on the next open (manual tasks and tasks owned by other live processes are left alone); artifacts are references with checksums; content versions are append-only with deduplication, diffs and restore-as-new-version; reproduction derives `exact`/`partial`/`impossible` from the live environment, prints the commands that would replay the task, and `--verify` detects a removed model (exit 3) or changed settings | `pytest tests/workflows/test_tasks_m24.py` (75); `scripts/acceptance_m24.sh` (real SIGKILL, re-runs a printed command) |
| M25 | workflow definitions are strict data (unknown kinds/fields/tools/variables are refused); model steps reuse the chat path and tool steps the permission centre; a model-proposed plan is stored `proposed` and cannot run without `--approve`; approving a plan grants no capability; checkpoints refuse before anything runs; subagents are child tasks with their own conversations; budgets (steps, wall clock, tokens, subagents) stop the run and name themselves; a cancel from another part of the process stops the next step | `pytest tests/workflows/test_agent_m25.py` (60); `scripts/acceptance_m25.sh` (real HTTP planning round trip) |
| M01-M09 | package installs, `archx-agent --version`, helper invariants (paths, Result, errors, tokens, redaction, config) | `pytest tests/foundation/test_foundation.py tests/foundation/test_config.py`, CLI smoke |
| M10 | conversation create/append ordering by sequence, context clear preserves history, restart-safe reading | `pytest tests/knowledge/test_memory_m17.py::TestConversationBasics` |
| M11 | committed-only success, exactly-once by op id, durable two-phase + replay, backpressure=PENDING, graceful drain, multi-thread safety, **SIGKILL mid-write recovery**, multi-process writes | `pytest tests/foundation/test_storage.py` |
| M12 | backup/verify/preview/restore-aside, tamper detection, retention | `pytest tests/foundation/test_storage.py::TestBackupRecovery`, `archx-agent db ...` |
| M13 | sequence ordering, capture levels, redaction on write and export, causal tree, retention keeps errors longer | `pytest tests/foundation/test_storage.py::TestEvents` |
| M14 | trace filters, errors, summary, JSONL export, retention, tree | `archx-agent trace ...` + CLI tests |
| M15 | discovery of GGUF files, facts/claims split, states, preference per task, verification recording | `archx-agent models ...` (see model tests) |
| M16 | OpenAI-compatible HTTP runtime against a real local server: success, 401/402/404/429-rate/429-quota/500, connection refused, malformed body, key never leaked | `pytest tests/foundation/test_application.py::TestHttpRuntimeContract` |
| M17 | all six memory kinds stored/retrieved/edited/deleted through the CLI with scope + provenance, duplicate rejection, slot supersession, artifact checksum, restart survival, crash replay, every write traced | `pytest tests/knowledge/test_memory_m17.py` + CLI acceptance |
| M18 | float32 vectors with model identity, embedding states, cache checksums, degraded keyword fallback, hybrid ranking, model-change staleness, cross-model refusal, full evaluation report | `pytest tests/knowledge/test_embeddings_m18.py`; `archx-agent eval retrieval` |
| M19 | five strategies build manifests with reasons; oldest-first preserves history; manual selection; summarise keeps originals + source range; ai_proposed requires approval | `pytest tests/knowledge/test_context_m19.py`; `archx-agent context ...` |
| M20 | provider catalogue keeps facts/claims/user confirmations apart; loopback = local (derived); remote is blocked until privacy confirmed + consent recorded + `model.local_only=false`; availability probe distinguishes reachable/auth/404/429/500/refused; quotas enforced; usage and cost attributed per request | `pytest tests/models/test_providers_m20.py` (30); `scripts/acceptance_m20.sh` (real HTTP server) |
| M23 | MCP client over real stdio and HTTP transports with deadlines; discovery recorded but registration requires trust+enable; every remote call needs an `mcp.call` grant; the optional MCP server is off by default, exposes a whitelist and uses the distinct `mcp-server` subject; extensions are installed/trusted/enabled separately, their manifests cannot invent capabilities or escape their directory, and their programs run with a rebuilt environment; dynamic tools are restored from the database on open | `pytest tests/tools/test_mcp_m23.py` (43) + `tests/tools/test_extensions_m23.py` (35) + `tests/interfaces/test_cli.py::TestCliMcp/TestCliExtensions` (9); `scripts/acceptance_m23.sh` |
| M22 | tools declare capability/risk/dry-run; ungranted operations are refused with an approval id; approval mints exactly the requested grant; scoped grants (once/task/conversation/project/persistent) are checked, single-use grants consumed before the work; sandbox refuses traversal, absolute escapes and symlink escapes; argv-only processes with a denylist, minimal env and timeouts; every attempt (including denials) has a `tool_runs` row and trace events | `pytest tests/tools/test_tools_m22.py` (78) + `tests/interfaces/test_cli.py::TestCliTools` (13); `scripts/acceptance_m22.sh` (real files and processes) |
| M21 | capability states with evidence (verified/inferred/unverified/unsupported/unavailable); eligibility before score; a model whose runtime is missing is refused; probes record measurements; `require_verified` policy; remote never auto-chosen; fallback is traceable and never silent | `pytest tests/models/test_router_m21.py` (33); `scripts/acceptance_m21.sh` |

**Test suite: 1282 tests, 0 failures, 0 skipped** on Python 3.11.2 (see note in GAPS
about 3.13 and about llama.cpp).

| CI on GitHub (added after the SDK work) | the workflow actually runs, and its output is readable from the repository without an Actions token: editing `.ci/trigger` starts it, each step writes `$LOGDIR/NN-<name>.log` plus a `status.tsv` row, a background publisher pushes the folder to the `ci-logs` branch every 45 s, and `scripts/ci_logs.sh` reads it back over git. A real SmolLM2-135M Q4_K_M is served on a CPU runner and answers (`docs/ci/model-proof.json`); four vendor clients complete a turn and stream against it; a real Ollama daemon is pulled and driven by its own client and by Archx (keyless local, `state now verified`); a Cloudflare quick tunnel is opened and the OpenAI SDK answers through the public URL. Five defects were found only by running it, and fixed | `gh api .../actions/runs` → runs #3 and #4 `success`; `./scripts/ci_logs.sh --run 20261028T115458Z-5e67bd9` (10/10 steps ok); the transcript in `docs/ci/README.md` |

| Chat streaming into the page | the reply is painted while it is written: `POST /api/chat/stream` writes server-sent events for the same turn the ordinary route records, with no `Content-Length` (a length would buffer every frame), an `error` frame when the turn is refused, and the page reading the body with `fetch`/`getReader` then replacing the streamed text with the recorded one | `pytest tests/interfaces/test_gui_stream.py` (8, over a real socket); `scripts/acceptance_m29.sh` (60 checks, 5 of them the stream) |
| Tool calling, measured | `models probe --capability tools` could never pass before this, because nothing offered the model a tool. The runtime now sends `tools` + `tool_choice`, parses the call, and distinguishes "called record_value with {\"value\": 1}" from a prose reply; a runtime with no tool path fails saying so | `pytest tests/tools/test_tool_probe.py` (4, including the CLI probe and the negative cases) |

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
  `tests/interfaces/test_gui_m29.py` now also fails if a class in the page has no rule behind it.
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
* M38: `docs/VERIFICATION.md#m38-acceptance-transcript` - the probe table on this machine (docker
  refused with its reason until a stand-in appears), a command refused by name while execution is
  off, a local command that exits 7 recorded as *failed* and a command that never started recorded as
  *refused*, the docker argv read back from a stand-in binary, a worker refusing without
  `--allow-exec` and refusing a wrong token, a timeout, a project pushed, edited there and pulled,
  a file edited on both sides kept as a conflict until `--force`, and remote/local training metrics
  that must be equal.
* M37: `docs/VERIFICATION.md#m37-acceptance-transcript` - a bundle hashed against its own bytes, a
  real worker on a real port computing a result whose numbers equal a local run's exactly, a worker
  that misreports its hash producing a disagreement instead of a result, and a dead port recorded as
  an attempt rather than a crash.
* M36: `docs/VERIFICATION.md#m36-acceptance-transcript` - two trainers measured on a corpus the
  script wrote, an n-gram perplexity recomputed by an independent implementation, a classifier
  predicting a known label, a fine-tune refused with six computed reasons, and a refused run with
  no artifact to predict from.
* M35: `docs/VERIFICATION.md#m35-acceptance-transcript` - a corpus written by the script is
  scanned through the tool layer, cleaned with every removal keeping its reason, split by content
  hash (a resaved document is refused across splits until `--normalize` closes it), built into an
  export whose manifest is then broken by an edit and by a delete, and verified by a page reading
  the same rows.
* M34: `docs/VERIFICATION.md#m34-acceptance-transcript` - files generated byte by byte are measured
  from their headers, a png wearing a `.jpg` name is stored as png with the disagreement as a
  column, an unmeasurable file is refused with its head bytes, asking for words or speech is
  refused with every missing link named and recorded, a transcript a person typed is the only kind
  the schema accepts, and the page measures the same bytes.
* M33: `docs/VERIFICATION.md#m33-acceptance-transcript` - a game is started and played, a refused
  move exits 2 and is kept in the log with its reason while the board and the move count do not
  change, a finished game refuses everything after it, sixty games of engine play are checked
  against the rules with no illegal move, nim leaves a zero XOR, a simulation reproduces from its
  parameters and a doctored hash fails its own replay, and a game started in the page is the row
  the CLI lists.
* M32: `docs/VERIFICATION.md#m32-acceptance-transcript` - an experiment is declared, refused a
  run without a grant (exit 4) and then really run; the numbers appear as rows only when the
  declared source produced them, and broken JSON and a missing metrics file are both named rather
  than zeroed; an unsafe parameter is refused before anything starts; `compare` names the best
  run and every run it could not rank; and the page lists the same experiments the CLI declared.
* M31: `docs/VERIFICATION.md#m31-acceptance-transcript` - a write is refused before the grant
  (exit 4, the file's sha1 unchanged, no change row) and lands after the approval; the runner's
  ledger carries the argv, the exit code and a `refused` row for the command that was not run; a
  real pytest check fails and then passes, recorded under its own name; the session patch is an
  artifact and `tasks reproduce` reads the task; and a write in the page is a file the CLI reads.
* M20: `docs/VERIFICATION.md#m20-acceptance` - a real OpenAI-compatible HTTP server is
  registered as a local provider, probed, chatted through, and charged for; a cloud
  provider is refused until confirmed + consented; a remote model is refused while
  `local_only` is true.

## Where the remaining work is listed

`docs/reports/STATUS.md` is the itemised list of everything still open (a live vendor call, M35
onward), with the reason each one is open and what would close it.

## Roadmap closure

M39 is verified with a real official bpy 4.2/Cycles CPU render in CI (64×64, 4897 PNG bytes,
SHA-256 `c157d34edbb959f8194117dc220b515b6bd5f750154ea5cb39337c34cd509570`).
Task artifacts and synchronous rendering are implemented; no background render recovery is claimed.
M40 provides interval, one-shot and hash-watch scheduling, atomic queue dispatch and an explicit
permissioned polling worker. Its CLI acceptance passes 34 checks; M39 acceptance passes 59.
M41 adds release packaging and hardening regressions. Latest local suite: **1951 passed in
486.57 s**; GUI smoke: **20 tabs**; clean-wheel install passes without runtime dependencies.

**Final combined CI #26 is green**, head `48dd607`, run `40914694127`: 1951 tests in 536.36 s,
91 stress/edge checks, 11 integrations, ten acceptances, real Blender render and clean-wheel check.
Evidence: `docs/ci/`, run `20261029T164537Z-48dd607`. All 24 logged steps passed.

M41 is closed within source/wheel readiness scope. Future feature extensions are limitations in
GAPS.md, not remaining M01–M41 roadmap milestones. No installer or published release is implied.
See `docs/RELEASE.md` for the supported/verified scope.

## Known breakage

No failing behaviour was recorded at the final milestone gate. The later repository
audit found and fixed additional defects; see [the audit report](docs/AUDIT.md) for
current checks and remaining product/maintenance gaps. The real-model CI evidence
supersedes earlier local-environment claims that model weights were unreachable.

## Post-roadmap repository audit

The audit refactors the CLI and GUI by responsibility, removes confirmed dead code,
fixes busy-commit retries and the global automation switch, and separates historical
evidence from current product limits. See [Audit and requirements comparison](docs/AUDIT.md)
and [Document guide](docs/DOCUMENT_GUIDE.md). Counts above belong to their recorded runs.

Final local audit gate: **1,965 tests passed** (2 optional-client deprecation warnings),
all **25 acceptance procedures exited 0**, GUI smoke covers **20 tabs**, and the clean-wheel
check includes every split script. These are local audit results; CI #26 above belongs to
`48dd607`, not this later refactor. Full details and remaining gaps are in the audit report.

## Second audit pass — feature packages and test ownership

Seventeen additional concentrated modules now have responsibility-focused packages;
released migrations retain their SQL/order; automation persistence is in the manager layer.
The 44 root regression modules are organized into nine suites. Source and clean-wheel
import checks enumerate all 364 Python files rather than relying on namespace discovery.

Final local gate: **1,985 tests passed**, 2 optional-client warnings, **25 acceptance
procedures exited 0**, the **20-tab GUI smoke** and dependency-free wheel checks passed.
Measured coverage is **77.3% statements / 56.9% branches**, not exhaustive verification;
CLI subprocess execution is separately evidenced by acceptance procedures. See
[the audit](docs/AUDIT.md), [simple codebase map](docs/CODEBASE_GUIDE.md) and
[technical review guide](docs/TECHNICAL_REVIEW.md). No fresh GitHub CI or real Blender
run was performed for this refactor.

## Earlier runtime/domain checkpoint — 2026-10-30

Four more original modules are split by responsibility: models, conversations, HTTP
runtime and local tools (21 total in the extraction inventory). Public imports and the
local-tool dataclass are preserved. HTTP error/payload handling, native reload/release
and bounded-memory process output now have 60 additional regressions.

Current local gate: **2,049 tests passed**, 2 optional-client warnings, **25 acceptance
procedures exit 0**, **34 targeted architecture checks**, **20 GUI tabs**, and **399
clean-wheel imports**. Coverage is **77.7% statements / 57.4% branches**. Inventories read
616 files, assign 60 folder roles and catalogue the same 82 Markdown documents.
No fresh CI, real Blender, native GGUF inference or Windows certification was run.

At this earlier checkpoint, two defects were reproduced: conversation settings retained
only the most recently written key, and catalogue registration could treat a directory
as usable. Both are fixed by the documentation-first maintenance below. See the [current audit](docs/AUDIT.md#runtime-and-domain-continuation)
for required follow-ups and platform/resource limits. This is not whole-product closure.

## Documentation-first maintenance — completed and locally verified

The documentation review runs before behaviour changes. It reads the complete Markdown
inventory, preserves labelled historical reports/transcripts, checks local links and
explicit code paths, and corrects stale current-status summaries, package paths and
safety claims. THINKING.md and PLAN.md now track post-roadmap maintenance explicitly.
Next: additive conversation-settings migration, model-file state validation, native
runtime failure cleanup, regression/acceptance/wheel checks, then refreshed evidence.
Previous gate counts are historical until this follow-up finishes.

Documentation gate: all **82 Markdown documents** read/classified, zero local link or
current explicit source-path findings. Current guides were corrected for package paths,
the missing schema v20–v30 map, stale top-level status, environment-vs-file secret
exposure, local-command disk/process limits, Docker requirements and workflow scope.
Historical reports/CI/transcripts retain their original evidence. This gate is mechanical
inventory plus targeted semantic review, not a claim that every sentence is proven.

Implementation and targeted checks: **341 passed**, 2 optional-client warnings, covering
the model/provider/router suites, conversation settings, workspace application and
architecture. Settings upgrade/rollback/backup/restart and real workspace replay are
included. Native cleanup errors and model replacement/disabled intent are tested. The
full coverage/acceptance gate was still running at that checkpoint; isolated wheel
import count was **401**.
Additional documentation corrections distinguish training bundles from opt-in remote
commands, make optional worker tokens explicit, and remove false claims that an
extension's rebuilt environment blocks access to the user's database.

Final-tree targeted suite: **117 passed**, including the 38 architecture/document guards.
A final review added two checks that unchanged file refresh/re-discovery preserves an
unrelated inference failure rather than erasing it. The broad run was restarted on that
final tree; interrupted earlier output is not counted as a successful final gate.
Independent stress/hostile-client checks: **91 passed**; cross-CLI/GUI/SQLite integration:
**11 passed**. Wheel verification imports all **401** modules without dependencies.
The document catalogue names/links every one of the 82 Markdown documents; historical
CI JSON/TSV and package TOML also parse consistently.

### Final documentation-first gate

**2,095 passed**, 2 optional-client deprecation warnings, **507.56 seconds**. All **25
acceptance procedures exit 0**; 7 early scripts retain their transcript-style caveat.
Independent checks: **91 stress / 11 integration**, **38 architecture/document guards**,
**20 GUI tabs**, **401 dependency-free wheel imports**. Coverage is **77.9% statements /
57.7% branches** across **401 source files**. Inventories read **623 files**, assign
**60 folder roles** and name/review all **82 Markdown documents**.

This batch adds **46 regression tests**. Migration v31 retains surviving legacy settings;
old overwritten values cannot be recovered. The original settings and directory bugs,
startup replay ordering, native stat/close errors and erased inference diagnostics are
fixed. Selected Ruff/whitespace checks are clean; 4 intentional callback arguments are
retained after dead-code review. No fresh GitHub CI, real Blender, native GGUF inference,
vendor-cloud or Windows certification was run. Extension capture/process containment,
optional worker auth and broader product scope limits remain explicit in GAPS.md.

## Extension and worker safety batch — completed and locally verified

Repeated the 82-document review before code changes: zero link/current source-reference
issues. Recreated the disposable verification environment (it is not persisted); the
optional SDK baseline passes 79 tests with the same two deprecation warnings. Current
work addressed extension output capture, worker HTTP/file refusals and the training
artifact identity race. Final results below are fresh, not borrowed from the previous gate.

Targeted safety gate: **284 passed**, including **93 new regressions** and the extended
worker method-ownership guard. Shared process mechanics and split worker responsibilities
are implemented. Forced delayed-training tests verify accepted identity and request-copy
isolation; real sockets/processes/files test framing, auth, timeout descendants, byte
budgets, malformed JSON and symlink refusals. Final broad outcomes are recorded below; the
isolated wheel imports **408 modules** and the **20-tab GUI smoke** passes.

The first M26 acceptance attempt failed a real test-harness timing race: the workflow's
one-second step completed before the polling/pause CLI could act. Verification now uses
bounded test-only release barriers for pause/crash steps, including explicit readiness
checks and early terminal-state escape. Scheduler semantics are unchanged. Fresh M26
runs pass 25 checks twice; its failed first attempt is not counted as acceptance success. The
workspace module's startup-order docstring is corrected to match the already-tested
register-before-replay implementation.

### Final extension and worker safety gate

**2,189 passed**, 2 existing Cohere/Pydantic deprecation warnings, **697.92 seconds**.
All **25 acceptance procedures pass** after correcting the M26 fixture race; its initial
exit-1 failure (2 assertions) and both passing 25-check reruns remain explicitly recorded.
The 7 early transcript-style procedures contribute exit statuses, not assertion totals.

Independent **91 stress / 11 integration / 39 architecture** checks pass, along with
**20 GUI tabs** and **408 module imports** from an isolated dependency-free installed wheel.
Coverage is **78.0% statements / 58.1% branches** across **408 source files**. Fresh
inventories read **632 files**, assign **61 folder responsibilities**, and name/review all
**82 Markdown documents**, with no structural/reference findings. Selected Ruff and
whitespace checks pass; the 4 required callback-argument notices are retained.

The batch adds **93 safety tests and 1 architecture parameter**. Shared process mechanics,
worker boundaries, malformed transport/file refusals and request/artifact identity are
implemented and tested. Per-file AST evidence checks the worker captured baseline;
previous transformation rows remain labelled historical. No new runtime dependency or
large artifact is added. No fresh real Blender, GGUF inference, vendor cloud, Windows/VM
or GitHub CI run is claimed. Disk quotas, detached-process containment, durable worker
recovery, public multi-user deployment and broad original-product gaps remain open in
[GAPS.md](GAPS.md), rather than being hidden behind roadmap closure.

## MCP transport lifecycle batch — completed and locally verified

Documentation gate repeated across 82 Markdown documents before changes. Inspection
confirmed deadline calculation starts after a potentially blocking send; stdout/stderr
lines and HTTP/error bodies are read without byte bounds; malformed RPC error objects
can kill the stdio reader; close can block on buffered pipes held by descendants. Failed
manager discovery also retains its cached connection. These are concrete follow-ups,
not a claim that the previous test gate certified every transport failure path.

Targeted gate: **280 passed**, including **104 new MCP regressions** and a transport-override
architecture guard. Bounded send queues include caller deadlines; raw stdio handles avoid
buffered close locks; HTTP redirects/invalid credentials and malformed/oversized responses
are refused. Complete discovery has cursor/page/item/byte/time budgets and registry-name
collision preflight. Reader/sender thread startup failures and manager failed-client cleanup
are tested. At this intermediate checkpoint, broad tests and acceptances were running; final
results are recorded below. GUI smoke passes all 20 tabs. Public imports remain available; the captured
MCP AST preserves 10 methods/3 globals and names 19 method/1 parser changes intentionally.

A final resource review found redirect refusal could retain an unclosed response through
exception frames. The response is explicitly closed before refusal and a direct regression
test is added. The intermediate broad run was stopped, not counted as a success; the
full gate is restarted against the final executable tree.

Final framing inspection also found that bounded HTTP read1 can accept a valid JSON prefix
even when the declared body is truncated. Successful responses now validate framing and
byte completeness, with chunked success and ambiguous/truncated regressions. Earlier
partial coverage runs are excluded; the final broad run starts after this fix.

The semantic document pass also corrected stale gap statements: tool probes and GUI SSE
already exist; automations already implement interval/one-shot/file triggers; M35 did not
supply non-text research extractors; task-history pruning is not implied by M41. MCP
record exports show keys, but raw env/header values are stored, and custom unauthenticated
server binds are possible. These are documentation corrections, not new runtime features.
GUI SSE fallback's possible repeat POST is recorded as a source-review follow-up requiring
fault-injection tests, not claimed fixed in this MCP client batch.

### Final MCP transport gate

**2,299 passed**, **2 existing Cohere/Pydantic deprecation warnings**, **761.86 s**.
All **25 acceptance procedures pass** on the final executable tree, including M26's 25
checks. The 7 early transcript-style procedures contribute exit statuses, not assertion
totals. Two partial broad runs were stopped for final fixes and are not counted.

Independent **91 stress / 11 integration / 40 architecture checks**, **20 GUI tabs** and
**413 module imports from an isolated dependency-free installed wheel** pass. Coverage is
**78.2% statements / 58.5% branches** across **413 source files**. Inventories read **638 files**,
assign **62 folder roles** and name/review **82 Markdown documents**, with no final
structural/reference findings. Selected Ruff/whitespace checks pass; Vulture's 5 observed
required callback-argument notices are retained, not claimed absent.

This batch adds **109 MCP regressions and 1 architecture guard**. It closes client-side
queued sends, malformed/oversized/truncated responses, bounded pagination and failed-cache
cleanup within the documented scope. Public imports remain; deliberate AST changes and
older baseline evidence are separately labelled. No new mandatory runtime dependency or
migration is added. No fresh Blender, real GGUF inference, vendor-cloud, Windows/VM or
GitHub CI certification is claimed. Server authentication/framing, durable recovery,
OS-level containment/cancellation, GUI retry/idempotency and original-product gaps remain
separate follow-ups, not hidden behind this local gate.

## Broad responsibility and boundary batch — completed and locally verified

Reviewed all 82 Markdown documents before changes. This pass batches three remaining large manager splits with GUI retry correctness and MCP server request handling, instead of treating a small coverage increase as progress toward an undefined total.

Implementation: three manager packages preserve all 75 methods / 13 globals and original
wildcard exports; MCP server is separated into policy/schema and two transports. Targeted
suites pass 232 tests (including 35 new server regressions and four added owner guards).
Browser smoke passes 20 tabs plus four fault/success stream scenarios that assert no
second POST and no concurrent duplicate submission. The initial browser test found a
shadowed catch variable; it was fixed before freezing executable code. At that intermediate checkpoint, full combined verification was running; its
completed result is below, not a project-progress percentage.

The first broad M26 acceptance attempt failed one fixed wall-clock assertion (2,664 ms versus 2,600 ms). The test now proves four-child overlap with a bounded rendezvous barrier instead of loosening the threshold. The failed attempt is retained; the corrected rerun result is below. Runtime scheduler semantics are unchanged.

The first barrier rerun also failed: the default 80% CPU admission budget permits only three 25% command jobs. The fixture now explicitly sets its disposable home's ceiling to 100% for the four-child rendezvous and restores 80% afterward. This tests actual concurrency within declared resources, rather than claiming worker-count overrides admission. Both failed attempts remain recorded.

Initial broad full run stopped after the legacy GUI source test demanded automatic POST
replay. Updated that obsolete assertion to forbid replay/require the warning; fresh full
verification was required and is now recorded below; the partial run is excluded. Browser fault tests independently
pass all four scenarios with a nonempty concurrent draft retained.

### Final broad responsibility/boundary gate

**2,338 passed**, 2 existing optional-SDK warnings, **1045.00 s**. All 25
acceptance procedures individually pass after the explicit M26 resource-fixture correction;
the batch's original 24/25 result and failed first barrier are retained, not relabelled green.
Independent 91 stress / 11 integration / 44 architecture / 8 GUI-stream checks, 20 browser
tabs plus 4 injected stream outcomes, and 440 dependency-free wheel imports pass.
Inventories cover 666 files / 66 folder responsibilities / 82 Markdown documents.
This closes the named cleanup batch, not the original product or every remaining module.


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


### Reference retrieval and analysis completed

Downloaded the user's 289724-byte Archx Agent 1.9.0 gzip tar through Actions; original
SHA256 9a263ec54307cfa555b38625a8d8bb35c2dadeb5d1e35afc69b559753b09a68e.
Source and isolated no-key Chromium review confirm coherent Chat/Studio/Memory/Debug/Settings,
browser provider setup, stable stream surfaces, Stop/per-chat ownership and conversation
editing/branches as concrete reference strengths. A browser check retained code/thinking
DOM identity across incremental paints; our painter still rebuilds answer contents.
The reference already contains question-driven web search/source cards (code-inspected,
not live web-tested here). Review: docs/REFERENCE_UI_REVIEW.md. This is completed analysis,
not an implemented port or certification that every reference capability works.
Current source and retrieval workflow were published only to the session branch, not main.
The unrelated model-matrix run was cancelled; downloaded source remains outside the repo.
