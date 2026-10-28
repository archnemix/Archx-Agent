# The local web GUI (M29, extended in M30)

```bash
archx-agent gui serve                 # http://127.0.0.1:8765/?token=…
archx-agent gui serve --port 0        # any free port
archx-agent gui serve --open          # and open a browser
archx-agent gui routes                # every endpoint, method and purpose
```

The GUI is a **client of the application layer**. Every panel calls the same managers, the
same chat service, the same permission centre and the same research runner as the CLI. It
adds no tables, no second index and no second permission path: `gui serve` opens one
workspace and serves it.

That is the whole design argument. A "friendly" second implementation is how products end up
with two truths about what happened, and how a convenience screen becomes a way around the
approval centre.

## The reply arrives while it is being written

`POST /api/chat` returns a finished reply; that is right for a script and wrong for a person
watching a 135M model think. `POST /api/chat/stream` runs **the same turn** - same task record,
same stored messages - and writes each piece as server-sent events:

```text
event: chunk
data: {"text": "[SIMULATED] "}

event: chunk
data: {"text": "I received 3 words. "}

event: done
data: {"conversation_id": "conv_...", "task": {...}, "text": "...", "completion_tokens": 9, ...}
```

Three decisions worth naming:

* **no `Content-Length`.** A length means the handler buffers every frame until the end, which
  is the opposite of streaming. The connection is closed to end the stream, so `Connection:
  close` goes with it.
* **the same service, not a second implementation.** `ChatService.send` already takes a
  `stream_callback` (the CLI's `--stream` uses it); the route puts a worker thread behind a queue
  and yields what it produces.
* **a failure still ends the stream**, with an `error` frame - a refused or broken turn must not
  leave the page waiting forever.

The page reads the body with `fetch` + `getReader` rather than `EventSource`, because
`EventSource` cannot POST. When the reply is done, the streamed text is replaced by the recorded
one, so what is on screen is what is in the database. If the browser cannot stream, the page falls
back to the whole-reply endpoint instead of failing.

Verified: `tests/test_gui_stream.py` (8 tests over a real socket: the content type, that chunks
arrive separately and before the `done`, that the turn is recorded like any other, that it needs a
credential, and that a refused turn ends with an `error` frame) and five checks in
`scripts/acceptance_m29.sh`.

## Starting it

The first thing it prints is the access token:

```
Archx GUI on http://127.0.0.1:8765/
  home      /home/you/.archx
  bind      127.0.0.1:8765  (loopback only)
  access token: 4Qm2…            <- this process's only key
  open      http://127.0.0.1:8765/?token=4Qm2…
```

Open the `open` URL. The page takes the token out of the address bar, exchanges it for an
HttpOnly session cookie, and never keeps the token itself.

## What is in it

| Panel | What it does | Where the work happens |
|-------|--------------|------------------------|
| **Status** | counts, schema, what is blocked and the exact command that unblocks it | `workspace.info()`, live manager stats |
| **Chat** | one turn, conversation list, warnings, `simulated` and token counts | `ChatService.send` - the same path as `chat --message` |
| **Research** | run a question, watch coverage, read the report, see the sources *including the ones that failed*, then mark the question done (or reopen it) | `ResearchRunner.run` + `research verify`'s own check |
| **Search** | one query across every source, with `degraded`/`skipped` notes | `SearchService.search` |
| **Tasks** | history, timeline, artifacts, tool runs | `TaskManager` |
| **Jobs** | queue, stats, pause/resume/cancel/retry, "run one queued job" | `JobManager` + `JobRunner` |
| **Access** | pending approvals, approve/deny, active grants, revoke, capability list | `PermissionManager` |
| **Memory** | add and list memories (with the duplicate check) | `MemoryManager` |
| **Models** | the catalogue and *why* each model can or cannot run here, a *Connect Gemini* form (the key is a `secret://` reference, never typed in), `test chat` per model, and the **consent ladder** | `ModelManager` + `runtime_availability` + `Workspace.assert_remote_allowed` |
| **Learning** | goals and criteria, add an item, next-up with its `why`, one hint per click (409 before an attempt), answer and see the schedule, sessions, propose items, start a review | `LearningService` - the same path as `learning …` |
| **Code** | a session list, an open form, a path field with read/save/delete, a textarea, a command box, the project's check button, the session patch and the runner's ledger | `CodingWorkspace` → `fs.read`/`fs.write`/`fs.delete`/`shell.run`, so every button is a grant or an approval |
| **Experiments** | declare an experiment (name, command with `{params}`, parameters, metrics source), run it with per-parameter overrides, read the run table - whose metric column says *why* a run has no number - and the comparison with its notes | `ExperimentService` → `shell.run` + `fs.read`; every run is a task with an artifact, and the numbers are rows |
| **Play** | start a game, play it (move box, legal moves as buttons, engine move, engine ×5, resign), read the board as text and the move log *with the refusals and their reasons*; run a simulation and replay its hash | `PlayService` - the same `move`/`engine_move`/`simulate`/`replay` calls the CLI makes |

There are no placeholder controls. If a panel would need something this build does not have,
the panel is not drawn: there is no "Settings" tab that pretends, no disabled "Train" button,
and no fake progress bar. The one thing a panel does when it cannot act is *say why*, with
the command that would fix it - the same refusals as the CLI, in the same words.

## A demo home to look at

The page is only interesting with something in it. `scripts/seed_demo.sh [home]` builds a
throwaway workspace (`~/.archx-demo` by default) through the ordinary CLI: a scripted model,
one conversation, three memories, a learning goal with an item ladder and two attempts, one
local research run with its sources, and a queued job. It never deletes an existing home and skips whatever is already there, so it is
safe to re-run after a restore.

```bash
./scripts/bootstrap.sh                                   # the venv is not committed
./scripts/seed_demo.sh                                   # ~/.archx-demo
ARCHX_PATHS_HOME=~/.archx-demo ARCHX_ALLOW_SIMULATED=1 \
  ./.venv/bin/archx-agent gui serve --host 0.0.0.0 --allow-remote --token <token>
```

The scripted runtime performs no inference, and every reply it produces says `simulated` in
the page and `[SIMULATED]` in the CLI. That is the point: a preview may be seeded, but it may
not pretend the seed is a model.

## Layout, theme and modes

One shell, three parts: a left **sidebar** (Modes · Work · Control), a **top bar** that names
the current mode and lists the tools that mode actually has, and a **work area**. The sidebar
collapses to a 64px icon rail with the button in its top corner, or by itself under 1100px,
and remembers which you chose; under 760px it becomes a horizontal strip.

| Group | Panels |
|-------|--------|
| **Modes** | Chat (composer, conversations, model chip), Research (question, where to look, seed URLs, report, sources, verification), Learning (goals, items, hints, schedule, sessions) |
| **Work** | Search (one query, nine sources), Code (sessions, edits as diffs, a recorded runner, named checks), Experiments (declared commands, runs, the comparison and its notes), Play (games the rules referee, simulations you can replay), Tasks (timeline, artifacts, reproduction), Jobs (queue, pause/resume/cancel/retry, run one) |
| **Control** | Access (approvals, grants, capabilities), Memory (add/list with the duplicate check), Models (why each one cannot run), Status (counts, schema, what is blocked) |

The tool strip in the top bar is drawn from live data, so it cannot flatter: `model: none
usable` and `net.fetch: not granted` are the app saying what it can do right now. That strip
is also where the modes stop looking identical - Chat spends tokens, Research spends network
grants, Learning spends neither.

**It is built to be used, not just to be looked at.** Chat is a transcript with avatars, a
role line and a per-message copy button that appears on hover (and stays visible on touch);
replies are rendered as markdown - headings, lists, quotes, inline code, fenced blocks with a
language label and a copy button, and tables with copy-as-CSV and save. The empty state offers
four prompts that fill the composer instead of pretending to be buttons that do nothing. A
waiting reply shows three dots, not a percentage. Warnings and refusals are rendered inline
where the action was taken, with the error code. Every list (conversations, research runs,
goals, tasks) is a picker that marks the open record; every long table is a scroll container
with a sticky header; every copy, save, approve, deny, revoke, pause, resume, retry and cancel
button is wired to the endpoint behind it, and a toast confirms what the server said.
The research panel carries one state change that belongs to the user alone: *mark complete*
asks for an optional note and records your judgement without touching the run's own status,
and *reopen* undoes it. The three acts that cannot be undone from the page - denying an approval, revoking a
grant, cancelling a job - open a confirmation dialog that names exactly what will happen,
and `Escape` or a click outside dismisses it.

**Colour is tokenised, and mostly absent.** Four surface levels (`--bg`, `--bg-2`, `--panel`,
`--panel-2/3`), three text levels, and colour reserved for state (`--ok`, `--warn`,
`--danger`). The accent is the text colour itself - white on black, black on white - so the
interface reads like an instrument rather than a dashboard. Three themes ship: **dark**
(default), **light**, and **soft** (warm off-white for daylight); the toggle cycles them, the
first visit follows `prefers-color-scheme`, and the choice is remembered. A theme is a token
swap on `data-theme` and nothing else.

**Keyboard.** `Enter` sends, `Shift+Enter` adds a line, `Ctrl/Cmd+K` jumps to Search and
focuses the query. Every control is a real `<button>`, `<input>` or `<select>` with a visible
focus ring; the sidebar marks the current mode with `aria-current`.

**No build step still holds.** Three files - `index.html`, `style.css`, `app.js` - served from
package data by exact name: no framework, no CDN, no icon font, no inline handler and no
`style=` attribute anywhere (so the CSP stays `'self'` with no `unsafe-inline`; icons are SVG
built with `createElementNS`, the coverage bar is a native `<progress>`, and the composer grows
by `rows`). `tests/test_gui_m29.py` fails if the page uses an id or a class with no rule behind
it, if a mode has no title/tools entry, or if a `-refresh` button has no listener.

## Security model

The GUI is a network listener in a local-first app, so it is treated as one.

**Reachability.** Loopback by default (`gui.host`, `gui.port`). A non-loopback bind requires
`--allow-remote`; without it `gui serve --host 0.0.0.0` exits 2 and explains itself. That
flag is for a container, a preview, or a phone on your own network - and it means the token
is the only boundary between that network and your data.

**Authentication.** A random token per process (`secrets.token_urlsafe`), compared with
`hmac.compare_digest`. Accepted as `?token=`, `Authorization: Bearer`, `X-Archx-Token`, or
exchanged at `POST /api/session` for a cookie that is `HttpOnly; SameSite=Strict;
Max-Age=gui.session_minutes`. The cookie value is an HMAC of the token, not the token, so the
browser never stores the key, and restarting the server invalidates every cookie. Failed
attempts are rate-limited (20/minute by default) with `429`.

**Cross-site writes.** Cookie-authenticated writes must carry `X-Archx-Request: gui`. A page
on another origin cannot set a custom header without a CORS preflight, and this server
answers no preflights (`OPTIONS` → 405) and sends no `Access-Control-Allow-Origin` ever.
Token-header callers (curl, the acceptance script) are exempt because a browser cannot be
tricked into adding that header for them. A request that presents no cookie at all is also
exempt: it has no session to be riding, so the CSRF check does not apply and authentication
answers that request with `401 unauthorized`. The distinction matters because the two errors
send a caller to different places — one is "identify yourself", the other is "add a header".

**Content.** `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src
'self'; img-src 'self' data:; connect-src 'self'; form-action 'none'; base-uri 'none';
frame-ancestors *`. No CDN, no inline script, no inline handler, no `eval`. The page may be
framed (so a desktop preview can host it); the scripts still cannot talk to anything but this
origin. `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. The `Server`
header carries the app version and not the interpreter.

**Paths.** Assets are served by exact file name from `interfaces/gui/assets/`, never by path,
so `../server.py`, `%2e%2e%2f` and a dotfile are all 404. Nothing else on disk is reachable:
the GUI has no "open this file" endpoint.

**Bodies and errors.** A request body over `gui.max_body_bytes` is refused with `413`. The
client is mid-upload when the refusal happens, so the server drains a bounded amount of the
body before answering; closing the socket immediately makes the caller see a connection reset
instead of the status, which is indistinguishable from the server crashing. Every failure
becomes JSON (`{"ok": false, "error": {…}}`) with a status that means something; an unexpected
exception is reported as its type and message, never as a traceback.

### Status codes are about whose problem it is

The server's job is to be honest about failure. A missing model, a refused key and a vendor
outage are not the same event, and a caller that has to treat all of them as `500` cannot
tell "my input is wrong" from "retry later" from "the server is broken". The mapping, most
specific first:

| status | code | when |
|--------|------|------|
| 400 | `validation` | a required field is missing, or a value has the wrong type |
| 402 | `quota_exhausted` | the account is out of credit |
| 403 | `consent_required`, `privacy_unknown`, `approval_required`, `auth_denied`, `permission_denied` | the caller may not, or has not yet agreed to, do this |
| 404 | `not_found`, `model_not_found`, `tool_not_found` | the thing does not exist |
| 405 | `method_not_allowed` | the path exists and that verb does not |
| 409 | `conflict`, `model_unavailable` | the state is not ready for this, and waiting or fixing it will change that |
| 413 | `context_overflow` | the input does not fit the model's window |
| 422 | `unsupported_capability` | the model cannot do this at all |
| 429 | `rate_limited` | slow down, this is temporary |
| 502 | `network_failure` | we could not reach the provider |
| 503 | `provider_outage`, `storage_busy` | they are down, or we are momentarily |
| 504 | `tool_timeout` | it took too long |
| 500 | `internal` | genuinely our fault |

Two consequences worth stating plainly:

**The value never gets coerced.** A `message` that arrives as `123`, `{}` or `[]` is a `400`,
not the string `"123"` or a Python dict repr stored as the user's turn. The same holds for
every id field: an identifier that is not a string does not fall through to a database
`ProgrammingError`.

**The server answers JSON for every verb.** `BaseHTTPRequestHandler` returns an HTML `501`
page for any verb it has no `do_*` method for, which would be the only non-JSON response the
GUI can produce and would leak the stdlib's markup to the page. `PATCH`, `TRACE` and a
misspelled verb all get `405` with the usual error envelope.

`GET /api/health` is read-only and public: it answers `GET` and `HEAD` (no body) with
version, uptime and request count, and every other verb with a JSON `405`. It never needed a
token — that is the point of a health check — but it used to accept `POST`, `PUT` and
`DELETE` and answer `200` to each, which made it a misleading thing to probe. The verb check
run before the CSRF check, because there is no write here to protect: `curl -X POST` on the
health path should be told the path does not take that verb, not that a header is missing.

## The API

The page uses only these; so can you.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | version, uptime, request count (public) |
| POST | `/api/session` | exchange the token for a cookie |
| GET | `/api/status` | counts, schema, warnings, what is blocked |
| GET | `/api/models` | catalogue, with why each model can or cannot run, `gates` and `provider_id` |
| GET | `/api/models/{id}` | one model: readiness and the consent ladder |
| POST | `/api/models` | register a Gemini model (`credential_ref` must be `secret://…`; `400 literal_secret` otherwise) |
| POST | `/api/models/{id}/probe`, `/api/models/{id}/provider` | measure one capability by calling it; register this model's endpoint as a provider |
| GET | `/api/providers` | providers with `privacy_known`, `consented`, `blocking_reason` |
| POST | `/api/providers/{id}/privacy`, `/api/providers/{id}/consent` | record what you confirmed; record consent |
| POST | `/api/settings/model.local_only` | open or close cloud routing (written to `config.json`) |
| GET | `/api/conversations`, `/api/conversations/{id}/messages` | history |
| POST | `/api/chat` | one turn (creates a task, like the CLI) |
| GET | `/api/search?q=` | unified search |
| GET/POST | `/api/memory` | list, store |
| GET | `/api/tasks`, `/api/tasks/{id}` | history, then timeline + artifacts |
| GET | `/api/jobs`, POST `/api/jobs/{id}/{pause,resume,cancel,retry}`, POST `/api/jobs/drain` | the queue |
| GET | `/api/approvals`, POST `/api/approvals/{id}/{approve,deny}` | decisions |
| GET | `/api/permissions`, POST `/api/permissions/{id}/revoke` | grants and capabilities |
| GET/POST | `/api/research`, GET `/api/research/{id}`, GET `/api/research/{id}/report` | runs (`?closed=1` / `?closed=0`), sources, verification, the report |
| POST | `/api/research/{id}/{close,reopen}` | mark a question done (with an optional note) or put it back; `409` if it is already in that state |
| GET | `/api/learning`, `/api/learning/goals/{id}` | goals with progress, then items, next-up, sessions |
| POST | `/api/learning/goals`, `/api/learning/goals/{id}/items`, `/api/learning/goals/{id}/{plan,answer,review}`, `/api/learning/items/{id}/hint` | create a goal, add an item, plan, answer, review, reveal one hint |
| GET/POST | `/api/code/sessions` | coding sessions (with their edit/run counts), and the tool roots a session may open on; POST opens one |
| GET | `/api/code/sessions/{id}` | one session: its edits, its runs, the task behind it |
| GET | `/api/code/sessions/{id}/file?path=…`, `/tree?path=…`, `/checks`, `/diff` | read a file, list a directory, the project's declared checks, the session's whole patch |
| POST | `/api/code/sessions/{id}/{read,write,delete,run,test,close}` | the same four tools the CLI uses; `run` needs `shell.run`, `write` needs `fs.write` |
| POST | `/api/code/runs/{id}/rerun` | replay a recorded command |
| GET/POST | `/api/experiments` | experiments (each with its run counts), the tool roots, and POST to declare one |
| GET | `/api/experiments/{id}` | one experiment: its runs, its metric names, its counts |
| POST | `/api/experiments/{id}/run` | run it once with optional `params` and a `timeout` |
| GET | `/api/experiments/{id}/compare?metric=…&minimise=1` | the ranking, the best run, and the notes that name what could not be ranked |
| GET | `/api/experiments/{id}/runs` | the run ledger |
| POST | `/api/experiments/{id}/{close,reopen}` | close it (runs stay readable) or put it back |
| DELETE | `/api/experiments/{id}` | delete it and its runs |
| GET/POST | `/api/play/games` | games (with counts), and POST to start one; `?status=open\|finished\|abandoned` |
| GET | `/api/play/games/{id}` | the board, whose turn it is, the legal moves, the recent log |
| POST | `/api/play/games/{id}/move` | propose a move; always `200`, with `legal: false` and the reason when the rules refuse |
| POST | `/api/play/games/{id}/{engine,auto,resign}` | one engine move, several plies, or abandon the game |
| GET | `/api/play/games/{id}/history` | every move, including the refused ones, with the counts |
| GET/POST | `/api/play/sims` | recorded simulations, and POST to run one |
| GET | `/api/play/sims/{id}` | one simulation: parameters, series, final grid, hash |
| POST | `/api/play/sims/{id}/replay` | recompute from the parameters and compare the hash |
| GET | `/api/play/stats` | games, moves, refusals, simulations |

### The Code panel, and why it is not an IDE

The panel is a session list, an open form, a path field, a read/save/delete row, a textarea, a
command box and two buttons: *run*, and *run the test check*. There is no language server, no
refactoring, no file tree you can drag. That is deliberate: the two things worth building were
the permission boundary and the record, and both of them live below the page.

Nothing in the panel is a capability of its own. Every button is one of four tools -
`fs.read`, `fs.write`, `fs.delete`, `shell.run` - invoked through the same `ToolManager` the CLI
uses, so with no grant the page gets the same `403 approval_required` the terminal gets `exit 4`
for, and the approval it names is in the Access panel. The editor does not read your file to
build a diff when reading is not allowed: it asks the permission centre first, gets "no", and
says the diff shows only the new content. One save is one approval request, not two.

The results are shown, not hidden: the ledger under the editor is the same `code_runs` table
`code runs` prints, and a failed command is an ordinary answer (HTTP 200, `status: failed`,
exit code in the row) because the request to run it succeeded. A refusal is a `403`; a bad field
is a `400`; a closed session is a `400` that says so.

### The Experiments panel, and the column that matters

The panel is a list, a declare form (name, command with `{placeholders}`, parameters as
`n=100, seed=1`, metrics source and path), a run card with one field per declared parameter, a
run table and a compare card. The run table's last column is the point of the panel: it shows the
metrics the experiment declared, or *not read: …* with the reason. There is no zero, because
there was no number.

A run from the page is the same `experiment run` the CLI makes: a `shell.run` call under the
permission centre, a task, an artifact, and rows. A refusal is `403 approval_required` with the
approval in the Access panel; a parameter that would not survive the shell is a `400 validation`
and nothing starts. `compare` never hides a row: the card prints the notes, including the runs it
could not rank and why.

### The Play panel, and the log it refuses to tidy

The panel is a game list, a start form (game and optional seed), a simulation form
(width, height, steps, seed, density), a simulation list, and a detail pane: the board as text,
chips for turn and move count, a move box with the legal moves as buttons, *engine move*,
*engine ×5* and *resign*, then the move log with a `why` column. Selecting a simulation shows its
parameters, its population series, its hash and the final grid, with a *replay and check the hash*
button that prints either `reproduced: …` or `DIFFERENT: stored … but these parameters give …`.

The board is text on purpose. A grid of styled cells would look better and be harder to compare
with what `play show` printed in the terminal; when the record is the point, the rendering should
not paraphrase it. The refused moves stay in the log table with `legal: no` and the reason,
because a log of only the moves that worked is a log you cannot audit.

Two refusals that are deliberately *not* errors: an illegal move comes back `200` with
`legal: false`, and a replay that disagrees comes back `200` with `matches: false`. Both are
answers to well-formed requests. A malformed field (`density: "lots"`) is a `400 validation`; an
unknown game is a `400` that names the three that exist.

### The consent ladder in the page

A remote model is drawn with four rungs, and each one is a real POST rather than a switch in
the browser:

| rung | shown when | the control | the call |
|------|-----------|-------------|----------|
| `consent_policy` | always | Allow cloud routing | `POST /api/settings/model.local_only {value:false}` |
| `provider` | always | Register the provider | `POST /api/models/{id}/provider` |
| `privacy` | always | Confirm what leaves the device | `POST /api/providers/{id}/privacy {data_leaves_device:true}` (after a dialog that says what that means) |
| `consent` | always | Record consent | `POST /api/providers/{id}/consent` |

The rungs come from the server (`gates`, computed next to `assert_remote_allowed`), so the
panel cannot show a green ladder for a call the workspace would refuse. A rung that cannot be
climbed yet - `privacy` before a provider exists - stays on screen with the reason instead of
disappearing, and simply has no button. `test chat` runs a real probe and shows the measurement
(`passed` with its latency, or the classified failure), never a green tick it did not earn.

Success is `{"ok": true, "data": …}`; failure is `{"ok": false, "error": {"code", "message",
"data"}}` with codes `validation`, `not_found`, `conflict`, `approval_required`,
`permission_denied`, `unauthorized`, `csrf`, `too_many_attempts`, `no_route`, `no_cors`,
`too_large`, `bad_json`, `internal`, plus the two learning refusals `try_first` (a hint before
the first attempt, matching the CLI's exit 3) and `nothing_due` (a review with nothing
scheduled).

## Configuration

| key | default | meaning |
|-----|---------|---------|
| `gui.host` | `127.0.0.1` | bind address |
| `gui.port` | `8765` | port (0 picks a free one) |
| `gui.allow_remote` | `false` | allow a non-loopback bind |
| `gui.open_browser` | `false` | open a browser on start |
| `gui.session_minutes` | `720` | cookie lifetime |
| `gui.max_body_bytes` | `1048576` | largest accepted body |

## What it does not do

* **No desktop window.** This is a local web UI, deliberately: it needs no Qt/GTK install, it
  works over SSH and in a container, and the same page is testable with `curl`. A native
  shell can wrap it later without changing anything behind it.
* **No drag-and-drop, no file browser, no editor.** Reading and writing files stays with the
  tool roots and the permission centre, and a GUI file picker is how that boundary gets
  quietly widened.
* **No live streaming.** A chat reply appears when it is finished; the trace database has the
  detail.
* **No multi-user accounts.** One token is one person - the person whose home this is.
* **Not hardened against a hostile local user.** The token protects against other origins and
  other machines; a process that can read your home can read the database and the token file.
* **No HTTP/2, no TLS.** Terminate TLS in front of it if you expose it beyond loopback; the
  GUI says so rather than pretending a bare `http://` is safe on a network.
