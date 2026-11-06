# CI harness

The sandbox this project is developed in has no browser libraries, so anything
that needs a real page runs on GitHub Actions. The workflow commits its output
back to the branch, which is how the results become readable here.

## Triggering a run

```bash
node tests/ci/run-remote.mjs        # push the sentinel, wait, pull results
```

`run-remote.mjs` writes a timestamp into `tests/ci/run-browser-tests` — that
file's path is the workflow trigger, so one tiny commit starts a run without
touching app code. When the run finishes, the bot commits `test-output/` and the
script rebases it into the working tree.

## Reading the results

| file | what it holds |
| --- | --- |
| `test-output/SUMMARY.md` | pass/fail table, every failure with its message |
| `test-output/latest.json` | machine-readable digest of the last run |
| `test-output/screenshots/*.png` | one shot per UI state, three viewports |
| `test-output/<suite>.log` | raw TAP output for the failing suite |

## Layout

- `tests/api/` — HTTP contract tests, runnable locally (`npm test`).
- `tests/browser/` — Puppeteer suites; need `BROWSER_TESTS=1`.
- `tests/mock-upstream/` — the fake provider that speaks OpenAI, Anthropic and
  Gemini wire formats. No test ever reaches a real API.
- `tests/ci/` — workflow plumbing and the summary writer. Its `node_modules`
  is separate from the app's so Puppeteer never ships with the product.
