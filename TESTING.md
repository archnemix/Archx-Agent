# How the app was tested

Two suites, one rule: nothing here reaches the internet, and nothing clicks a
button that a person could not click.

Run it locally with `npm test` (API suite, ~2 s). The browser suites need a
Chromium build, so they run on GitHub Actions — see `tests/ci/README.md`.

## What is covered

| area | checks | where |
| --- | ---: | --- |
| HTTP contract (state, providers, models, chat, logs, storage) | 20 | `tests/api/` |
| Visual tour: 5 pages × 8 settings tabs × 3 themes × 3 viewports | 51 | `tests/browser/visual-tour.test.mjs` |
| Real-input interaction: send, stop, markdown, scroll, theme, sidebar, keys, mobile drawer | 10 | `tests/browser/interaction.test.mjs` |
| Hit-testing every visible control in 8 states × 3 viewports | 24 | `tests/browser/interaction.test.mjs` |
| **total** | **84 browser + 20 API** | |

The three wire protocols are covered too: the mock upstream speaks
OpenAI-compatible, Anthropic Messages and Gemini Generative Language, and the
API suite drives a real streaming chat through each adapter.

## How the browser side works

- **No mocks in the page.** The real server boots in a temp data area
  (`ARCHX_DATA_DIR` + `XDG_CONFIG_HOME`), so test runs never touch a real chat
  database.
- **The fake provider does the mocking**, not the front-end. Streaming, retries,
  errors and reasoning deltas are exercised through the app's own code paths.
- **Input is real.** `page.mouse.click()` at integer coordinates, `keyboard.type`
  with a delay. `el.click()` from inside the page is banned in these files,
  because it passes even when a fixed toolbar sits on top of the button.
- **Hit-testing is geometric.** For each visible control we scroll it into view,
  then ask `document.elementFromPoint()` at its centre what is actually there.
  A control that cannot be reached after a sensible scroll is a failure, and the
  error names the overlay that swallows it (`covered by footer.composer-wrap`).

## Bugs this found in the shipped app

1. **Suggestion chips unreachable on phones** (fixed in `public/css/chat.css`).
   Five chips plus the 9vh top margin were taller than the message pane, which
   never scrolls. At 390×844 the last chip rendered entirely behind the
   composer: no scroll position could reach it. The empty state now starts
   higher on small screens and the chip block caps its height and scrolls.

Nothing else broke. Twelve of the seventeen CI runs were spent fixing the test
kit itself — see `THINKING.md` for that list, it is the more useful half of the
story.

## Reading a failure

`test-output/SUMMARY.md` has one row per suite and one line per failure.
Screenshots from the same run are under `test-output/*/screenshots/`, named
after the state they show, so a visual regression can be eyeballed without
re-running anything.

Failures carry evidence rather than a stack trace: a chat check that times out
prints the transcript, the composer value, the open dialogs and the toasts at
that moment. That is what turned "no answer arrived" into "the answer was
there, the wait was reading the wrong property".

## Where the kit lives

```
tests/api/contract.test.mjs        HTTP contract, runs locally
tests/browser/visual-tour.test.mjs tour + screenshots, per viewport
tests/browser/interaction.test.mjs real-input chat flow + hit-testing
tests/browser/support.mjs          browser plumbing (click, wait, hit-test)
tests/mock-upstream/server.mjs     fake provider: OpenAI, Anthropic, Gemini
tests/helpers/                     boot the app, assertions, SSE reader
tests/ci/                          workflow helper, summariser, harness deps
.github/workflows/browser-tests.yml
```
