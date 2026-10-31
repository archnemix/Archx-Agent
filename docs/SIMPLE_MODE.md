# Simple Mode and unified search (M27)

Two features with one purpose: a person who does not want to learn the CLI should be able
to ask a question and get an honest answer, and a person who *does* use the CLI should never
have to guess which of nine places something was written down.

Neither feature is a second application. Simple Mode is a **front door**: every intent is
executed by the machinery that already exists (chat, memory, search, workflows,
permissions). Search is a **lens**: it reads the managers that own the data instead of
copying them into an index.

```
                       archx-agent simple ask "where did I write about database locks"
                                         │
                    application/simple.py│detect_intent()  -> (intent, why)
                                         ▼
        chat ─────────────► ws.chat.send()            (M16/M19/M21 path)
        search / recall ──► ws.search.search()        (application/search.py)
        remember ─────────► ws.memory.add()           (M17 path, dedupe preserved)
        status ───────────► ws.router.route / memory.stats / tasks.stats / jobs.stats
        workflow ─────────► ws.workflows.create + ws.agent.run   (M25 + M22 permissions)
                                         │
                                         ▼
                       SimpleResult(intent, why, headline, detail, next_step, data)
```

## Unified search

`SearchService.search(query, *, kinds=, limit=20, per_source=10, project_id=,
conversation_id=, include_files=)` returns one ranked `SearchReport`.

**Sources.** Eight, each mapped to the manager that owns it:

| kind | source | matched on |
|------|--------|-----------|
| `memory` | `MemoryManager.search` | title + content, kind/category matter for weight |
| `conversation` | `ConversationManager.search` | title + message text |
| `task` | `TaskManager.search` (new in M27) | title + type + status |
| `workflow` | `WorkflowsManager.search` (new in M27) | name + goal + summary |
| `project` | `ProjectManager` | name + description |
| `artifact` | `TaskManager.artifacts` | path + kind |
| `file` | the filesystem under `ws.tool_roots()` | path + content, line-numbered |
| `tool` | `ToolRegistry` | name + summary + capability |

**Scoring is one function, applied to every source** (`score_text`), because a ranking you
cannot explain is a ranking you cannot debug:

* terms: query words of two or more characters, deduplicated, at most eight, longest first;
* `haystack = title + "\n" + text`, so a title match counts as content;
* `coverage` = the fraction of terms present; full coverage scores at least `1.0`;
* phrase bonus: the exact query (three or more characters) appearing verbatim adds `0.5`;
* title bonus: any term in the title adds `0.75`;
* ties break on `KIND_WEIGHT` (`memory` 6, `conversation` 5, `task` 4, `workflow`/`artifact`
  3, `file` 2, `project`/`tool` 1), then alphabetically.

`KIND_WEIGHT` breaks ties *between different kinds of the same string* — a memory you wrote
deliberately outranks a file that happens to contain the word — and never overrides a
better score.

**A broken source degrades the report; it does not break the search.** Each source method
returns `(hits, note, consumed)` where `note = {"degraded": bool, "reason": str}`. The
memory source reports keyword-only results when no embedding index is configured; the file
source reports truncation at `search.max_files`. Those notes are surfaced as
`report.degraded` and printed. A source that raises is caught, recorded as degraded with the
error, and the other sources still answer.

**Files are read defensively.** Only inside `ws.tool_roots()` (the configured file-tool roots, not an OS process sandbox), never
dot-directories, never `SKIP_DIRS` (`node_modules`, `.git`, `__pycache__`, `dist`, …), never a
symlink that escapes, never a file larger than `search.max_file_bytes` (256 KiB), never more
than `search.max_files` (400), and never a file whose first block contains a NUL byte. Every
skip is counted, not silently dropped: `report.skipped` names why a whole kind was skipped
and `report.degraded` names a partial scan.

**Search never writes.** Not a row, not a trace event, not a "last searched" timestamp. That
is a test (`test_search_does_not_write_anything`) rather than a claim, because a read path
that writes is a read path that can fail the way writes fail.

## Simple Mode

**Intents are a closed set**: `chat`, `search`, `recall`, `remember`, `status`, `workflow`,
`help` (plus `quit` for the REPL). `detect_intent` returns `(intent, why)` — the second value
is a plain-language sentence that the CLI prints under every answer. There is no "confidence
score" because there is nothing to hide behind: the rule that matched is the reason given.

| you type | intent | what runs |
|----------|--------|-----------|
| `where did I write about X` / `find X` / `do we have anything about X` | search | `SearchService` over every source |
| `recall X` / `what do you know about X` | recall | memory only, using the local embedding **and** keyword path |
| `remember that X` / `note that X` / `always …` / `from now on …` | remember | `MemoryManager.add` as `permanent`, category `preference` or `fact`, dedupe intact |
| `status` / `what's running` / `what is pending` | status | router + memory + tasks + jobs, read only |
| `run template NAME k=v` | workflow | `WorkflowsManager.create` + `AgentRunner.run` |
| `/help`, or an unknown slash command | help | the six plain-language capabilities |
| anything else | chat | `ChatService.send`, one conversation per session |

Slash commands (`/search`, `/find`, `/remember`, `/note`, `/recall`, `/status`, `/help`,
`/chat`, `/ask`, `/quit`, `/exit`) are explicit overrides, so a person who knows what they
want does not have to phrase it naturally.

**The four refusals, and why each one is a *result* rather than an exception:**

1. *No model.* Chat returns "I have no model to answer with" plus the `models add-http`
   command. The process exits `0`: the question was understood, the answer was unavailable.
2. *A permission.* A workflow step that needs `fs.read` stops **before** the step runs and
   shows `archx-agent approvals approve ap_…`. Exit code `4`. No grant is created — the test
   asserts the grant count is unchanged after the refusal.
3. *A checkpoint.* `run template check-and-report` needs `--approve`; Simple Mode prints that
   command instead of approving it.
4. *A model step with no model.* The workflow fails honestly ("it has a model step and no
   model is configured") instead of raising a traceback out of the CLI.

**`remember` is not a note-taking side channel.** It writes a real `permanent` memory with
`provenance.mode = "simple"`, the same duplicate detection as `memory add` (a second attempt
is reported as "I did not store that", not silently swallowed) and the same trace events, so
it is visible to `memory list`, to semantic recall, and to the unified search that Simple
Mode itself uses.

**The REPL** (`archx-agent simple` with no subcommand) keeps one `conversation_id` across
turns, prints the reason under each answer, keeps going after a refusal, and exits on
`/quit`, `/exit`, EOF or Ctrl-C. `--json` is refused here (exit 2) because a stream of JSON
documents is not a stream of one document — use `simple ask --json` in scripts.

## Configuration

| key | default | meaning |
|-----|---------|---------|
| `search.default_limit` | 10 | merged hits returned when `--limit` is not given |
| `search.per_source` | 10 | cap per source before merging |
| `search.include_files` | true | file content search on/off (also `--no-files`) |
| `search.max_files` | 400 | stop scanning after this many candidate files |
| `search.max_file_bytes` | 262144 | skip larger files, counted in `report.degraded` |

## What this deliberately does not do

* It does not create an index, a cache or a `search` table. Every query reads the managers.
  At the corpus sizes this app produces (thousands of rows, hundreds of files) that is
  faster than maintaining a second copy and it cannot go stale.
* It does not use embeddings for files or tasks. Only memory has a vector path today; the
  report says `keyword-only` rather than pretending otherwise.
* It does not learn from clicks. There is no ranking feedback loop, so there is nothing to
  leak and nothing to tune.
* It does not let Simple Mode's friendliness widen authority. The only way a workflow gets a
  capability is the user running `approvals approve`.
