# Historical verification: The GUI rebuild and the Research completion model (schema v20)

This is a recorded run. See the [verification index](../VERIFICATION.md) for context.

## The GUI rebuild and the Research completion model (schema v20)

Both were run in this environment, on this branch, after `scripts/bootstrap.sh`. Nothing below
is quoted from a design document; each block is the output of the command above it.

### The page, booted in a real DOM

There is no browser in this sandbox, so the page is driven through `jsdom` instead of a
screenshot: the real `index.html` and the real `app.js` are loaded, `fetch` is answered with a
scripted workspace, and every view is opened by clicking its tab.

```text
$ node /tmp/domtest/smoke.mjs
DOM SMOKE OK (no problems)
```

What that pass covered: the gate is hidden after boot; `connected` in the sidebar foot; the
empty state and its four prompts; the conversation list; three live tool chips; the version;
the model chip; a chat turn that renders a table, a code block, a table toolbar, a warning
callout and per-message copy buttons, and leaves no thinking row behind; an existing
conversation rendered with headings, lists, a quote and a same-page-safe link; all ten views
activated with the tab marked current; a research report with a coverage bar; a learning
next-card with a hint button and the items table; a task's key/value record; the jobs,
capability, memory and models tables; six status cards and the info grid; the theme cycling
dark → light → soft → dark; the rail collapsing and being remembered in `localStorage`; every
`-refresh` button, the reload button and *new chat* clicked without throwing; and the
confirmation dialog opening, being cancelled, then confirming a deny.

### The stylesheet and the page are still honest

```text
$ .venv/bin/python -m pytest tests/test_gui_m29.py -q
85 passed
```

That file is the guard rail for the rebuild: every `id` the script touches exists, every
`-refresh` button has a listener, every class used in the page has a rule in `style.css`, every
mode has a title and a `tools` list, the two palettes and the third theme exist, the rail
collapse is `localStorage`-backed, and nothing is loaded from another origin - no `@import`, no
CDN, no inline `style=` and no `onclick=` attribute anywhere.

### Acceptance: the GUI over a real socket

```text
$ ARCHX_ALLOW_SIMULATED=1 ./scripts/acceptance_m29.sh /tmp/home-m29-ui3
...
[ok]   the page is a sidebar of modes, not a wall of tabs = 1
[ok]   the sidebar groups modes, work and control = 3
[ok]   a third, softer theme too = 1
[ok]   nothing is styled or scripted inline (the CSP forbids both) = none

M29 acceptance: 55 checks passed
```

### Research closure

```text
$ .venv/bin/python -m pytest tests/test_research_close.py -q
28 passed

$ ARCHX_ALLOW_SIMULATED=1 ./scripts/acceptance_research_close.sh /tmp/home-close3
...
[ok]   v20 is the research-closure migration = research-closure
[ok]   the run's own status is untouched = completed
[ok]   the coverage is untouched = 0.25
[ok]   closing twice is a 409 = 409
[ok]   a closed run can still be read, reported and reopened
[ok]   the close was traced = True

Research closure acceptance: 35 checks passed
```

The coverage figure is deliberately printed: it is *not* 100%, and the run is still closed,
because closing a question is the user's call rather than a threshold the tool crosses.

### The whole suite, and the other milestones' acceptance

```text
$ .venv/bin/python -m pytest --tb=short
1137 passed in 213.05s

$ ARCHX_ALLOW_SIMULATED=1 ./scripts/acceptance_m30.sh /tmp/home-m30-v20
M30 acceptance: 90 checks passed

$ ARCHX_ALLOW_SIMULATED=1 ./scripts/acceptance_m29.sh /tmp/home-m29-v20
M29 acceptance: 55 checks passed
```

`acceptance_m30.sh` gained one check (`the v19 migration is the learning one`) and its schema
assertion now reads "at least v19" instead of "exactly v19", because v20 is a later migration
and pinning a milestone to the newest number would break on every future schema change.

