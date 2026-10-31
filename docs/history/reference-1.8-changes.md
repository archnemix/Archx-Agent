# Archx Agent 1.8.0 — release notes & usage

> Historical notes from the supplied Node reference, not current 1.0.0 validation.
> Any Windows/data compatibility statements apply only to that reference, never the removed Python database.

Local AI workspace: SQLite persistence, pluggable providers (OpenAI-compatible,
Google Gemini, Anthropic), capability-typed multimodal studio, keyless web
search, and a desktop (Tauri) shell. Keys are AES-256-GCM encrypted at rest.

## Install & run (web UI)

Requirements: Node.js ≥ 22 (uses the built-in `node:sqlite`).

```bash
npm install
npx archx-agent webui            # or: node bin/archx-agent.js webui
# options:
#   --port 8080        bind port (default 4173, auto-increments if busy)
#   --host 0.0.0.0     bind host (default 127.0.0.1)
#   --data-dir PATH    where the SQLite journal + media live (asked on first start)
```

Open http://127.0.0.1:4173. On first start you choose a data area (folder or
memory-only). Change it later in Settings → Storage; moves are
copy → verify → switch → delete, and choosing the *current* folder now shows a
friendly “already the current data area” note instead of an error.

## Desktop app (Tauri)

`src-tauri/` contains the wrapper: it spawns `archx-agent webui`, waits for the
port, and shows the UI in a native window. On a machine with Rust installed:

```bash
npm install
cargo tauri dev        # develop
cargo tauri build      # produce installers (.msi / .dmg / .deb / .AppImage)
```

The shell falls back to `npx archx-agent` when the binary is not on PATH and
kills the server when the window closes.

## What changed in 1.8.0 (the 18 fixes)

1. **Add only working models** — the import dialog auto-runs parallel tests with
   a live panel (model being probed, sent/returned status, done/total, working,
   failed, remaining, Stop button). “Add checked models” adds passed + untested
   and skips failed; failed rows are auto-unchecked after a run.
2. **Multimodal capability areas** — every model carries capabilities
   (chat / vision / image-gen / video / tts / stt). Studio shows four surfaces
   (Image generation, Text→speech, Speech→text, Vision·OCR) and each lists only
   models that can do that job; non-chat models never appear in the chat picker.
3. **Chat pinning + multi-delete** — pin icon per chat (pinned float to the top),
   Select mode with select-all, per-chat checkboxes and “Delete (n)”.
4. **Temporary chats** — Temp mode in the sidebar: chats created while it is on
   are ephemeral (not persisted) and are labelled in the list.
5. **Provider deletion policies** — deleting a provider asks: *Keep models,
   pause them* (entries stay parked in profiles and resume on re-attach, one
   click) or *Remove provider and its models*. No more “provider not found”
   crashes from parked entries.
6. **Tauri desktop wrapper** — see above.
7. **Per-capability test documents** — probes exercise the surface a model
   advertises (text echo, 1×1-pixel vision image, tiny TTS, reachability STT,
   image prompt). The Probe dialog shows the default document, lets you save a
   custom JSON body per model, and restore the default.
8. **Parallel testing, no caps** — batch runs use an 8–16 worker pool with no
   artificial model limit (OpenRouter-scale lists test fully); the import dialog
   has a search-text filter plus Select all / Select matching / Clear all.
9. **Profiles & system prompts** — creating either opens a popup asking for
   name + enable + short description; profile names are editable afterwards
   (Rename); names are unique-enforced.
10. **UI redesign** — clean black/white dark theme + clean white light theme +
    optional soft theme; multi-page navigation (Chat / Studio / Memory / Debug /
    Settings); the default system prompt ships with `{username}`, `{age}`,
    `{preferredName}`, `{agentName}` variables and stays editable.
11. **Web search tool** — the composer “Web” toggle (every mode). Keyless engine
    chain from dsh-free-web-search (Bing → DuckDuckGo → SearXNG by default) with
    user-ordered priority, max-results setting and a “Test engines” diagnostics
    panel in Settings → Tools. Bing/DDG click-tracker URLs are unwrapped.
12. **One log per batch** — provider-wide and import runs write ONE
    `model-test-batch` / `provider-test-all` row; per-model rows only for
    individual user tests. Retention is configurable per log family in
    Settings → Danger zone (API / tools / config / everything days).
13. **Memory page** — live storage usage (database, chats, logs, image/video/
    document assets, memories, library total) with per-category Wipe/Clear and
    a global total pill.
14. **Multi-view navigation** — single sidebar, five views, hash-routed
    (`#/chat`, `#/studio`, `#/memory`, `#/debug`, `#/settings:section`).
15. **Funky theme removed.**
16. **Switches rebuilt & pixel-tested** — the ON/OFF control was re-implemented
    as a standalone 40×22 geometry (16px knob, 2px inset, 18px travel),
    screenshot-benched at 1×/2× in `public/toggle-test.html` until clean, then
    integrated. No in-track text, no smear.
17. **Screenshot audit** — every page and dialog captured at 1× and 2× (plus a
    screencast interaction video) and inspected; issues fixed along the way
    (broken gear-icon SVG path, clipped probe JSON, missing vendor libs).
18. **Same-folder migration** — choosing the current data area is a calm no-op
    with a friendly message; a missing `dir` payload can no longer silently
    switch to memory-only and delete data; verification compares providers
    order-insensitively so post-add moves verify correctly.

## Backend surface worth knowing

- `POST /api/providers/:id/test-models` — parallel probe list (concurrency ≤16).
- `POST /api/providers/:id/test-batch-log` — one log row for a UI run.
- `POST /api/providers/:id/generate-image | speech | transcribe` — studio tools.
- `GET  /api/memory-stats` — storage usage categories.
- `GET  /api/tools/web-search/test` — engine diagnostics.
- `POST /api/storage` — `{dir: string|null}` data-area move (copy/verify/switch/delete).
- Mistral quirks handled: `/audio/voices` discovery when a voice name is
  rejected, and JSON `audio_data` (base64) speech responses unwrapped.

## Testing performed

Real-key end-to-end tests (Gemini + Mistral): model listing, chat (stream +
non-stream), web-search-grounded chat, TTS→STT round-trip with exact-text
return, image-gen wiring (quota-limited upstream), parallel batch probes,
provider pause/re-attach resume, storage moves with verification, retention
persistence. UI verified by scripted browser runs: every page + dialog
screenshotted (1×/2×), switches pixel-measured, interaction screencast encoded
to video and frame-checked.
