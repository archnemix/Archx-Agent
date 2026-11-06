# Thinking — testing the web UI

A journal of how this got built, including the wrong turns. The finished test
kit looks tidy; the path to it did not.

## The constraint that shaped everything

The sandbox has Node and npm but no browser libraries (`libnss3`, `libgbm` and
friends are absent) and the network allow-list covers only GitHub, npm and
PyPI. So `puppeteer` cannot launch anything locally, and Google Drive is not
reachable at all.

That leaves GitHub Actions as the only place a page can actually render. It
also means results have to come back through git, because artifact downloads
are blocked here too. Hence the pattern used throughout:

1. a sentinel file (`tests/ci/run-browser-tests`) is the workflow trigger, so a
   run costs one tiny commit;
2. the workflow writes everything it produces into `test-output/`;
3. results are pushed to a `test-results` branch;
4. locally, `git checkout FETCH_HEAD -- test-output` brings them back.

Untracked output folders never survive a `git pull` (they are ignored), so the
local helper fetches the results branch directly.

## Order of work

**API suite first, on purpose.** It runs locally in two seconds and settles the
contract — response shapes, error codes, streaming format. Every browser
failure after that can be blamed on the browser layer instead of the server.

Writing it caught my own wrong assumptions immediately:

- `/api/state` returns `chats` as a bare array, not `{ chats: [...] }`.
- The stream ends with `archx.meta` *then* `archx.profile`; the last frame
  often has no trailing newline, so a naive parser drops it. (That one is a
  real lesson: parse the tail buffer.)
- Retries are for *probes* (`/test-model`, `/provider-test`), never for chat. A
  429 during streaming arrives as an in-stream error event, because the 200 has
  already been sent. The test now asserts exactly that instead of pretending a
  status code can change mid-stream.
- The Anthropic adapter appends `/v1` itself; give it a base URL that already
  ends in `/v1` and discovery 404s.

**Then the browser suite**, in two files: a visual tour (does every screen
exist at three viewports, in three themes) and an interaction suite (does the
chat actually work when you click it).

## The mistakes, in order

Each of these cost a CI run. All of them were in the tests, not the app, which
is the normal ratio when a harness is new.

1. **`npm ci --prefix tests/ci`** — not a valid install. Every browser job died
   before running. Fix: `working-directory: tests/ci`.
2. **Browser packages not resolvable.** They are installed under
   `tests/ci/node_modules`, which Node's ESM resolver never looks at from
   `tests/browser/`. Fix: `createRequire` against the harness `package.json`.
3. **Failure markers written outside the uploaded artifact.** The publish job
   then saw an empty marker and called the run green with 0 checks. This one is
   the dangerous kind of bug — a green tick on a run that tested nothing. Fix:
   each bundle writes its own marker inside its own folder, and suite steps
   fail with a non-zero exit again.
4. **`node --test tests/api/`** — the directory form is newer than Node 22's
   runner; it tried to `require` the folder. Fix: an explicit glob.
5. **`getBoundingClientRect()` serialises to `{}`** across the CDP boundary
   (its properties live on the prototype). Every click was dispatched with
   `NaN` and failed with a protocol error. Fix: copy `left/top/width/height`
   into a plain object before returning it from `page.evaluate`.
6. **Fractional mouse coordinates.** CDP wants integers. Fix: `Math.round`.
7. **`page.evaluate` cannot see Node closures.** `waitFor` called
   `page.evaluate(fn)` without forwarding the expected text, so the predicate
   threw `ReferenceError` on every poll and reported "no answer arrived" while
   the transcript plainly had it. Fix: pass an `arg`.
8. **`innerText` is empty while a row is streaming** (`white-space: pre-wrap`
   keeps it unrendered until the answer settles). Fix: read `textContent`.
9. **Picking the wrong element.** "Last `<pre>` in the document" found an older,
   one-line block; rows carry `data-idx`, so select by that. And a generated
   code sample that is not *fenced* renders as plain text — the test then
   asserted overflow on something that correctly had none.
10. **Judging layout mid-animation.** The mobile composer check ran while the
    drawer was still sliding out over it. Fix: wait for the transition.
11. **Racing a debounced save.** Settings writes debounce 250 ms; reading
    `/api/state` straight after a click sees the old value. Fix: poll for it.
12. **First-run dialog.** A fresh profile opens "A few details for your agent"
    over everything, which blocked 42 checks. Fix: `openPage` dismisses it the
    way a user would — and that is now itself a documented behaviour.

## The one real bug

The hit-test started as a list of failures with `covered by div.modal` in every
line. Dismissing the dialog cleared almost all of it. One entry survived on
mobile: a `.chip` **button** covered by `footer.composer-wrap`.

It was not a flaky overlay. On a 390×844 screen the empty state sits 9vh down
and carries five suggestion chips; the message pane does not scroll, so the
fifth chip rendered entirely behind the composer. No scroll position could
reach it. A person on a phone simply could not press it.

Fix, deliberately small: on `max-width: 860px` the empty state starts at 2vh
and the chip block caps at 46vh and scrolls. Desktop is untouched. The
before/after is visible in `test-output/visual-mobile/screenshots/mobile-01-chat.png`.

## Two judgement calls

**Scroll, then judge.** The first hit-test called anything not visible a
failure — which flagged controls on the long Models page that are perfectly
reachable by scrolling. Now each control is scrolled into view first, and if
that still leaves it under the floating composer, scrolled to the top. Only
then is "unreachable" reported. A test that cries wolf on layout length gets
disabled within a week.

**Brand-consistency assertion, not just existence.** The theme checks read the
`data-theme` attribute *and* the persisted server value, because a theme that
applies visually but does not save is a real bug class that a screenshot alone
would miss.

## Where the kit stands

84 browser checks and 20 API checks, green in CI (run 16). 51 screenshots per
run are committed with the report so the visual half can be reviewed without
re-running anything.

What it does **not** cover yet, stated plainly:

- Studio's image / speech / transcription / vision panels render and are
  hit-tested, but no test drives an actual generation through them.
- Provider creation is tested through the API, not through the Settings form
  with real typing (the form's preset dropdown and the add-models dialog are
  the next obvious targets).
- Debug page filtering and the chat-debug popover are only checked for
  rendering and reachability.
- Mobile was verified at 390×844 only; foldables and landscape are untested.

Those are the next four things I would write, in that order.
