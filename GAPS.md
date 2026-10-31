# Known gaps and honest limitations

This file records what is **not** true yet. If a feature is not listed as verified in
[PROGRESS.md](PROGRESS.md), do not assume it works.

## Current evidence and environment limits

The original local-only environment notes were superseded by GitHub CI. CI #26
(run `40914694127`, implementation `48dd607`) exercised a real tiny GGUF model,
eight optional SDK clients, a real Ollama daemon, a public tunnel, and official
Blender 4.2 bpy/Cycles CPU rendering. See [CI evidence](docs/ci/README.md).
This proves those recorded Linux/CPU runs, not every model, operating system or device.

* The recorded combined CI uses Python 3.11. Python 3.13 and other interpreters are
  not certified by that run.
* No microphone, camera, audio playback or GPU hardware was exercised. Speech
  recognition and synthesis are not implemented; this is not just a missing driver.
* The fresh audit environment has no Blender/bpy installation. Historical real-render
  evidence is distinct from the audit's source, API, CLI and stand-in renderer tests.
* The hash embedding provider is lexical, not semantic. Optional semantic embedding
  quality has not been established by the combined CI.

## Clarified Research requirement remains unimplemented

Research must be an AI chat that discovers and searches general web sources from a user
question, without requiring the user to supply URLs. The existing report/source-analysis
workflow is not that product. Its current value is analysing supplied material, retaining
quotes/provenance and making sourced reports, not autonomous discovery. See
[the feature inventory](docs/FEATURE_STATUS.md) for the 31 scoped-implementation / ten
partial-area roadmap count and explicit Research acceptance criteria. No original-feature
completion percentage follows from those milestone units.

## Roadmap closure is not full product completion

M01–M41 are closed **within the milestone scopes in PLAN.md**. That is not proof
that the original broad product ambitions are delivered. The repository has no separately
versioned, user-approved original requirements baseline, so a complete line-by-line
sign-off against the original brief cannot be reconstructed from the roadmap alone.
[The audit report](docs/AUDIT.md) maps the implemented areas and remaining product gaps.

Research reads local documents and supplied URLs; it does not perform general web search.
Voice measures files and records human transcripts; it cannot hear or speak. Datasets
handle text corpora; training runs two small CPU trainers, not transformer fine-tuning.
Remote compute uses a compatible worker, not managed cloud provisioning. Scenes cover
six primitive meshes, measured exports and a verified local render path, not a general
Blender editor. Automations poll interval, one-shot and file-hash triggers; there is no
cron, external-event service or managed daemon. Installers, desktop certification and
release publication remain outside the source/wheel readiness milestone.

## Execution environments: what the sandbox does not promise

* **`local` is not a sandbox.** It runs `sh -lc '<command>'` on this machine; the only control is the
  permission centre (`shell.run` is a grant or an approval). The note on every local run says so.
* **`wsl` is not a boundary.** It is a second Linux environment whose `/mnt/c` is your own disk. The
  probe says this in the `isolation` column, and the row's note repeats it; do not read "it ran in
  WSL" as containment.
* **Windows Sandbox is `detached`.** `WindowsSandbox.exe` returns immediately, so there is no exit
  code, no stdout and no streamed output - only a `.wsb` naming a log file the guest writes. The row
  says `detached` rather than inventing a `0`.
* **A container is only as isolated as its flags.** `docker` is invoked as `run --rm --network none
  -v <cwd>:/work -w /work <image> sh -lc '<cmd>'`; `--network none` is the default but
  `exec add docker --network bridge` deliberately turns it off, and the mounted directory is
  writable from inside. The busybox `sh` in a slim image is not a hardened image, and nothing here
  pulls, builds or prunes images.
* **`vmware` and `virtualbox` run a command in a guest you prepared.** No snapshots are taken or
  reverted, no guest is started or stopped, and no file is copied in - the command has to already be
  able to do its work in the guest's own filesystem.
* **`exec push`/`exec pull` work only against a `remote` target.** A container, WSL distribution or
  VM is refused by name instead of pretending to copy files into something this process cannot see.
* **Nothing streams.** A command's output arrives when it finishes (or at `execution.timeout`,
  default 60 s), clipped at the tool layer's limit; there is no pty and no stdin.
* **`execution.enabled` is off by default.** A command in a sandbox is still a command: the switch,
  plus the `shell.run` grant, is what makes `exec run` start anything at all.
* **The worker's `/exec` is a shell on someone's machine.** `--allow-exec` and `--token` exist for
  that reason; executable/non-loopback HTTP workers now require a token. A holder of that
  shared secret can use enabled authority; it is not per-user authentication, TLS or OS isolation.

## Per-mode limits

`docs/MODES.md` lists every mode with what it is for and what is honestly built. In short:
Research Mode has **no web search, no crawler and no experiment runner** (it reads local
documents and the URLs you paste), and Learning Mode has **no model grading and no media
items**. Both are marked `done · scoped` in PLAN.md: the narrower milestone passed, while these
original-product capabilities remain absent.

## Known limitations inside implemented features
* **Learning Mode does not grade prose.** An answer is marked correct only by a normalised
  comparison against the expected answer the learner wrote, or by the learner's own 1-5
  rating; both are recorded (`graded_by = exact` / `self`). There is no rubric marking, no
  partial credit and no model judgement, so "how well did I explain it" is not measured - only
  "did it match". Media items, generated exercises and multiple choice are not built.
* **Training cannot fine-tune a transformer.** Two CPU trainers really run (n-gram perplexity,
  nearest-centroid accuracy) and their numbers were measured; `lora`/`qlora`/`full` are refused with
  a computed chain, and nothing here loads weights, uses a GPU, or estimates what such a run would
  cost. There is no serving path either - an artifact can be scored with `train predict` and that is
  all.
* **Remote compute has no cloud behind it.** A worker is a second process running this build's
  trainers - there is no provider SDK, no credential, no billing, no queue, no chunked or resumable
  transfer, no sharding, and no retries. A worker is identified by the endpoint you typed and by the
  hash of the bytes it returned; there is no signature, so a worker that computes the right artifact
  and *also* lies about something else in the payload is only caught where a hash covers it.
* **A bundle carries the corpus, capped and uncompressed.** `remote.max_chars` (200 000) refuses
  anything larger rather than shipping it, so a real corpus needs a transfer mechanism this build
  does not have. Bundles are JSON with the text inline; there is no streaming and no resume.
* **Datasets are text only and stop at the export.** No training, no tokenisation, no chat-format
  templating, no image or audio records beyond counting them as shelved candidates, no cross-dataset
  dedupe, and no upload or publishing path anywhere in the build. A manifest records the source
  bytes; there are no rewriting transforms.
* **Voice cannot hear or speak.** `voice transcribe` and `voice say` are refusals with a computed
  reason chain, recorded as rows; the only transcript the schema accepts is one a person typed.
  Media support is measurement only: PNG, JPEG, GIF, WAV and text. WebP, TIFF, FLAC, MP3, MP4,
  video, OCR, captioning, transcoding and thumbnails are all absent, not stubbed.
* **Learning sessions have no clock.** A session records start, end and counts, but no
  per-item duration, and the day boundary for "today's practice session" is the ISO date
  string of the stored timestamps, not a local timezone.
* **The learning schedule is per item and per home.** No cross-goal queue, no per-learner
  profile, no jitter, no interval fuzz - the SM-2-lite table in `docs/LEARNING.md` is the whole
  model.
* **The GUI adds learning items and answers them but cannot delete or reorder.** Deleting a
  goal (with `--yes`) or an item stays a CLI act; the page deliberately has no destructive
  control.


* **Retrieval embeddings are lexical in this environment.** The default offline provider
  is `archx-hash-v1` (deterministic feature hashing). It is *not semantic*; the
  evaluation numbers in `docs/RETRIEVAL_EVAL.md` are therefore an upper bound for
  same-vocabulary queries. A real semantic model (`bge-small-en-v1.5`, 384-dim, MIT) is
  supported through `sentence-transformers` when installed, but could not be exercised.
* **`vultr/VultronRetrieverPrime-Qwen3.5-8B` was evaluated and rejected.** It is a
  visual-document retriever (8.4B params, ColQwen-style multi-vector output requiring
  MaxSim late interaction over page images), not a text embedding model, and it is not
  viable on CPU here. Evidence and the fallback are in `docs/RETRIEVAL.md`.
* **`ai_select` relevance scoring is deterministic token similarity, not a model
  judgement.** It records reasons per item and says so, but it is weaker than a
  model-based selector; `ai_proposed` likewise builds proposals from budget arithmetic
  rather than model reasoning (and requires approval).
* **Summaries are generated by the configured model.** With the simulated runtime the
  "summary" is canned text; the `generator` field records `model` and the manifest is
  marked degraded if the summariser fails.
* **`proposals` are stored but not editable item by item** in the CLI; approval is
  all-or-nothing via `--proposal <id>`.
* **Trace retention deletes rows.** Originals of *conversations and memories* are never
  deleted by compaction, but trace retention genuinely removes old events (by design,
  configurable, and errors are kept twice as long).
* **Single-machine, single-process assumptions for the writer.** Multiple *processes*
  can open the same database safely (busy timeout + WAL, tested), but only one process
  should run a `WriteCoordinator` writer against a file at a time in production use.
  Cross-process journal replay is not coordinated with a lock.
* **Provider privacy claims are unverified transcriptions.** The templates in
  `managers/providers/` record what vendor documentation says, with `claim_source` and
  `verified = 0`. No vendor API was called in this environment (no keys), so no claim was
  checked; the UI/CLI prints "vendor claim" next to each one and the user must confirm.
* **No default prices ship.** Cost is only estimated when the user supplies prices,
  because a stale built-in price list is worse than no number.
* **Region/residency is free text**, not interpreted or enforced; Archx cannot stop a
  provider from processing in another region.
* **`providers check` only probes `/models`.** A provider that answers `/models` but
  fails completions is not detected by the probe; the first real request will fail with a
  classified error and be recorded in usage.
* **Capability probes are shallow.** `models probe` sends a tiny prompt and checks the
  shape of the answer: it proves the path works, not that the model is good at it. In this
  environment the only successful probe is against the labelled test double.
* **Tool capability is probeable, not guaranteed.** The router offers a fixture tool via
  `chat_with_tools` and requires a returned call. A missing adapter path or plain-text
  answer fails the probe; passing is evidence for that model/runtime, not universal tool quality.
* **No cost-aware routing.** Prices from M20 are recorded but not used by the router score.
* **Tools do not run from a model yet.** M22 built the registry, the permission centre and
  the execution path; M25 runs tool steps in workflows. No ordinary chat turn can request a
  tool, so a model cannot decide to call one on its own.
* **`shell.run` is a granted capability, not a syscall sandbox.** Any program on `PATH`
  that is not on `tools.shell_denylist` can run once a grant exists. The denylist and the
  minimal environment reduce the blast radius; they do not contain a hostile program.
* **Approvals are out-of-band.** `approvals approve` decides a request, then the operation
  must be repeated; there is no suspend/resume of an in-flight workflow yet (M24/M25).
* **MCP authentication is optional only on loopback.** Non-loopback binds require a
  bearer token; the whitelist and shared `mcp-server` subject still control tool access.
  There are no per-person accounts, TLS or global service quotas. Unauthenticated
  loopback remains reachable by local callers; a token is not public-server certification.
* **Extensions are trusted, not sandboxed.** Their programs get a rebuilt environment and
  must keep their data paths inside their own directory, but a trusted program is an
  ordinary process. Manifest hashes are recorded; they do not prove authorship.
* **No OAuth for MCP HTTP servers**, no sampling/elicitation or prompt execution. The
  client can list prompt metadata; the Archx server does not expose prompts. Binary MCP
  content is JSON-serialised rather than stored as an attachment.
* **`tasks reproduce` does not re-run the task.** It assesses and prints commands; actually
  replaying work belongs to M25/M26. A record could therefore be right about the plan and
  still be stale about the world by the time someone follows it.
* **No task/version-history pruning policy is implemented.** These records remain
  append-only. Backup/trace retention is separate; closed M41 does not imply task pruning.
* **Version content is stored twice** (the row and the replayable write journal); a 1 MiB
  version costs about 2 MiB.
* **Task `tools` metadata is not authorization or proof of execution.** Callers can supply
  it when creating/updating tasks and executed tool history can extend it. Workflow steps
  hold declared plans; tool-run rows/timelines are the evidence of individual execution.
* **Workflows run sequentially with no loops or branches**, and a failed run is re-run from
  the beginning (`agent rerun`), repeating earlier side effects. Durable pause/resume now
  exists, but only *between* steps and only for jobs (see the scheduler entries below).
* **A checkpoint is an up-front gate**, not a mid-run pause; approving after a refusal means
  starting a new run.
* **Subagents share the parent's process** and budgets; they are separated by task and
  conversation, not by process.
* **Planner quality is model quality.** With no real model available here, the plan-parsing
  paths are exercised against the protocol stub and the simulated double, which is stated
  wherever it happens.
* **The GUI is a web page, not a native desktop window.** It has browser-scoped access,
  not arbitrary OS filesystem/hardware control. This does not mean browsers cannot offer
  file pickers or other permissioned web APIs; a native shell remains separate work.
* **One token is one user.** There are no accounts, no roles and no audit of *which person*
  did something - only of which interface and which grant.
* **The GUI cannot create, edit or run a workflow.** It lists tasks and jobs, but authoring a
  workflow (M25) and approving a proposed plan stay in the CLI; a plan editor is a real
  feature, not a panel.
* **GUI chat streams tokens without automatic replay.** Missing final frames, stream
  read failures and unsupported response readers no longer trigger a second POST. Partial
  output remains marked unconfirmed; refresh history before a manual retry. Same-page
  concurrent submissions are guarded, but no server idempotency key or in-flight model
  cancellation is supplied. An explicit/manual retry can still duplicate prior work.
* **`gui serve` is one process serving one home.** Two homes need two ports; there is no
  home switcher, because switching homes inside a running process would mean reopening the
  database and every manager under live requests.
* **No TLS and no HTTP/2.** Exposing the GUI beyond loopback means putting a real proxy in
  front of it; the flag that allows a remote bind does not make the connection private.
* **A hostile local user is out of scope.** The token protects against other origins and
  other machines. Anything that can read your home can read `archx.db` and your terminal.
* **Windows and macOS are untested.** Path containment tests cover symlinks and
  traversal on Linux; Windows-specific behaviours (drive letters, UNC paths,
  case-insensitive filesystems) are unverified.
* **Extension programs are not sandboxed** beyond a rebuilt environment, a working
  directory, a timeout and an output cap. An extension that declares `process.exec` runs as
  the user; the trust step is what keeps that from happening by accident, not the kernel.
* **A hung step in an in-process workflow cannot be pre-empted.** The job deadline is
  checked at step boundaries and a `command` job's child process group is killed, but a
  model call that never returns keeps its thread until it returns. The job is still failed
  by `reap_expired()` from any other process.
* **The memory budget is advisory.** `scheduler.memory_limit_mb` is arithmetic over declared
  estimates, not a cgroup; observed peak RSS is recorded after the fact for the worker
  process, not per job.
* **Orphaned children survive a SIGKILLed worker.** If the worker dies hard, its child
  process keeps running (it is in its own session) while the job is recovered and re-run.
  The scheduler does not try to adopt or reap a process it did not start.
* **No cron or per-job `not_before` scheduling.** The durable queue drains ready jobs.
  Implemented automations separately poll interval, one-shot ISO timestamp and file-hash
  triggers; they are not a general calendar/cron service.
* **Pause granularity is a workflow step.** A running `command` job refuses `pause`; there
  is no checkpoint inside a command's execution.
* **Unified search is keyword-only outside memory.** Only the memory source has an
  embedding path; conversations, tasks, workflows, artifacts and files are scored by term
  coverage, so a query with no shared vocabulary with the text finds nothing. The report
  says `keyword-only` instead of implying semantic search ran.
* **Search has no index, so it is linear.** Every query scans the managers (and up to
  `search.max_files` files). That is deliberate at this scale; a corpus of hundreds of
  thousands of files would need an index that could go stale.
* **File search is confined to the tool roots.** A file elsewhere on disk is not found,
  which is correct for the permission model and surprising if you expect a desktop search.
* **File search skips binaries, huge files and noise directories, silently from the
  user's point of view** beyond the aggregate counts in `report.degraded`. It does not
  report which individual files were skipped.
* **No ranking feedback and no fuzzy matching.** A typo scores zero; there is no
  spell correction, stemming or synonym expansion, so `locks` does not match `locked`.
* **Simple Mode's intent detection is rule-based**, not a classifier. A sentence that
  sounds like a search but starts with "tell me..." is treated as chat. The reason line
  makes the mistake visible rather than hiding it.
* **Simple Mode cannot answer "why did that fail?" beyond the first cause.** It reports the
  refusal and one next step; deeper diagnosis is `trace`/`tasks show`, which it points at.
* **A refusal still writes a task row.** A workflow stopped by a missing grant is recorded
  as a failed task, so repeated attempts accumulate history. That is honest, and it makes
  `tasks list` noisier than a user might expect.
* **Approvals granted through Simple Mode keep the approval's scope.** A `once`,
  conversation-scoped grant authorises exactly one run of exactly that conversation, so an
  identical request afterwards asks again. Widening that would be a privilege change, not a
  convenience improvement.
* **The Simple Mode REPL keeps state only in memory.** Leaving it loses the conversation
  handle (the conversation itself is stored); `--json` is refused there.
* **Web research only reads the URLs you supply.** There is no crawler, no search-engine
  integration and no discovery: `--mode web` with no `--url` is a usage error, not an empty
  result. Finding sources is your job (or a future MCP search tool's).
* **No search API is configured or assumed.** No key, no endpoint, no scraping. Adding one
  means writing a tool with its own capability, which is why it is not smuggled into the
  researcher.
* **Research does not extract PDFs, office documents or images.** `net.fetch` accepts
  text content types. Dataset preparation is text-focused too; closed M35 is not evidence
  that those extractors exist.
* **Credibility is not assessed.** Every web page is `credibility='unknown'` and every local
  document is `internal`. Archx does not rate publishers, so a persuasive blog and a
  specification look the same in the source list.
* **Stance needs a model.** Without one, every source is `unknown` and the report says the
  absence of a judgement is not agreement. Relevance is term overlap, not understanding, so a
  source can be highly relevant and irrelevant to the actual question.
* **Planning and judging cost tokens.** `research.max_judged_sources` bounds the judgements,
  but a run with a model performs one call per judged source plus the plan plus the reading.
* **The report is only as good as the excerpts.** The extractive answer quotes a window of at
  most `research.excerpt_chars`; a document whose relevant sentence sits outside that window
  contributes nothing useful and no warning.
* **`research verify` checks form, not truth.** It confirms that citations resolve and that
  claims carry one; it cannot tell whether the cited sentence supports the claim.
* **A research run has no resume.** If it fails mid-gather the run is `failed`; there is no
  cursor to continue from (unlike a workflow job). Re-running re-reads the sources.
* **`net.fetch` has no robots.txt check, no caching, no cookies and no per-host rate limit.**
  It is a single-request fetcher, and the user supplies the URLs, so politeness is manual.
* **`net.fetch` follows at most `tools.fetch_max_redirects` (3) and fails closed beyond it.**
  Legitimate sites with longer chains (login walls, CDNs) are refused rather than chased.
* **Secret references are not universal at-rest protection.** Provider keys should use
  `secret://` references, but literal configuration values and MCP env/header maps can be
  stored in configuration/SQLite and its journals/backups. Key-only display and pattern/
  registry-based export redaction are not encryption; unusual credentials can evade
  redaction. Protect the home directory and avoid literal secrets where references work.

## Maintenance and verification follow-ups

The audit passes split interface concentration and 36 named domain/application/adapter/interface
modules into responsibility-focused packages, while preserving public imports and
released migration SQL. This is still not independent-service isolation or proof that
every branch is tested. The remaining larger modules, folder map and per-file coverage
are listed in [the audit report](docs/AUDIT.md) and
[technical reviewer guide](docs/TECHNICAL_REVIEW.md).

A complete requirement baseline, broader platform tests, real speech and transformer
training would be new work. Existing green tests do not establish those capabilities.
Scheduled command output is spooled to disk with bounded in-memory reads, but there is
no hard disk quota. A legacy manually submitted command job is trusted local execution,
not an untrusted-code sandbox. Do not expose that queue to untrusted users.

The runtime follow-up additionally bounds local-tool output **memory**, not spool disk
use; POSIX process-group timeout handling is not Windows tree containment or an OS
sandbox. Native lifecycle tests inject a fake dependency, not real GGUF inference.
The documentation-first follow-up fixes the previously reproduced single-key settings
and directory registration defects with migration/restart/catalogue tests; see the
[maintenance audit](docs/AUDIT.md#documentation-first-maintenance) for its own gate.
Already overwritten legacy setting values cannot be recovered. Catalogue observations
are snapshots, not full GGUF validation or a guarantee against filesystem races.

Extension output capture and POSIX process-group timeout handling are addressed by the
extension/worker safety continuation; see [its audit](docs/AUDIT.md#extension-and-worker-safety-continuation)
for final verification. Spooling still has no disk quota, and Windows process-tree
containment is not supplied. Detached/background children may survive. File snapshots
are not race-free OS isolation; valid write batches are not transactional under I/O failure.
Worker training jobs are still in-memory without durable recovery. Active training and
retained job records now have explicit caps; HTTP handlers, validation and `/exec`
concurrency still have no global admission quota.

Executable workers and all non-loopback/hostname worker binds now refuse startup without
a token; only numeric-loopback training-only serving may omit one. CLI `--token-env`
avoids putting its value in argv, not OS-environment exposure. Captured server credentials
cannot be disabled by mutating the worker's token field; restart to rotate them. Shared
authentication and bounded training admission do not certify public multi-user deployment.


### MCP transport boundaries after lifecycle hardening

MCP now bounds messages/diagnostics/queues and complete paginated discovery, starts caller
deadlines before transport sending, refuses redirects and closes failed/dead cached clients.
It does **not** sandbox discovery programs, suppress inherited credentials, durably restore
sessions, automatically replay timed-out calls or cancel remote side effects. Finite SSE
responses are supported, not long-lived/resumable server subscriptions. No complete JSON
Schema evaluator is provided. Detached children, Windows process-tree containment,
uninterruptible OS/resolver/header I/O and global connection/resource quotas remain outside
this gate. A background daemon can outlive the waiting caller. Preflight validation is not
transactional rollback of later registry/database I/O failures. See the [MCP audit](docs/AUDIT.md#mcp-transport-lifecycle-continuation).

### What the cleanup percentage does and does not mean

The remaining-owner batch addresses all nine large modules named at the preceding checkpoint.
Its fixed ledger has 36 targets including 27 earlier transformations. Only accepted targets
count; code moved but not finally verified remains pending. This is an equally weighted
structural backlog, not an estimate of time, exhaustive code correctness or the original
product. Medium-sized owners such as configuration, scheduling, embedding persistence,
datasets/coding managers, search and remote orchestration remain review candidates.
Speech, transformer fine-tuning, managed cloud, durable worker/MCP recovery, OS containment
and fresh native/platform validation are not completed by rearranging files.

The final fixed structural ledger is now **36/36 accepted (100%)**, from 27/36 (75%).
That closes its nine remaining named owners only; all product/validation and further
semantic-review gaps above remain open. It is not a percentage of original requirements.
