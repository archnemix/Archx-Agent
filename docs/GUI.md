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
| **Research** | run a question, watch coverage, read the report, see the sources *including the ones that failed* | `ResearchRunner.run` + `research verify`'s own check |
| **Search** | one query across every source, with `degraded`/`skipped` notes | `SearchService.search` |
| **Tasks** | history, timeline, artifacts, tool runs | `TaskManager` |
| **Jobs** | queue, stats, pause/resume/cancel/retry, "run one queued job" | `JobManager` + `JobRunner` |
| **Access** | pending approvals, approve/deny, active grants, revoke, capability list | `PermissionManager` |
| **Memory** | add and list memories (with the duplicate check) | `MemoryManager` |
| **Models** | the catalogue and *why* each model can or cannot run here | `ModelManager` + `runtime_availability` |
| **Learning** | goals and criteria, add an item, next-up with its `why`, one hint per click (409 before an attempt), answer and see the schedule, sessions, propose items, start a review | `LearningService` - the same path as `learning …` |

There are no placeholder controls. If a panel would need something this build does not have,
the panel is not drawn: there is no "Settings" tab that pretends, no disabled "Train" button,
and no fake progress bar. The one thing a panel does when it cannot act is *say why*, with
the command that would fix it - the same refusals as the CLI, in the same words.

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
| GET | `/api/models` | catalogue, with why each model can or cannot run |
| GET | `/api/conversations`, `/api/conversations/{id}/messages` | history |
| POST | `/api/chat` | one turn (creates a task, like the CLI) |
| GET | `/api/search?q=` | unified search |
| GET/POST | `/api/memory` | list, store |
| GET | `/api/tasks`, `/api/tasks/{id}` | history, then timeline + artifacts |
| GET | `/api/jobs`, POST `/api/jobs/{id}/{pause,resume,cancel,retry}`, POST `/api/jobs/drain` | the queue |
| GET | `/api/approvals`, POST `/api/approvals/{id}/{approve,deny}` | decisions |
| GET | `/api/permissions`, POST `/api/permissions/{id}/revoke` | grants and capabilities |
| GET/POST | `/api/research`, GET `/api/research/{id}`, GET `/api/research/{id}/report` | runs, sources, verification, the report |
| GET | `/api/learning`, `/api/learning/goals/{id}` | goals with progress, then items, next-up, sessions |
| POST | `/api/learning/goals`, `/api/learning/goals/{id}/items`, `/api/learning/goals/{id}/{plan,answer,review}`, `/api/learning/items/{id}/hint` | create a goal, add an item, plan, answer, review, reveal one hint |

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
