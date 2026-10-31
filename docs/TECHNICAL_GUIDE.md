# Technical guide

## Ownership

| Location | Responsibility |
|---|---|
| bin/ | Executable entry point |
| lib/cli.js | CLI arguments, storage selection and startup |
| lib/server.js | Express routes and request orchestration |
| lib/store.js, lib/db.js | SQLite records, write queue, storage migration |
| lib/providers/ | Provider-specific wire protocols and errors |
| lib/websearch.js | Search engines and fallback chain |
| lib/modes/ | Chat-mode request preparation |
| lib/memory/ | Memory record vocabulary |
| public/index.html, public/css/ | Reference layout and component styling |
| public/js/ | Browser state, API calls, incremental rendering and interactions |
| public/vendor/ | Bundled third-party browser libraries |
| src-tauri/ | Inherited desktop wrapper; not freshly validated |
| test/ | New Node regression tests; no old Python tests |
| scripts/ | Development-only browser verification |
| docs/FEATURE_REQUIREMENTS.md | Complete features, acceptance boundaries and current gaps |

Do not split or rewrite the reference UI just to change module counts. Keep new work
small and feature-owned. Large inherited server/store/ui modules need incremental
extraction with behaviour checks, not another wholesale implementation.

## Verification

`npm test` uses Node's built-in test runner. Socket tests use local provider fixtures
and disposable SQLite directories. They require no keys or network model downloads.
`npm pack --dry-run` checks the source package. Browser verification uses optional
Playwright/Chromium installed outside runtime dependencies; see scripts/browser-check.mjs.
No desktop build, native Windows run or live search is claimed by these checks.

## Version and persistence boundaries

package.json, the root lockfile entries, Cargo.toml and tauri.conf.json must agree on
1.0.0. Dependency versions and database schema versions are not product versions.
Historical source comments retain their original version labels. Old release-note
files were removed from the active documentation; they remain in Git history.

This app does not open the Python schema-31 workspace. The inherited Node schema and
storage migration remain in place. Test against a new data directory. The desktop
wrapper currently depends on a globally installed command/npx fallback and a fixed
port; audit that flow before shipping an installer. Remote server authentication,
CSRF/origin protection and safe web-page fetching need a separate security pass.

### Run the optional browser check

Install Playwright locally without changing product dependencies:

```sh
npm install --no-save --package-lock=false playwright
npx playwright install chromium
npm run test:browser
```

The check starts temporary loopback HTTP servers, exercises the real UI/API/store
against a local fake provider, closes everything, and removes its data directory.
Screenshots go to ignored `test-results/browser`. `PLAYWRIGHT_MODULE` may name an
absolute installed module path; `BROWSER_OUTPUT` can move the screenshots. The
optional `SPARTICUZ_MODULE` supports a preinstalled serverless Chromium in sandboxes.
Neither test server uses the ordinary user store or configured provider credentials.

New small modules own chat-save scheduling (`chat-persistence.mjs`), stream framing
(`chat-events.mjs`), failure state (`chat-failure.mjs`) and persisted message extras
(`lib/message-state.js`). Native OpenAI-compatible streams now require an explicit
completion marker or finish reason; other adapters still need the equivalent audit.
Save failures are reported, but failed writes are not automatically retried.
