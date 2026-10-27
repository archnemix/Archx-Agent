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
| **Work** | Search (one query, nine sources), Tasks (timeline, artifacts, reproduction), Jobs (queue, pause/resume/cancel/retry, run one) |
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
tricked into adding that header for them.

**Content.** `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src
'self'; img-src 'self' data:; connect-src 'self'; form-action 'none'; base-uri 'none';
frame-ancestors *`. No CDN, no inline script, no inline handler, no `eval`. The page may be
framed (so a desktop preview can host it); the scripts still cannot talk to anything but this
origin. `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. The `Server`
header carries the app version and not the interpreter.

**Paths.** Assets are served by exact file name from `interfaces/gui/assets/`, never by path,
so `../server.py`, `%2e%2e%2f` and a dotfile are all 404. Nothing else on disk is reachable:
the GUI has no "open this file" endpoint.

**Bodies and errors.** A request body over `gui.max_body_bytes` is refused with `413` before
it is read into the app. Every failure becomes JSON (`{"ok": false, "error": {…}}`) with a
status that means something; an unexpected exception is reported as its type and message,
never as a traceback.

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
