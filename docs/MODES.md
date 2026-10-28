# Modes: what each one is for, and what is actually built

This file answers two questions that the milestone reports do not answer directly:

1. **What did I ask for?** — the forty milestones, in one list, with their real status.
2. **What should each mode do, and what does it do now?** — the same shell, different tools.

The interface is deliberately the same everywhere: a left sidebar of modes, one top bar that
shows the tools the current mode has, and a work area. What changes between modes is the
**tools** and the **controls** — a chat composer is not a hint ladder, and a citation check
is not a schedule. The table below is the honest map of that difference.

## 1. The forty milestones

`done` means verified in this environment, with tests and an acceptance script — the evidence
is linked per row in [PROGRESS.md](../PROGRESS.md). `partial` means the milestone shipped but
a part of its stated purpose is not built (each one is explained in §3). `not built` means
there is no code.

| # | Milestone | Status | What it actually is |
|---|-----------|--------|---------------------|
| M01–M09 | Foundation: package, paths, config, errors, storage, CLI | done | the floor everything else stands on |
| M10 | Conversation model | done | ordered messages, restart-safe |
| M11 | WAL storage, exactly-once writes, recovery | done | survived a SIGKILL mid-write |
| M12–M16 | Events, projects, artifacts, secrets, redaction | done | the plumbing |
| M17 | Memory: six systems | done | active, permanent, archival, project, solution, learning |
| M18 | Embeddings + retrieval evaluation | done | lexical by default; a real semantic model is optional |
| M19 | Context strategies | done | five strategies, each explained |
| M20 | Provider catalogue + privacy metadata | done | consent, local-only, usage accounting |
| M21 | Capability-safe router + model management | done | refuses models it cannot run, and says why |
| M22 | Tool registry + permission & approval centre | done | every tool call is a grant or an approval |
| M23 | MCP client/server + extensions | done | stdio servers, tools, resources |
| M24 | Task history, versions, reproduction | done | timeline, artifacts, replay commands |
| M25 | Workflows: user-directed and model-proposed | done | budgets, checkpoints, subagents |
| M26 | Job scheduler | done | claims, deadlines, pause/resume, SIGKILL recovery |
| M27 | Simple Mode + unified search | done | one query across nine sources |
| M28 | **Research Mode** | **partial** | real runs over local docs and supplied URLs; no web search, no crawl, no experiments (see §3) |
| M29 | GUI core workflows | done | this interface; a client of the same managers |
| M30 | **Learning Mode** | **partial** | goals, items, hints, schedules, sessions; no model grading, no media (see §3) |
| M31 | **Coding workspace** | done | sessions on a directory, edits as diffs, a recorded runner, named checks (see §2) |
| M32 | **Experimental Mode** | done | declared commands and parameters, real runs, a comparison that names what it could not rank (see §2.3) |
| M33 | **Play Mode** | done | three small games the rules referee, and simulations that replay from their parameters (see §2.4) |
| M34 | **Voice and media** | **partial** | media measured from its own bytes, transcripts with provenance, speech refused by name - no microphone and no speech model exist here (see §3.4) |
| M35 | Dataset preparation | not built | collect, clean, split, version a corpus |
| M36 | Training and model modification | not built | LoRA/fine-tune — no weights or GPU reachable here |
| M37 | Remote compute | not built | hand work to another machine, portably |
| M38 | Blender and 3D workflows | not built | scene scripting through the tool layer |
| M39 | Automations and scheduled tasks | not built | triggers, watches, recurring work |
| M40 | Hardening and release | not built | packaging, upgrade path, audits |

## 2. Modes: same shell, different tools

Every row is a real page in the GUI. "Controls" are what you can press; "tools behind them"
are the application calls; "status" is what works today.

| Mode | What it is for | Controls you get | Tools behind them | Status |
|------|----------------|------------------|-------------------|--------|
| **Chat** | talk to the local model, one turn at a time | conversation list, composer (Ctrl+Enter), model chip, warnings | `ChatService.send` → router → provider; each turn writes a `chat` task | **works** (refuses clearly when no model is reachable) |
| **Research** | turn a question into a sourced report | question, where to look (local / mixed / web), seed URLs, own subquestions, no-model switch, run list, report, sources table, verification, **mark complete / reopen** | `ResearchRunner` → plan (model or rules), reads local docs + supplied URLs through `net.fetch`, hashes what it read, drops unverifiable quotes, computes coverage, re-checks every citation | **works within its scope** — it does not search the web or run experiments (§3.1) |
| **Learning** | learn a topic with a schedule | goals + criteria, add item (question, answer key, hint ladder), next-up with `why`, one hint per click, answer form, item/schedule table, sessions, "propose items", "start a review" | `LearningService` → exact/self grading, SM-2-lite schedule, hint gating, sessions as tasks | **works within its scope** — no model grading, no media (§3.2) |
| Search | find anything this home knows | query, files toggle, per-source notes | `SearchService` across conversations, memory, tasks, workflows, projects, artifacts, tools, files | works |
| Tasks | see what ran and reproduce it | status filter, timeline, artifacts, reproduction | `TaskManager` | works |
| Jobs | run durable queued work | queue stats, pause/resume/cancel/retry, "run one queued job" | `JobManager` + `JobRunner` | works |
| Access | decide what Archx may do | pending approvals, approve/deny, grants, revoke, capability list | `PermissionManager` | works |
| Memory | what Archx keeps about you | kind, category, title, content, stored list | `MemoryManager` (duplicate check included) | works |
| Models | which models can run here | catalogue with the reason each cannot, **Connect Gemini** (name, model id, key *reference*), `test chat` per model, and the four-rung consent ladder with the button that climbs each rung | `ModelManager` + `runtime_availability` + `Workspace.assert_remote_allowed` + `GeminiChatRuntime` | works |
| Status | what this home is | counts, schema, blocked items and the exact next command | `workspace.info()` | works |
| **Code** | edit, run and test a directory | session list + open form, file path, read/save/delete, command box, "run the test check", diff, the ledger of every run, close | `CodingWorkspace` → `fs.read`/`fs.write`/`fs.delete`/`shell.run` through `ToolManager`, so every action is a grant or an approval; edits land as diffs on the session's task | **works** — see §2.2 |
| **Experiments** | run a declared command, keep the numbers, compare runs | experiment list + declare form (name, command, `{params}`, metrics source), run card with per-parameter overrides and a timeout, run table with the metric column that says *why* a run has none, compare card, close/reopen | `ExperimentService` → `shell.run` + `fs.read` through `ToolManager`; every run is a task with its log as an artifact, and metrics are rows | **works** — see §2.3 |
| Play / Voice | **planned** | — | — | **not built**; no button pretends otherwise |

The header of every mode shows the tools *that mode* has, from live data — `net.fetch:
not granted` in Research, `model: none usable` in Chat, `grading: exact or self` in
Learning. That strip is the difference between the modes made visible.

### 2.1 The modes that are asked for but not built

The remaining milestones are modes, so they belong in the same inventory - with the work they
were asked to do, and no button pretending they exist. Nothing below has code today.

| # | Mode as asked | What it was asked to do | What exists to build it on |
|---|---------------|-------------------------|----------------------------|
| M35 | Dataset preparation | collect, clean, split and version a corpus | versions, artifacts, tool roots, search |
| M36 | Training and model modification | LoRA / fine-tune a model | none here: no weights and no GPU are reachable |
| M37 | Remote compute | hand work to another machine portably | HTTP runtime, jobs, providers, consent records |
| M38 | Blender and 3D workflows | script scenes through the tool layer | tools, jobs, artifacts |
| M39 | Automations and scheduled tasks | triggers, watches, recurring work | scheduler, jobs, workflows |
| M40 | Hardening and release | packaging, upgrade path, audits | migrations, backups, `doctor`, this acceptance corpus |

Each of these follows the rule the built modes already follow: a mode is a shell plus a set of
tools, and if the tools are not there the mode is not drawn. That is why the list above is
prose in a document rather than ten greyed-out entries in the sidebar.

### 2.2 The Coding workspace, and what it is careful about

The mode is deliberately small: one directory, one file at a time, one command at a time. It is
an editor and a console, not an IDE, because the interesting part of the milestone is not the
text box - it is the two rules underneath it.

**Every action is a tool call.** Reading a file is `fs.read`, saving one is `fs.write`, running
something is `shell.run`. There is no private filesystem path for the editor, so the panel cannot
do anything `archx-agent tools run` could not, and a refusal is the same refusal the CLI gets -
including the approval id. Writing a file you may not read is allowed and says so in the diff
rather than raising a second approval request for the read.

**The record outlives the process.** A session is a row with a task; an edit is a row with a
unified diff, the checksums either side of it, and an artifact attached to the task; a command is
a row with the argv that ran, the directory, the exit code, the duration and the output. Refusals
are rows too. That is what makes `code diff`, `code rerun` and `tasks reproduce` possible on work
that happened hours ago, and it is why the session's task is marked *manual*: the user works in a
session across many commands, so the process exiting is not the work ending.

What it does **not** do: no multi-file refactoring, no language server, no automatic fixing, no
watching for changes. The checks are whatever the project declares in `archx.checks.json` - the
app runs them and records them; it does not decide what "tested" means for your project.

### 2.3 The Experiments workspace, and the one rule under it

An experiment is a declaration - a command, its parameters, and where the numbers come from -
and a run is a row that says what actually happened. The rule that shapes the whole mode is:

**a metric is a metric only if the experiment said where it comes from.**

So the metrics source is declared when the experiment is created (`none`, the last line of stdout
as JSON, or a JSON file the run writes), and the runner reads *only* that. When the source is
missing, malformed, or not numeric, the run is stored with a sentence saying so and **no** metric
rows; `experiment compare` then lists those runs by id with the reason instead of dropping them.
A table that treats "no answer" as zero is the failure this mode is built to make impossible.

The parameters get the same treatment. A substituted value has to be a single shell-safe token,
and an undeclared placeholder - or a declared parameter the command never uses - is refused by
name *before* anything runs. Nothing is quoted behind your back, because quoting a value changes
the command you meant.

Everything else follows the pattern the Coding workspace set: each run goes through `shell.run`
under the permission centre (no grant is exit 4 with the approval id, and the refusal is recorded
as a run), each run is a task with its output kept as an artifact, and the numbers live in
`experiment_metrics` so "which run was best" is a query and not a re-parse.

What it does **not** do: no grid sweeps in the runner (`--set` is one run; a sweep is a loop over
`experiment run`), no plotting (that is M41's job, and a chart drawn from these rows cannot
disagree with the table), and no model asked to interpret a run.

### 2.4 Play Mode, and why a game is worth having

A game is the smallest honest test of agency there is: the rules are public, the state is small, and
"did it play legally" is answerable without an opinion. Three games live in
`application/games.py` as pure rules - tic-tac-toe, connect four and nim - and everything above
them (the CLI, the page, the engine) is a caller.

The rules are the only authority on legality. A mover proposes a string and `apply` answers with a
new state or a reason; the built-in engine chooses from `legal_moves`, so it cannot produce an
illegal move by construction rather than by review. A refused move is **written down** with
`legal = 0` and the reason, and the board does not move - a log of only the successful moves cannot
show you that the rules held, which is the whole reason to keep one.

Simulations are the second half: Conway's life under a named rule (`B3/S23`), seeded from a number,
with the population series and a sha256 of the final grid recorded. `play replay` recomputes from
the parameters alone and says whether the hash still matches, so a record can be checked rather than
believed. A doctored hash fails its own replay - that is a test, not a promise.

What it does **not** claim: that the engine is strong (connect four is two plies; tic-tac-toe is
perfect and draws against itself), that a model plays *well* (nothing here grades strategy), or that
a simulation proves anything. `docs/PLAY.md` has the details and the tables.

### 2.5 Voice and media, and what a machine without ears can still do

Three things are true on any machine, and they are what this mode builds: what a file *is* can be
measured from its own bytes; who wrote a transcript can be recorded; and what cannot be heard can
be said out loud. So `voice probe` parses PNG, JPEG, GIF and WAV headers by hand, keeps the file
name as a *claim* beside the measurement (a `.jpg` that is really a PNG is stored as a PNG and
counted as mislabelled), and refuses anything it cannot measure with the bytes it began with.

Asking it to hear or speak walks a chain - the switch, the model setting, the registry, the model's
claim, the runtime's readiness - and reports *every* missing link, in order, then writes the
attempt to `voice_attempts`. The chain is computed from the workspace, so the reason changes when
the workspace does. The last link is always the same: no adapter in this build can transcribe or
synthesise, and a registered model is not enough.

The only transcript it can store is one a person typed, and that is a `CHECK (source IN ('human'))`
in the schema rather than a rule the service happens to enforce.

What it does **not** claim: that it can recognise speech, synthesise it, caption an image or read
text out of one. `docs/VOICE.md` has the tables, the formats and the refusals.

## 3. What "done" does not mean (the honest gaps)

### 3.1 Research Mode is marked `partial`, not done

What it does: given a question and either local documents or a list of URLs you paste, it
plans subquestions, reads those pages through the `net.fetch` capability (approval required),
records every source including the ones that failed, hashes the text, keeps only quotes that
appear in the excerpt, demotes uncited model prose, computes coverage, writes a report with
`[S<n>]` citations, and can re-verify each citation.

What it does **not** do, and what that means for "let the AI search":

* **No web search.** There is no search engine, no result ranking, no crawl. "Web" mode means
  "these URLs I was given". The page says so in the form, and a web run with no URLs is a 400.
* **No browsing loop.** It does not follow links, does not decide to read a second page, does
  not iterate on a hypothesis.
* **No experiments.** It cannot run a command, measure a result and write it up. That is M32's
  job; the pieces it would sit on (jobs, tools, tasks, artifacts) exist and are tested.
* **No chat in Research.** The mode is a form, not a conversation. "Ask a follow-up about this
  report" is not built.
* **Completion is yours, not the runner's.** A run can be marked done (`research close`, or
  *mark complete* in the page) and reopened; that records your judgement. It is not a claim
  that the question was answered, and coverage never closes anything by itself.

Closing this is a milestone, not a patch: a search provider behind the permission centre (or
an MCP tool), a bounded browse loop with a per-run page budget, and a chat affordance that
carries the run as context. Recorded in `GAPS.md`; not pretended in the UI.

### 3.2 Learning Mode is marked `partial`, not done

What it does: goals with criteria, items with an optional answer key and an ordered hint
ladder, hints refused before the first attempt, exact/self grading that records which one
fired, SM-2-lite scheduling that explains every interval, sessions recorded as tasks, plans
that name their author, and a report.

What it does **not** do: no model marks prose, no media items (images, audio), no multiple
choice, no exam mode, no cross-goal curriculum, no per-learner profile. The GUI adds items and
answers them; deleting stays a CLI act.

### 3.3 The GUI is a client, not a product surface for everything

Fourteen panels, all wired, nothing decorative. The shell is one page with a sidebar, a top bar
carrying each mode's live tool chips, three themes and a chat transcript with markdown,
copy buttons and confirmations for anything that cannot be undone. Workflow authoring, streaming tokens, files, a
multi-user story and TLS are not there; they are listed in `GAPS.md` and `docs/GUI.md` rather
than implied by a greyed-out button.

### 3.4 Voice is marked `partial`, not done

The milestone name is "voice and multimodal foundation", and the foundation is what exists:
measurement, provenance, and a refusal that names the missing piece. Speech recognition, speech
synthesis, video and OCR are not implemented in any form - not stubbed, not simulated, not
"coming soon". This machine has no microphone and no speech weights, and building an adapter for
weights nobody can run would be a claim this repository could not verify.

## 4. Where this leaves the roadmap

Built: M01–M34 (with the three honest `partial`s above), plus the Research completion model
(§3.1). Next: **M35 Dataset preparation**, which needs no hardware this machine lacks. The Research gaps in §3.1
remain the most valuable repair, and they no longer have an excuse: the runner and the record
they needed now exist in the coding workspace, which can be reused rather than invented.

If a mode is missing from the sidebar, it is because the code is missing — not because the button
was hidden.
