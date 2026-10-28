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
| M32 | Experimental Mode | not built | run experiments, compare runs, keep the record |
| M33 | Play Mode | not built | games, simulations, sandboxed tinkering |
| M34 | Voice and multimodal | not built | speech in/out, images, audio — no hardware here |
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
| Experimental / Play / Voice | **planned** | — | — | **not built**; no button pretends otherwise |

The header of every mode shows the tools *that mode* has, from live data — `net.fetch:
not granted` in Research, `model: none usable` in Chat, `grading: exact or self` in
Learning. That strip is the difference between the modes made visible.

### 2.1 The modes that are asked for but not built

The remaining milestones are modes, so they belong in the same inventory - with the work they
were asked to do, and no button pretending they exist. Nothing below has code today.

| # | Mode as asked | What it was asked to do | What exists to build it on |
|---|---------------|-------------------------|----------------------------|
| M32 | Experimental Mode | run experiments, keep the parameters and results, compare runs | jobs, tasks, artifacts, versions, research sources, and now the M31 runner |
| M33 | Play Mode | games, simulations and sandboxed tinkering | tools + permission centre (nothing may escape a grant) |
| M34 | Voice and multimodal | speech in and out, images, audio | none in this build: no microphone, no weights, no GPU |
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

Eleven panels, all wired, nothing decorative. The shell is one page with a sidebar, a top bar
carrying each mode's live tool chips, three themes and a chat transcript with markdown,
copy buttons and confirmations for anything that cannot be undone. Workflow authoring, streaming tokens, files, a
multi-user story and TLS are not there; they are listed in `GAPS.md` and `docs/GUI.md` rather
than implied by a greyed-out button.

## 4. Where this leaves the roadmap

Built: M01–M31 (with the two honest `partial`s above), plus the Research completion model
(§3.1). Next: **M32 Experimental Mode**, then M33 Play, M34 Voice. The Research gaps in §3.1
remain the most valuable repair, and they no longer have an excuse: the runner and the record
they needed now exist in the coding workspace, which can be reused rather than invented.

If a mode is missing from the sidebar, it is because the code is missing — not because the button
was hidden.
