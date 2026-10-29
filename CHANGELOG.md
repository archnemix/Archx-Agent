# Changelog

All notable changes. Format loosely follows Keep a Changelog; versions track the
milestone block rather than semantic-release cadence, because M01-M20 are one development series.

## [Unreleased]

### Fixed
- **One save is one approval request.** `code write` reads the previous content to build a diff;
  when `fs.read` was not granted that read created a *second* pending approval for a file the
  user had only asked to write. It now asks the permission centre without opening a request and,
  if the read is not allowed, records the diff as partial with the reason. (`docs/GUI.md` already
  promised one request; now the code does too.)

### Changed
- **The roadmap's M38 is now execution environments**, and Blender, the automations and hardening
  moved to M39-M41. M36 and M37 both ended by needing a place to run work, and nothing had been
  built for those three, so the shift costs nothing (`PLAN.md` §Note on the M38-M41 numbering).
- **A `local` execution run goes through a shell.** `exec run "echo a && echo b"` used to be refused
  as "command not found: echo a" because the local backend treated the string as one argv; it now
  runs `sh -lc '<command>'` (or `cmd /c` on Windows) like every other backend, so a command line
  means the same thing everywhere - and the note says the local target has no isolation.
- **A `docker` mount is absolute.** The invocation says
  `-v /abs/path:/work` rather than `-v .:/work`, which meant "wherever docker was started".
- **A worker's HTTP refusal is a refusal, not a network failure.** A 401 from `/exec` used to be
  reported as `failed` with a URL error; the body is now read and the run is recorded as `refused`
  with the reason the worker gave.

### Added - M38, Execution environments and sandboxing

- **Seven backends, one wrapper builder.** `local`, `remote`, `docker`, `wsl`, `windows-sandbox`,
  `vmware` and `virtualbox` are known by name; `build_invocation` is a pure function per kind, its
  result is stored on the run row and printed by `exec show`. A target that cannot run here is
  recorded as `refused` with the reason and the command that would enable it, so "I set it up and it
  did not work" is a row, not a memory.
- **The wrapper is verified by a stand-in binary.** The acceptance script plants a shell script named
  `docker` on `PATH` that appends its own `argv` to a file, then asserts `--rm`, `--network none`, the
  absolute host mount, the image and `sh -lc '<command>'` are all there. A target that quietly ran the
  command on this machine would fail that check rather than pass silently.
- **Three exit codes that mean three different things.** `0` the command ran and succeeded, `1` it ran
  and failed, `3` nothing ran (execution off, backend unusable, target refused, wrong token, missing
  `shell.run` grant). A refusal stores every reason, costs nothing, and returns the approval id to
  print when that is what is missing.
- **WSL is labelled *not a boundary*** in the probe table itself - `/mnt/c` is your own disk - and
  **Windows Sandbox records `detached`** rather than an invented exit code, with the generated `.wsb`
  naming the log file the guest writes, a `--read-only` mount option, and networking off unless asked
  for (`--network none` is a string, and a string is truthy: read as a boolean it switched the
  sandbox's networking *on* for the one value that means off).
- **`train run --target local|remote`.** One row either way (`training_jobs.target`,
  `remote_job_id`), and a remote run's perplexity is *equal* to a local run's because the worker calls
  the same `train_records()`. A sandbox is refused as a training target by name: a trainer needs its
  dataset and artifact inside it, which is a different milestone's work.
- **`exec push` / `exec pull` keep a hash ledger.** Every path records `sha256_local` and
  `sha256_remote`; a pull compares base, local-now and remote-now, so a file edited on both sides is a
  **conflict** with the local copy untouched and exit 3 - `--force` is an explicit act. Unchanged
  files are skipped; the ledger is queryable with `exec files`.
- **A worker that runs commands only when its operator says so.** `remote worker --allow-exec
  --token <secret> --workdir <dir>`: without the flag `/exec` answers 403 naming it (training still
  works), with a token every route requires `Authorization: Bearer` (constant-time compare), and a
  `cwd` that escapes the workdir is refused. A wrong token is a *refusal* - the command did not run -
  not a failure.
- Metrics, output and the file ledger are stored; stdout and stderr are also written through
  `fs.write`, so the evidence outlives the terminal.
- Schema v28 adds `execution_targets`, `execution_runs` and `execution_files`, and adds `target` and
  `remote_job_id` to `training_jobs`.
- `execution.enabled` defaults to **false**: a command in a sandbox is still a command.
- The GUI grew an eighteenth panel: the probe table with reasons, a command box with a target
  chooser, the run ledger, and a run's invocation, output and refusal reasons.

### Added - M37, Remote compute and portability
- **A bundle that identifies its input.** `remote export` writes one JSON document carrying the
  corpus, the M35 manifest checksum and the declared run, then hashes it. Each record carries two
  digests that are *not* the same number: `file_sha256` measured with `fs.probe` (bytes, the same
  measurement the dataset recorded) and `text_sha256` of what `fs.read` returns (trimmed). One number
  for both would refuse the bundle's own records; the pair is what catches an edit after the build
  and an edit in transit, respectively.
- **Nothing leaves without three answers.** `remote.enabled`, `remote.endpoint` and
  `remote.require_approval` (on by default, so the setting is not a lie). A refusal is a row with
  every reason and an entry in `remote_attempts`; the job can be dispatched later.
- **A worker with no database.** `archx-agent remote worker` takes a bundle, re-checks the protocol,
  the body hash, every text digest, the rebuilt manifest and that a `train` split exists - refusing
  over the wire with the reason - and then calls the same `train_records()` the local command calls.
  A remote run's perplexities are **equal** to a local run's, and the tests assert equality.
- **The artifact is hashed twice.** `claimed_sha256` (what the worker said) and `received_sha256`
  (what this machine measured) are separate columns because the point is that they can disagree. A
  disagreement stores the file, marks the job `received`, records the attempt as `mismatch`, and sets
  no `verified_at`; `remote verify` re-reads the file *and* re-checks the claim, so asking twice
  cannot rescue a misreported hash.
- **A dispatch that never arrived is a row** - `failed` with the error stored, in the same spirit as
  M34's refused probes and M36's refused runs. A worker speaking `archx-remote/0` is refused with
  both versions named.
- Schema v27 adopts v8's reserved `remote_jobs` with `ALTER TABLE` and adds `remote_attempts`.
- The GUI grew a seventeenth panel: bundle a dataset, approve, dispatch, collect, and the two hashes
  shown as separate rows.

### Added - M36, Training and model modification
- **Two trainers that really run**, both dependency-free and deterministic: an n-gram language model
  with add-k smoothing scored by **perplexity** per split, and a nearest-centroid classifier over
  hashed bag-of-words scored by **accuracy**. Neither is a stand-in for something else.
- **An unseen word is scored, as `<unk>`, rather than skipped** - skipping is how a language model
  reports a number no text could produce. The counts and the smoothing are in the artifact, so
  anyone can recompute the perplexity; the acceptance script does exactly that with an independent
  implementation and fails on a disagreement above 1e-9.
- **Fine-tuning is refused by name.** `lora`, `qlora` and `full` walk a computed chain - the switch,
  the base model, the weights directory, the library, the GPU, the adapter - report every missing
  link in order, and store the refusal as a row (exit 3). A refused run has no artifact.
- **Nothing runs until the dataset can support it**: `train preflight` checks the split, the
  validation records, the build and M35's manifest, so a corpus that drifted after its build cannot
  produce a number.
- Metrics are rows (`training_metrics`), so a comparison is a query, an empty split is absent, and
  a metric that could not be measured is null rather than zero. `train compare` names a winner only
  when every run used one method and every one produced the metric.
- The artifact is written through `fs.write`, hashed into the row and registered as a version;
  `train predict` re-reads it from disk.
- Schema v26 adopts v8's reserved `training_jobs` with `ALTER TABLE` and adds `training_metrics`.
- The GUI grew a sixteenth panel: run a trainer, read the metrics, and see the refusal card with
  every missing link.

### Added - M35, Dataset preparation
- **Every candidate is a row.** A file removed by a cleaning rule keeps `status = 'dropped'`, the
  rule that removed it and the reason; `dataset explain` answers "why is this not in my dataset"
  from the record, and the CLI and the page both show the dropped rows.
- **Scanning goes through the tool layer**, one `fs.list` per directory (so every level is a
  permission check), with a depth bound and a refusal on a truncated listing rather than a scan
  with invisible holes. A text suffix hiding binary bytes is recorded as binary: the refusal *is*
  the reason.
- **Splits follow from the record.** `bucket = hash(seed + ':' + sha256)` means equal bytes cannot
  straddle splits and adding a file does not move the existing rows. A resaved document - same text,
  different whitespace or case - is caught by a normalised hash recorded at scan time, refused with
  the crossing pair named, and closed by `dataset clean --normalize`.
- **The manifest is a claim that can fail.** `build` writes the JSONL export through `fs.write` and
  records a sha256 over the manifest's sorted lines; `verify` re-reads the files, prints stored
  versus recomputed and names each changed or missing record. The CLI exits 3 - nothing broke, the
  corpus moved.
- **The license is recorded, never inferred.** Unstated is `unknown`; `--require-license` refuses
  instead of inventing one.
- Schema v25 adopts v8's reserved `datasets`/`dataset_transforms` with `ALTER TABLE` and adds
  `dataset_records`, one row per candidate, plus a step ledger (`scan`, `clean`, `split`, `build`).
- The GUI grew a fifteenth panel: create, scan, clean, split, build, verify, and the record table
  with the dropped rows and their reasons.

### Added - M34, Voice and media
- **A media fact is a fact only if it was read from the file.** `application/media.py` parses PNG,
  JPEG, GIF and WAV headers by hand and reports what the container declared; anything else is
  refused with the bytes it began with. No PIL, no ffmpeg, no `file` binary: a header parse is
  thirty lines per format, and a media pipeline that needs a 60 MB wheel will not run where it is
  needed.
- **The file name is a claim, kept beside the measurement.** A PNG named `.jpg` is stored as a PNG,
  with `name_mismatch` set and counted in `voice stats`. A WAV whose header claims more data than
  the file has keeps both numbers. Nothing is adopted from the extension and nothing is rejected
  because of it.
- **The same bytes are one asset.** The sha256 decides; a repeated probe returns the existing row
  with `duplicate: true`, and `--force` stores a second one.
- **Retaining the bytes is a decision.** `--retain` refuses before copying anything until
  `voice.retain_audio` is on; then the copy lands under the file's own hash.
- **Asking it to hear or speak is refused on the record, with every missing link named.** The chain
  is computed - the switch, the model setting, the registry, the model's claim, the runtime, the
  adapter - so the reasons change when the workspace does, and the attempt is a row in
  `voice_attempts` (CLI exit 3; HTTP 200 with `status: refused`, because nothing broke).
- **The only transcript this build can store is one a person typed**, enforced by
  `CHECK (source IN ('human'))` in the schema rather than by the service alone.
- New tool `fs.probe` (capability `fs.read`, low risk): reads a head as bytes and hashes the file;
  `fs.read` still refuses to decode a binary file as text.
- The GUI grew a fourteenth panel: measurement, the disagreement with the name, the refusal with
  its reasons, and a form to record the words you wrote.

### Added - M33, Play Mode
- **The rules are the only authority.** `application/games.py` holds tic-tac-toe, connect four and
  nim as pure rules: build a board, list the moves that are legal *there*, apply one, say whether
  the game is over. Every mover - a person, the engine, a model - goes through the same `apply`
  and gets either a position or a reason, so legality is decided in one place.
- **A refused move is kept.** It is written to `game_moves` with `legal = 0` and the rules' own
  reason, the board does not move and `move_count` does not advance. `play history` counts both,
  and the page shows the refusals in the same table: a log of only the moves that worked cannot
  show you that the rules held. Over HTTP a refusal is `200` with `legal: false`; the CLI exits 2.
- **The engine cannot cheat by construction.** It chooses from `legal_moves(state)`, so an
  illegal move is not a bug waiting to be found; perfect-play tic-tac-toe draws against itself,
  nim leaves a zero XOR, and connect four looks two plies ahead - and `docs/PLAY.md` says two
  plies is not strong rather than implying otherwise.
- **A simulation is a record, not a picture.** `play sim` runs Conway's life under a fixed named
  rule (`B3/S23`), storing the parameters, the population series, the final grid and its sha256;
  `play replay` recomputes from the parameters alone. A doctored hash fails its own replay with
  both hashes printed (exit 1). Parameters are refused rather than clipped, and wrapping is
  refused by name because this build has no torus rule.
- Schema **v23** adopts the `games`/`game_moves` tables reserved by v8 with `ALTER TABLE` - a
  reserved table is not a free table, so it is extended rather than redefined under whoever has
  rows in it - and adds `play_sims`.
- The GUI grew a thirteenth panel: board as text, legal moves as buttons, engine move, and the
  move log with its `why` column; simulations show their hash and replay it in place.

### Added - M32, Experimental Mode
- **An experiment is a declaration.** `archx-agent experiment create NAME --command "python
  bench.py {n}" --param n=100 --metric-source stdout-json` records the command, its parameters
  and where the numbers come from, in `experiment_specs` (schema v22). A placeholder with no
  declared parameter, a declared parameter the command never uses, and a metrics file that
  escapes the experiment's directory are all refused by name before anything runs.
- **A metric is a metric only if the experiment said where it comes from.** The runner reads the
  declared source - the last non-empty line of stdout as JSON, or a JSON file the run writes,
  through `fs.read` like everything else - and nothing else. A source that is missing,
  malformed, or not numeric leaves the run with a `metrics_error` sentence and **no** metric
  rows, and `experiment compare` lists those runs by id with the reason instead of dropping
  them. No zero, no silent average.
- **Every run is a run.** The parameters actually used, the resolved command, the exit code, the
  duration, the output as an `experiment-log` artifact, a `experiment` task marked *manual* with
  the numbers on its timeline, and `passed`/`failed`/`timeout`/`refused`/`error` as distinct
  states. A command that exits non-zero is data, not an exception; a refusal (no `shell.run`
  grant) is exit 4 with the approval id and a `refused` row.
- **Comparison names what it cannot compare.** `experiment compare --metric quality [--minimise]`
  picks the best run, and the notes list the runs with no value for that metric, the runs that
  did not pass, and any run whose parameters do not match its neighbours.
- **A substituted parameter must be one shell-safe token.** `--set 'n=5; rm -rf /'` is refused
  before anything starts, rather than quoted into something the user did not ask for.
- Metrics are rows in `experiment_metrics`, so the ranking is a query; `close`/`reopen` keep the
  history and `delete --yes` takes the runs with it.
- The GUI grew a twelfth panel (declare, run with overrides, the run table with the column that
  says *why* a run has no number, and the comparison with its notes); `scripts/gui_smoke.mjs`
  exercises it.
- `pytest tests/test_experiments_m32.py` (66), `scripts/acceptance_m32.sh` (53 checks over a real
  socket), a CI step, `docs/EXPERIMENTS.md`.

### Added - M31, the coding workspace
- **A session is a directory, a task and a record.** `archx-agent code open` binds a directory
  inside the tool roots and gives it a `coding` task marked *manual* (a session is used across
  many commands, so a process exiting is not the work ending). The three tables are
  `code_sessions`, `code_changes` and `code_runs` (schema v21).
- **Every action is a tool call.** Reading is `fs.read`, saving `fs.write`, deleting `fs.delete`,
  running `shell.run` - all through `ToolManager`, so the grants and approvals are the same ones
  the CLI and the page already use. With no grant the file is untouched, the refusal names the
  approval (exit 4, or `403 approval_required` over HTTP) and nothing half-happens. A write you
  may not read still works and says the diff is partial, instead of raising a second approval.
- **Edits are diffs you keep.** Every change is a row with a unified diff, both checksums and an
  artifact on the session's task; `code diff` is the whole patch as one more artifact.
- **The runner records every command** - the string as typed, the argv that ran, the directory,
  the exit code, the duration, the output, and refusals as rows too. A failing command exits 1 and
  asks a question on the task; a timeout is `timeout`, not `failed`; `code rerun` replays a row.
- **Checks come from the project.** `archx.checks.json` is strict data (unknown fields, duplicate
  names, a missing command and a bad timeout are refused by name); `code test` runs a named check
  and records it under that name.
- The GUI grew an eleventh panel: session list, open form, path field, read/save/delete, a
  textarea, a command box, the check button, the diff and the ledger. It makes exactly the calls
  the CLI makes, and `scripts/gui_smoke.mjs` (jsdom) exercises it.
- `pytest tests/test_coding_m31.py` (66), `scripts/acceptance_m31.sh` (48 checks over a real
  socket), `docs/CODING.md`.

### Fixed
- **The GUI answered a client's mistake as a server fault.** A `model_id` that was not a string
  reached SQLite and came back as `500 ProgrammingError`; a model that does not exist came back
  as `500` because `ModelNotFoundError` inherits `ProviderError` and the map stopped at the base
  class; a `message` that arrived as a number or an object was `str()`-coerced and stored as the
  user's turn. All three are the caller's to fix and are now `400`/`404` with a code that says
  which. The status table is ordered specific-first and every 5xx is now genuinely unexpected.
- **`PATCH` and any misspelled verb got the stdlib's HTML `501` page**, the only response in
  this app not shaped like its own JSON. Every verb now reaches the router.
- **`GET /api/health` answered `POST`, `PUT` and `DELETE`** — with a payload and without a token
  — so probing it proved nothing. It is `GET`/`HEAD` only, checked before the CSRF gate.
- **A body over the limit got a connection reset instead of the `413`**, because the server
  refused and closed while the client was still uploading. It now drains a bounded amount of
  the in-flight body first, so the refusal can be read.
- **An unauthenticated write said `csrf`**, which pointed at a header when the actual problem
  was that nobody had identified themselves. No cookie, no CSRF check: `401 unauthorized`.
- **A 4000-character asset name returned `500 missing_assets`.** Names over 255 bytes and any
  `OSError` while reading one are now `404`, which is what an unreachable file is.

### Added
- Three suites that test the seams rather than the units: `tests/test_stress.py` (13 — eight
  concurrent writers, twenty concurrent chats, ten parallel streams, a deliberately slow
  provider, fd and thread counts), `tests/test_edge_cases.py` (78 — field types, message
  boundaries at exactly 8000/8001, RTL/CJK/NUL/astral text, malformed JSON, every verb, a
  15-row provider-fault status table) and `tests/test_integration.py` (11 — one turn seen by the
  CLI, the GUI and SQLite; a real subprocess; the OpenAI SDK through the whole stack). They
  found every bug in the list above.
- CI runs those three as their own steps (`stress and the hostile client`, `end to end across
  the cli, the gui and sqlite`) so their timings are visible on the runner instead of hidden
  inside a 400-second "unit tests" row.
- `scripts/ci_evidence.sh <run-id>` rebuilds `docs/ci/` from what the workflow published, and
  `docs/ci/RUNS.tsv` is the history its table is drawn from. The numbers in that README are now
  lifted out of the logs instead of retyped after reading them.
- **Run #8 (12 steps, all ok)** on the runner: 1384 tests in 372 s, 91 stress/edge in 46 s and
  11 integration in 17 s - the same three counts as this sandbox. `docs/ci/`.
- **Run #10 (13 steps, all ok)**: 1448 tests in 348 s, the M31 acceptance 48/48 over a real
  socket on the runner, plus the SDK matrix, a real Ollama daemon and a public URL.
- An `openai-compatible` provider template for third-party endpoints (Z.ai, DeepSeek, a gateway)
  whose wire is OpenAI's but whose terms nobody here can source: `--base-url` is required, the
  privacy block says "unknown - not transcribed", and all four consent rungs still apply.
- **The chat reply streams into the page.** `POST /api/chat/stream` writes server-sent events
  (`chunk` … `done`, or `error`) for the same turn the non-streaming route records; the page reads
  the body with `fetch`/`getReader`, paints each piece as it arrives, and replaces it with the
  recorded text at the end. No `Content-Length`, `Connection: close`, and a fallback to the
  whole-reply endpoint when the browser cannot stream.
- **`models probe --capability tools` can actually pass now.** Tool calling was offered and never
  measured, because nothing ever offered a tool. `HttpChatRuntime.chat_with_tools` and
  `SdkTransport.chat_with_tools` (OpenAI shape, plus Anthropic's flat schema) send the tool and
  parse the call; a prose reply, a missing path, or a client with no implementation each fail in
  their own words rather than being counted as success.
- `scripts/acceptance_m29.sh` grew to 60 checks (the stream, its frames, and its credential).
- **The CI workflow runs, and its output lives in the repository.** Editing `.ci/trigger` starts
  `model-matrix.yml`; every step writes `$LOGDIR/NN-<name>.log` and a `status.tsv` row, and a
  background publisher pushes the folder to the `ci-logs` branch every 45 s. `scripts/ci_logs.sh
  --list|--run|--tail|--wait` reads it back over git with no Actions token. Run #4 is green:
  install, pytest (1251 passed on the runner), llama.cpp + SmolLM2-135M served, a real completion,
  four vendor clients answering *and streaming*, a real Ollama daemon, and a Cloudflare tunnel with
  the OpenAI SDK on the public URL.
- `docs/ci/` keeps that run's artefacts (status table, model answer, tunnel url, per-client output).
- **Exact-path contract for the SDK clients.** `tests/test_sdk_m22.py::TestPaths` pins the path each
  client requests and `TestDefaults` asserts `default_base_url + path` equals the vendor's public
  URL. The groq and together defaults were wrong (they append `/openai/v1` and `/v1` themselves) and
  are now the bare origin.
- `scripts/strict_openai_stub.py`: a stand-in for llama-server that 404s unknown routes, so
  `remote_model.sh` can be rehearsed locally without hiding a wrong base URL.
- `scripts/remote_model.sh` streams after the chat call inside the same live transport, reports the
  base and the path it composed, and distinguishes SKIP (protocol mismatch, 404) from FAIL.
- **Four more official SDKs, and one of them needs no key.** `groq`, `together`, `cohere` and
  `ollama` join `openai`/`anthropic`/`google`/`mistral`, so `models sdks` lists eight clients.
  `SdkSpec.key_required` records that Ollama's local daemon must *not* be given a credential:
  `transport.available()` is ready for it only on a loopback endpoint, `Workspace`
  `runtime_availability` says `ready: a local Ollama needs no key (no data leaves this machine)`,
  and the same client aimed at a remote host is still refused. Cohere is driven through
  `ClientV2` (`POST /v2/chat`, `usage.tokens`), Ollama through `POST /api/chat` with the knobs in
  `options`; Groq and Together reuse the OpenAI shape, with their base URLs carrying the `/v1`
  those clients assume.
- `KNOWN_PROVIDERS` gained `groq`, `together`, `cohere`, `mistral` and `ollama` templates, each
  with a `privacy_claims` block whose retention/training wording says *not transcribed here*
  rather than inventing vendor terms.
- **CI you can watch without an Actions token.** `.github/workflows/model-matrix.yml` runs on a
  push that changes `.ci/trigger` (no API dispatch), writes every step's output to
  `$LOGDIR/NN-<name>.log` plus one `status.tsv` row, and a background publisher pushes the folder
  to the `ci-logs` branch every 45 s and again at the end. `scripts/ci_logs.sh --list|--run|--tail|--wait`
  reads it back over git and exits 1 if any step failed, 3 if no run has appeared. The job covers
  pytest, a real llama.cpp server with SmolLM2-135M Q4_K_M, `scripts/remote_model.sh` across every
  installed client, a real Ollama daemon in Docker, and a Cloudflare quick tunnel through the
  OpenAI SDK.
- `scripts/remote_model.sh` uses `python3`/`archx-agent` from `PATH` when there is no `.venv`
  (the runner case), appends `/v1` for the clients that need it, and says `SKIP` - with the
  reason - for `cohere`/`ollama` when the target is an OpenAI-shaped server.
- **Every SDK client streams.** `SdkTransport.stream` holds one parser per vendor
  (`chat.completion.chunk` deltas, Mistral's `.data` wrapper, Anthropic `content_block_delta`,
  Gemini `streamGenerateContent` over a GET/POST, Cohere `content-delta` events, Ollama JSON
  lines); `SdkChatRuntime.stream` uses it instead of returning one chunk, so the declared
  `supports_streaming` is now true in fact. `chat --stream` works through all eight, and
  `scripts/remote_model.sh` streams from the runner too.
- `tests/test_sdk_m22.py` grew to 61 tests (Groq/Together request shape, Cohere v2 parsing, Ollama
  `/api/chat` and its `options`, keyless-local vs key-required-remote, the workspace path);
  `scripts/acceptance_sdk.sh` grew to 86 checks.

- **Google Gemini is a real provider.** `adapters/gemini_runtime.py` speaks the
  `generateContent` / `streamGenerateContent` protocol natively (`contents`, `systemInstruction`,
  `generationConfig`, `usageMetadata`, `promptFeedback`), sends the key only as the
  `x-goog-api-key` header, and classifies 400/401/403, 404, 429-as-quota vs 429-as-burst-limit,
  5xx, non-JSON and safety blocks into distinct domain errors with their own retry flags.
  `models add-gemini --name flash --model gemini-2.0-flash [--credential-ref secret://env/…]`
  registers it and refuses a literal key with exit 2.
- `Workspace.register_gemini` is the one registration path, used by the CLI *and* the GUI.
- The GUI Models panel is now actionable: a *Connect Gemini* form (the key is a `secret://`
  reference, never typed in), `test chat` per model, and the **consent ladder** - four rungs
  (`consent_policy`, `provider`, `privacy`, `consent`) rendered from the same conditions
  `assert_remote_allowed` enforces, each with the button that climbs it.
- API: `GET /api/models` gained `gates` + `provider_id`; `GET/POST /api/models`,
  `GET /api/models/{id}`, `POST /api/models/{id}/{probe,provider}`, `GET /api/providers`,
  `POST /api/providers/{id}/{privacy,consent}`, `POST /api/settings/model.local_only`
  (persisted to `config.json`, so a restart agrees with the page).
- `scripts/gemini_protocol_stub.py`, `scripts/acceptance_gemini.sh` (60 self-checking
  assertions over a real socket) and `scripts/gui_smoke.mjs` (jsdom: ten tabs render, four
  ladder rungs draw, the form posts, no page errors).
- `tests/test_gemini_m21.py` (56 tests: request shape, credential handling, answer parsing,
  streaming, the failure taxonomy, the consent gate, the GUI ladder).

### Added (SDKs)
- **A second way to reach a vendor: its own SDK.** `runtime=sdk` drives `openai`, `anthropic`,
  `google-genai` or `mistralai` through `adapters/sdk_transport.py`, translating each client's
  objects into the same `ChatResult`. Clients are built with `max_retries=0` (retrying is the
  router's decision) and their parameters are feature-detected, because vendors move them
  (`anthropic` 2.x dropped `temperature`; OpenAI added `max_completion_tokens`).
- `models sdks` lists which clients are importable and which variable each expects;
  `models add-sdk --name --sdk --model [--base-url] [--credential-ref]` registers one, refusing
  a literal key with exit 2. The `sdk` runtime is in `NETWORK_RUNTIMES`, so the four consent
  rungs apply to it.
- API `GET /api/sdks`; the Models panel's transport picker lists installed clients (missing ones
  are labelled, not hidden) and each model card names the SDK it uses.
- `.github/workflows/local-model-tunnel.yml` serves SmolLM-135M Q4_K_M with llama.cpp on a
  runner, proves a completion, exposes it over a Cloudflare quick tunnel and publishes the URL
  as `tunnel-url.txt`; `scripts/remote_model.sh` then runs every SDK against that URL and
  registers it in Archx.
- `scripts/acceptance_sdk.sh` (46 self-checking assertions over a real socket) and
  `tests/test_sdk_m22.py` (40 tests, all four clients against one local server).

### Changed
- **Every network-capable runtime is gated by one allow-list.** `Workspace.NETWORK_RUNTIMES`
  replaces the per-runtime check in `assert_remote_allowed`, so a new adapter cannot become a
  way around the consent rules.
- The "endpoint is not a registered provider" refusal now names the right template
  (`--template google` for a Gemini model, `--template openai` for the rest).
- `ModelManager.update` merges `facts` and `user_metadata` instead of replacing them, and
  `facts` is a writable field - a model's endpoint and API version could previously be set
  once and never corrected.
- The provider-echoed key inside a Gemini error is redacted to `[REDACTED]` before the message
  reaches the caller.
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
