# Archx Agent

A modular, **local-first** AI operating environment: conversation, persistent memory,
research, coding, experiments, learning, play, media, model management, datasets,
training, remote compute, automation and extensible tool execution under one set of
storage, settings, permissions, routing, tracing and task history.

> **Status: work in progress.** Milestones are built and verified in order; see
> [PROGRESS.md](PROGRESS.md) for exactly what works today and [GAPS.md](GAPS.md) for
> what does not. Nothing is claimed as working without a recorded verification.

## Install (development)

```bash
python -m venv .venv
./.venv/bin/pip install -e .
./.venv/bin/pip install pytest            # for the test suite
./.venv/bin/archx-agent init
```

or, in one step: `./scripts/bootstrap.sh`.

Python 3.11+ is required. The core has **no mandatory third-party dependencies**;
model runtimes and media tooling are opt-in extras.

## Quickstart

```bash
# 1. point it at a model
#    a) local GGUF files (needs `pip install llama-cpp-python`)
archx-agent models discover --dir ~/models
#    b) any OpenAI-compatible HTTP endpoint (llama.cpp server, Ollama, vLLM, LM Studio)
archx-agent models add-http --name local-llama --base-url http://127.0.0.1:8080 --model smollm2
#    c) an explicitly simulated runtime, for exploring the app with no model at all
archx-agent models add-scripted --name simulated-demo

# 2. remote providers are opt-in: register, confirm the privacy terms, consent
archx-agent providers add cloud --template openai --auth-ref secret://env/OPENAI_API_KEY
archx-agent providers privacy          # shows what is known, and where it came from
archx-agent providers confirm cloud --data-leaves-device yes
archx-agent providers consent cloud
archx-agent config set model.local_only false   # deliberately required for remote calls

# 3. talk
archx-agent chat --message "Summarise what you know about this project"
archx-agent chat                       # interactive

# 4. memory
archx-agent memory add --kind permanent --category preference \
  --title "Metric units" --content "Always use metric units" --tags style
archx-agent memory search metric
archx-agent memory policy              # documented policy for all six memory systems

# 5. tools need a grant: the first attempt queues an approval, then run it again
archx-agent tools run fs.write --arg path=notes.md --arg content=hello
archx-agent approvals list
archx-agent approvals approve ap_...
archx-agent tools run fs.write --arg path=notes.md --arg content=hello
archx-agent tools runs                  # every attempt, denials included

# 5b. MCP servers and extensions go through the same checks
archx-agent mcp add fixture --command python3 --arg path/to/server.py
archx-agent mcp sync fixture            # discovers; registers nothing until trusted+enabled
archx-agent mcp trust fixture && archx-agent mcp enable fixture
archx-agent mcp sync fixture && archx-agent mcp call fixture echo --arg text=hi

# 6. what did I do, and can I do it again?
archx-agent tasks list                      # every turn and tool task, newest first
archx-agent tasks show <task>                # timeline, tool runs, artifacts
archx-agent versions list artifact <path>    # content history with diffs and restores
archx-agent tasks reproduce <task> --record  # exact / partial / impossible, with reasons

# 7. let the agent carry out a plan (a model's plan needs approval)
archx-agent agent run-file plan.json          # steps you wrote
archx-agent agent plan "summarise the notes"  # a model proposes; nothing runs yet
archx-agent agent show wf_... && archx-agent agent run wf_... --approve

# 8. long work goes through the durable queue
archx-agent jobs submit command "sleep 30" --timeout 5   # a hard deadline, not a hint
archx-agent jobs submit workflow wf_... --timeout 600
archx-agent jobs run                                     # drain (exit 3 = work remains)
archx-agent jobs pause jb_... && archx-agent jobs resume jb_...
archx-agent jobs recover                                 # after a crash: requeue, do not guess

# 9. one search, and a front door that explains itself
archx-agent search "database locks"          # conversations, memory, tasks, workflows, files
archx-agent search kafka --kind memory --no-files
archx-agent simple ask "where did I write about database locks"
archx-agent simple ask "remember that the staging key lives in vault"
archx-agent simple status
archx-agent simple                            # a small loop: /help for what it understands

# 10. research a question: a plan, real sources, citations, and what it could not establish
archx-agent research run "how does sqlite locking work"
archx-agent research run "how does sqlite locking work" --no-model   # extractive, no model calls
archx-agent research run "..." --mode web --url https://example.com/page   # needs a net.fetch grant
archx-agent research sources rs_...     # what was read, and what could not be
archx-agent research verify rs_...      # exit 3 if a citation does not resolve

# 11. the same app in a browser: a local GUI with a token, no second implementation
archx-agent gui serve                 # prints http://127.0.0.1:8765/?token=...
archx-agent gui serve --port 0 --open # any free port, and open it
archx-agent gui routes                # every endpoint it serves

# 12. inspect everything that happened
archx-agent trace list --limit 20
archx-agent db check
```

Simple Mode never widens your authority: when a request needs a permission or an approval,
it prints the exact `archx-agent approvals approve ...` command and stops (exit `4`).

`--json` is accepted before or after the subcommand. `--home DIR` keeps a separate
workspace (useful for experiments and tests).

### The simulated runtime is not a model

`--allow-simulated` / `models add-scripted` enables a **test double** that returns
canned text. Every surface labels it (`[SIMULATED]`), traces record it, and it is
disabled unless you ask for it. It exists so the application can be exercised without
downloading weights; it never stands in for a real model in acceptance evidence.

## What works today

| Area | State |
|------|-------|
| Layered architecture + enforced import matrix | verified |
| Config (defaults → file → env → CLI), validated, with provenance | verified |
| SQLite storage: serialised writer, journal, exactly-once replay, backpressure | verified (incl. SIGKILL crash test) |
| Backup / verify / preview-restore / restore-aside / retention | verified |
| Structured trace: capture levels, causal tree, redaction, export, retention | verified |
| Conversations: create, search, rename, soft/hard delete, export, restart-safe ordering | verified |
| Six memory systems with scope, provenance, history, dedupe, retention, artifacts | verified (M17) |
| Embeddings: float32 vectors with model identity, states, hybrid retrieval, eval harness | verified (M18) |
| Context strategies: oldest-first, summarise, AI-select, manual, AI-proposed | verified (M19) |
| Model catalogue: facts vs claims vs user metadata, discovery, verification states | verified |
| Providers: local/cloud catalogue, privacy metadata, confirmations, consent, availability, quotas, usage | verified (M20) |
| Capability-safe routing: evidence-backed capability states, eligibility, probes, visible fallback | verified (M21) |
| Tools + permissions: declared capabilities, scoped grants, approvals, sandboxed fs/shell, run audit | verified (M22) |
| MCP client (stdio + HTTP) and optional server; extensions with a trust boundary | verified (M23) |
| Task history, content versions with diffs/restore, and evidence-based reproduction records | verified (M24) |
| Agent workflows: user-written plans, model-proposed plans behind approval, subagents, budgets | verified (M25) |
| Durable job queue: priorities, concurrency with resource admission, hard deadlines, pause/resume, crash recovery | verified (M26) |
| Unified search across conversations, memory, tasks, workflows, projects, artifacts, tools and files | verified (M27) |
| Simple Mode: plain-language intents with a stated reason, honest refusals and printed next steps | verified (M27) |
| Researcher Mode: validated plans, real sources, checked citations, coverage and limitations | verified (M28) |
| Local GUI: token-authenticated, CSRF-protected, every panel wired to the real services | verified (M29) |
| Learning Mode: goals with criteria, hint ladder, SM-2-lite schedule, exact/self grading | verified (M30) |
| Coding workspace: sessions on a directory, edits as diffs, a recorded runner, named checks | verified (M31) |
| Experimental Mode: declared commands and parameters, metrics only from the declared source, honest comparison | verified (M32) |
| Play Mode: three games the rules referee, a log that keeps the refusals, simulations that replay from their parameters | verified (M33) |
| Voice and media: measured from the bytes (PNG/JPEG/GIF/WAV), transcripts that name their author, refusals that name the missing link | verified, scoped (M34 - no speech model exists here) |
| `net.fetch` as a capability: http(s) only, private addresses refused, redirects re-checked | verified (M28) |
| Provider runtime boundary: llama.cpp in-process, OpenAI-compatible HTTP, tested error classification | verified for HTTP; llama.cpp needs the optional dependency and a model file |
| CLI | verified end-to-end |
| Datasets, training, remote compute, Blender, automations | **not built yet** (M35–M40, see PLAN.md) |

## Design principles (enforced, not aspirational)

1. **Local-first, not local-only.** Cloud and remote workers are optional and explicit.
2. **Modular.** Replaceable providers, storage, executors and interfaces.
3. **Real capabilities, not labels.** A capability is only routed on when it is verified.
4. **Explicit authority, safe defaults.** Nothing grants itself permission.
5. **Inspectable and reproducible.** Every consequential event is traced.
6. **Preserve source data.** Compaction never deletes originals.
7. **Demonstrable progress.** A milestone is done only when it works in the app.

## Documentation

* [ARCHITECTURE.md](ARCHITECTURE.md) - layers, invariants, data model, extension points
* [PLAN.md](PLAN.md) - milestone scope and status
* [PROGRESS.md](PROGRESS.md) - what is verified, how, and what is next
* [GAPS.md](GAPS.md) - known limitations, honestly stated
* [THINKING.md](THINKING.md) - decision log with reasons
* [CHANGELOG.md](CHANGELOG.md)
* [scripts/seed_demo.sh](scripts/seed_demo.sh) - rebuild the demo home the live preview serves (after `bootstrap.sh`)
* [docs/MODES.md](docs/MODES.md) - every mode and milestone, what each is for, and what is honestly built
* [docs/GUI.md](docs/GUI.md) - the local web GUI, its layout, themes, security model and every endpoint
* [docs/LEARNING.md](docs/LEARNING.md) - goals, items, hint ladders, grading and the schedule
* [docs/RESEARCH.md](docs/RESEARCH.md) - research runs, evidence rules, citations, `net.fetch` limits
* [docs/CODING.md](docs/CODING.md) - coding sessions, edits as diffs, the recorded runner, named checks
* [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md) - declared commands and parameters, honest metrics, comparison
* [docs/PLAY.md](docs/PLAY.md) - the rules as the only authority, refused moves kept, simulations that replay
* [docs/VOICE.md](docs/VOICE.md) - media measured from the bytes, transcripts that name their author, speech refused by name
* [docs/SIMPLE_MODE.md](docs/SIMPLE_MODE.md) - unified search, its ranking, and every Simple Mode intent
* [docs/AGENTS.md](docs/AGENTS.md) - workflow definitions, step kinds, approval gates and budgets
* [docs/SCHEDULER.md](docs/SCHEDULER.md) - durable jobs, deadlines, concurrency, pause/resume, crash recovery
* [docs/TASKS.md](docs/TASKS.md) - task history, content versions, and what "reproducible" means
* [docs/MCP.md](docs/MCP.md) - MCP client/server, transports, extensions and their trust boundary
* [docs/TOOLS.md](docs/TOOLS.md) - tool registry, capabilities, grants, approvals, sandbox
* [docs/ROUTING.md](docs/ROUTING.md) - capability states, eligibility, probes, fallback
* [docs/PROVIDERS.md](docs/PROVIDERS.md) - provider catalogue, privacy metadata, consent gates
* [docs/RETRIEVAL.md](docs/RETRIEVAL.md) - embedding design, scale thresholds, model research
* [docs/RETRIEVAL_EVAL.md](docs/RETRIEVAL_EVAL.md) - measured retrieval quality
* [docs/VERIFICATION.md](docs/VERIFICATION.md) - environment verification and acceptance transcripts

## Tests

```bash
./.venv/bin/python -m pytest -q
```

Unit, integration, crash/recovery, multi-process and end-to-end CLI tests. Tests that
cannot run are reported as **skipped**, never as passed.

## License

MIT.
