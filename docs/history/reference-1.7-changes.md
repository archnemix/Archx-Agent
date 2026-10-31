# archx-agent 1.7.0 — change log & root-cause report

> Historical notes from the supplied Node reference, not current 1.0.0 validation.
> Any Windows/data compatibility statements apply only to that reference, never the removed Python database.

Every change below maps to a reported problem or an optimization rule
("no UI/UX change, less lag, smart fetching"). Rule numbers in brackets
refer to `UI-RULES.md`.

---

## A. Streaming code blocks could not be scrolled, showed the top line, and the scrollbar blinked

**Root cause (exact):** `paintContent()` in `public/js/render.js` replaced the
whole `msg-content.innerHTML` on every ~50 ms paint. Every `<pre>`, table and
reasoning scroller was therefore destroyed and recreated 20×/second:
the scrollbar thumb under your pointer was a brand-new element each paint
(the blink), an in-progress scrollbar drag was killed mid-gesture (cannot
scroll), and the saved-scroll restore heuristic kept newly created blocks at
`scrollTop 0` (you saw the first line instead of the newest).

**Fix:** new incremental renderer `public/js/blocks.js` [6.3]:
- message source is chunked (fences & tables = own chunk; prose between them);
- each chunk renders once into a stable wrapper; unchanged chunks are never
  touched again (zero work, stable scrollbars);
- the actively growing code block patches only `<code>.innerHTML` inside the
  existing `<pre>` — identity, scroll position and drags survive;
- the active block auto-follows its bottom edge (shows the latest code) until
  you scroll up inside it; returning to the bottom re-arms following;
- the completion paint is in-place (the old full `renderMessages()` rebuild
  in `complete()`'s finally block jumped finished answers back to the top);
- O(active chunk) markdown+highlight work per paint instead of O(message).

Verified: `t02` (follow mid-stream, identity stable, scroll-up respected,
re-arm), `t05` (bottom preserved after completion), `t13` (10/10 rounds,
0 px drift).

## B. Reasoning box scroll problems while generating

Same rebuild bug. The reasoning panel is now a persistent `<details>` whose
`.thinking-body` text is updated in place and follows its bottom edge while
streaming; user toggling the panel open/closed wins over the auto behaviour;
after completion it collapses and relabels to "Reasoning" unless the user
opened it [6.3]. Verified in `t02`/`t05`.

## C. Providers: user choice of provider + URL, Anthropic, Gemini, keyless locals, custom models

- New native adapters: `lib/providers/anthropic.js` (Messages API, SSE
  `content_block_delta`/`thinking_delta`, system lifting, `x-api-key` +
  `anthropic-version`) and `lib/providers/gemini.js` (Generative Language
  API, `:generateContent` / `:streamGenerateContent?alt=sse`, `x-goog-api-key`,
  `thought:true` parts → reasoning, `models/` prefix stripping, chat-capable
  filtering, pagination).
- Provider editor gained a **preset select** (Anthropic, Gemini, OpenRouter,
  Groq, OpenAI, DeepSeek, Mistral, Together, Ollama/LM Studio/vLLM keyless
  locals, Custom). Choosing a preset fills name + URL + adapter; every field
  stays editable; picking an adapter with an empty URL fills its default base.
- Custom model IDs: existing Settings → Models control retained, plus a
  manual "Add ID" row inside the add-models dialog.
- Verified end-to-end against protocol mocks (`t09`) **and against the real
  Gemini endpoint with your key** (44 models listed, `gemini-3.5-flash-lite`
  answered `ARCHX_OK` in 749 ms, streaming chunks + usage meta correct).
  Note: Google currently 404s `gemini-2.5-flash-lite` for new keys although it
  is still listed by `/models` — exactly the case the new test-before-add
  flow catches.

## D. Add-provider popup: no way to add only working models, no test, no retry

- The add-models dialog now has **Test listed models** (server batch probe,
  concurrency 4), per-row ✓ works/✗ failed tags with latency, an
  **Add only working models** checkbox (checked-and-failed models are skipped
  on add), and the manual ID row.
- **Retry policy [6.7]:** `lib/retry.js` — every provider probe (connectivity,
  single model test, batch test, test-all) makes **2 attempts** by default;
  retries only transient failures (408/429/5xx, network/timeout), never 4xx.
- Same retry logic applies to Settings → Models "Test" and "Test all".
- Verified in `t02`/`t05` with a mock model that fails its first attempt
  (`flaky-once-1` passes on retry) and one that never answers
  (`broken-forever` flagged, excluded by only-working).

## E. Model profiles buried at the bottom of Models

Profiles moved to their own settings page `#/settings:profiles` (nav entry
"Profiles"); Models ends at catalog curation [7]. Zero-profile state renders a
single calm column instead of a huge empty viewer box.

## F. Profile activation default & the tiny borderless "No profile"

- Fresh installs and cleared profiles resolve to **No profile**; disabling
  advanced profiles clears the active profile server-side [6.8].
- The profile menu's "No profile" is now a first-class bordered option row
  (selected state visible), not a ghost-text button; the topbar button dims
  its label when no profile is active.

## G. Chat debug: chat API calls missing, "event" spam, opening one entry opened all, metadata `{"_encrypted": true}`

**Root cause (exact):** `Store.listLogs()` spread the *plaintext string*
returned by `keys.decryptDetailed()` into an object
(`{...'{"ts":...}'}` → character-indexed garbage). Consequences, all observed:
- encrypted entries lost `kind/provider/model` → classified as anonymous
  "event" rows in *Other* (your "many identical event calls in a minute");
- every garbage row produced the same fallback log id (`|||||`), so expanding
  one expanded all of them;
- expanding showed only `{"_encrypted": true}` because every real field was
  undefined;
- chat API calls (kind `chat`, with providerId) never matched the API filter.

**Fix:** `listLogs()` now `JSON.parse`s the decrypted payload and always
stamps row `id/ts/kind/providerId/traceId/chatId` from the journal columns, so
rows are uniquely keyed even when a payload fails to decode. Encrypted mode
now renders identically to simple mode (plus the "encrypted" badge).
Verified in `t02` (kinds real, single-row expansion, metadata decodes).

## H. Debug polling overhead (optimization, no UI change)

- New `GET /api/logs/rev` (MAX(id)+COUNT aggregate). Debug page and chat debug
  poll the revision and fetch payloads only when it changed [6.6].
- Log search precomputes a lowercase blob per entry once per fetch instead of
  `JSON.stringify`-ing the whole cache per keystroke.
- Verified in `t12`: idle debug page ships zero full payloads across poll
  cycles.

## I. Chat persistence overhead (optimization, no UI change)

- New `POST /api/state/chat` single-chat upsert. Streaming, debug-event
  stamps, sends, regenerates, edits and chat switches persist ONE chat record
  instead of rewriting every chat with every message [6.6-style hot path].
  Bulk `POST /api/state/chats` remains only for structural ops (delete/wipe).
- Verified in `t12`: streaming produces only single-chat upserts, max payload
  well under 64 KB, zero bulk rewrites.

## J. Model-list fetching (optimization, no UI change)

- `fetchModelsFor()` caches per provider with a 5 min TTL and dedupes
  in-flight requests; menu opens/hovers/settings visits no longer re-POST
  `/models` [6.5]. Explicit refresh keeps working (`refresh list`,
  `Fetch models`).
- Verified in `t12`: 10 menu opens + settings round-trips → ≤ 1 request.

## K. Odd behaviours aligned with mainstream chat UIs

- Navigation (new chat / switching) during generation is allowed; the stream
  keeps writing to its own chat and repaints resume when you return [6.4].
  Sending a second concurrent message remains blocked (single engine).
- Clicking plain text blurs the composer; any printable key refocuses it
  (ChatGrok/Grok-style) [6.1] — no caret blinking while you read.
- "Jump to latest" pill appears when you scroll away from the bottom during a
  generation [6.2].
- Persisted `pending:true` messages (interrupted streams, reloads) are
  sanitized on load, so a blinking caret can never survive a restart [6.9].
- Partial output is persisted every 1.5 s during streaming, so closing a tab
  no longer loses a half-finished answer.

## L. Spacing & visual schema

- Spacing tokens `--sp-0…--sp-8` (2…40 px) added in `base.css`; 372
  gap/padding/margin declarations across all four stylesheets normalized onto
  the scale [2].
- Light/soft themes gained syntax-highlight token overrides (the bundled hljs
  sheet is dark-only; strings/keywords washed out on white) [4].
- Field labels, modal bodies, toolbars, cards re-spaced to the schema; see
  `UI-RULES.md` for the editable rule set [9].

## M. Misc

- Version bump 1.6.10 → 1.7.0.
- `CHATDEBUG-MAP.md` remains valid; polling now revision-gated (section H).
- Test kit (not shipped): puppeteer suites `t01…t13` — 48 behavioural checks,
  protocol mocks for OpenAI/Anthropic/Gemini wires, stress suite measuring
  long tasks (worst ≈ 100 ms during triple-stream stress) and heap (≈ 3 MB).

---

## Addendum — human-eyes audit (hit-testing) & fixes found only by looking

Programmatic `el.click()` tests pass even when a human could never click the
control. A dedicated audit (`testkit/t16-audit.mjs`) walks **every visible
interactive element in 28 UI states × 3 viewports** (desktop 1440×900, laptop
1280×700, mobile 390×844), scrolls it into view like a person and verifies
with `document.elementFromPoint()` that a click at its centre lands on it.
It found four real blockers, all fixed:

1. **Toasts could swallow Send.** The toast stack sat bottom-right, exactly on
   the composer's send/stop buttons at laptop heights. Toasts moved top-centre
   under the measured page header (`--topbar-h`) and made fully
   `pointer-events: none` (they carry no interactive content), so clicks pass
   through them regardless of position.
2. **Invisible message actions ate menu clicks.** `.msg-actions` (copy/regen/
   edit) used `opacity: 0` when not hovered — still hit-testable, and because
   opacity creates a stacking context later in DOM order, the invisible bar
   painted *above opened topbar menus* and silently consumed clicks aimed at
   menu rows (reproduced: profile-menu "No profile" row unclickable whenever a
   message row sat under the menu). Fixed with `visibility: hidden` until
   hover/focus-within; same for the sidebar chat delete button.
3. **Mobile Models toolbar was unusable**: the nowrap action row squeezed the
   search input to ~4 px and pushed "Delete selected" off-screen at 390 px.
   Now wraps: search owns a row, actions share the next.
4. **Jump-to-latest pill clipped the composer** on mobile (wrapped note makes
   the composer taller). The pill now anchors to the measured composer height
   (`--composer-h`), re-measured on scroll/paint/resize/page change.

Also found by journey testing with real mouse input only
(`testkit/t17-journeys.mjs`, 16 checks):

5. **Opening a profile no longer activates it.** Previously clicking a profile
   in Settings → Profiles both opened it in the editor *and* switched chat
   routing to it (the source of "profile activation is active by default").
   Editor-open state (`setOpenProfile/editingProfile`) is now separate from
   routing-active state; routing changes only happen from the chat topbar
   menu or the explicit active-select. Creating a profile opens it in the
   editor without activating; the list marks the routing-active profile with
   a "· routing" suffix.
6. **Profiles page warms model lists** on entry (cached, deduped) so
   "Available to add" is never stuck at "not fetched yet" with the Fetch
   button living on another page.

Final state: audit clean (no control blocked anywhere), 64 behavioural checks
green, journeys 16/16 with real input events only.


---

# 1.7.1 — follow-up fixes from hands-on testing

1. **Provider form selects were empty on a fresh visit.** The preset/adapter
   dropdowns were only populated after the first New-provider/Edit/Save click,
   so on a first look they showed nothing and could not be changed (reported
   for a Mistral provider). The editor is now initialised at boot and re-synced
   whenever the adapter list changes; editing a provider shows its known
   provider in the select (matched by URL or name) and it stays changeable.
2. **Duplicate provider controls removed.** The chip row under the form
   (Anthropic/Gemini/…/vLLM buttons) did exactly what the provider select
   does; it is gone. Labels clarified: "Provider" (fills URL + protocol),
   adapter hint now explains it is the wire protocol.
3. **Selection no longer drawn as a bright white line.** Profile rows and
   system-prompt rows use a real **enable/disable switch** (green when on);
   the inset accent line was removed from option rows, prompt rows and the
   profile menu. The switch on a profile row toggles routing on/off directly.
4. **Composer clears the instant a message is sent**, not when the reply
   finishes (the old clear ran in a `.then()` after the whole stream).
5. **"Soft" theme retuned to a true Warm theme** (cream paper, amber ink,
   honey borders) — clearly distinct from Light; renamed in the UI.
6. **New "Funky" theme**: deep grape surfaces with hot-pink/teal/violet
   accents and real textures — dot-grid sidebar, zigzag ribbon topbar,
   confetti washes behind messages, gradient primary/send buttons and
   avatars, dashed code/table borders, sticker shadows on menus/modals.
   All artwork is inline CSS gradients / SVG data-URIs (offline-safe).
   Server theme whitelist + cycle + settings picker updated (4 themes).
7. **Spacing polish**: provider form fields now sit on a 16 px rhythm,
   settings body top padding 24 px, hint margins normalized.

Verification: `testkit/t25-round3.mjs` (12 checks: form init on fresh visit,
chips gone, edit shows + changes preset, composer clears mid-stream, switches
present/toggle routing, warm ≠ light, funky textures applied, 4 choices),
full regression 76 checks green, hit-test audit clean across 30 states
including the funky theme.


---

# 1.7.2 — navigation, durability, branches, scoped wipes

1. **Mobile was stuck on Settings/Debug**: those page headers had no sidebar
   toggle, so with the drawer closed there was no way back. Both headers now
   carry the hamburger (≤860 px only; desktop keeps its chat-topbar toggle).
   Also fixed: the backdrop-close handler immediately re-closed a drawer that
   the header toggle had just opened (same click), and Escape no longer hides
   the inline provider editor (legacy popup behaviour made the form look
   broken/empty after pressing Esc anywhere).
2. **Crash-safe write queue** (`lib/store.js`): every state write is
   journalled to `write-queue.jsonl` in the data area, then coalesced and
   written by a single serialized writer on the next tick; the journal is
   truncated after each drain and **replayed at boot** if a crash left entries
   (proven by `t28`: child process killed between enqueue and drain → next
   boot restores the chat). Migrations/wipes/close flush synchronously first.
   No write can be lost and the SQLite file is only touched by one writer.
3. **Concurrent chats**: streams are now per-chat (`streams` map in
   `chat.js`). Several conversations generate simultaneously; stop/send
   indicators follow the chat you are viewing; Esc/Stop stops the viewed
   chat. Sending in a chat that is already generating is the only block left.
4. **Branches you can visit**: edit-&-resend and regenerate archive the
   discarded continuation (`chats.branches`, new `branches_json` column with
   ALTER migration for old DBs). The composer shows a "⑂ n" button; its menu
   lists every archived continuation (origin edit/regenerate/current, length,
   time). Opening one archives the current tail first — **no continuation is
   ever lost**, both directions verified.
5. **Scoped wipes** (Settings → Danger zone, each with its own confirm):
   wipe everything · wipe data but keep providers & keys · wipe chats only ·
   wipe image assets · wipe video assets · wipe document assets · wipe the
   library fully. Media scopes delete asset rows *and* their files under
   `media/`. Server: `POST /api/wipe {scope}`; unit-tested per scope.
6. **Advanced model profiles are ON by default** for new installs (picker
   visible, routing still defaults to *No profile*).
7. **Dark theme lifted one step** (panels #101010/#1a1a1a/#232323, borders
   #2c2c2c/#404040) so edges stay distinct on LCD/non-OLED panels where
   near-black-on-black smeared.
8. First-run experience audited with screenshots of every screen and popup in
   zero-config state (`testkit/shots/50-…63-…`), desktop and mobile.

Verification: `t27` (16 checks: mobile toggles, concurrency, branch round
trips, journal drained, crash replay, scoped wipes via API), `t28` store unit
(10 checks incl. simulated crash replay and every wipe scope), full
regression 93 checks green, hit-test audit clean across 30 states.


---

# 1.7.3 — wipe semantics, switch design, migration FK, profile catalog

1. **"Keep providers & keys" wipe now keeps everything personal.** It deletes
   only chat-generated data (conversations, request logs, memories/embeddings,
   summaries, context state). Providers, encrypted keys, models, profiles AND
   all settings — personalization (your name, preferred name, age), agent
   name, theme, prompts, generation prefs — survive. UI copy updated
   ("Wipe chat data, keep providers & personalization").
2. **Switch redesign** (profile rows + prompt rows): the ON colour follows the
   theme accent instead of a hard-coded green (white on dark, black on light,
   amber on warm, pink on funky); track and knob are translucent shades
   (color-mix with alpha); the track carries an explicit **ON / OFF** word.
3. **Storage migration "FOREIGN KEY constraint failed" fixed.** Two causes:
   (a) migration targets were opened with a bare handle whose `modes` table
   was empty, so inserting chats violated `chats.mode_id → modes`; modes are
   now seeded on every handle that receives writes; (b) the copy-verification
   compared a raw snapshot against a normalized read-back and always failed
   once chats existed — the comparator now normalizes both sides identically
   (default-filled message fields, stable ordering, resolved system prompt).
   Unit-tested: fresh target, stale target, round-trip back, chat deletion
   (`t33`, 5/5).
4. **An active profile no longer empties model pickers.** Previously the
   picker filtered the catalog to profile members, so a provider with no
   profile entries showed "no model matches" and zero rows (your Gemini
   case). Now the full curated catalog stays visible and is rendered
   **locked/dimmed** while a profile routes (existing lock banner explains
   why), with an "in profile" tag on member models. Selecting a provider
   column still deliberately detaches the profile (direct-pick semantics);
   hovering previews without detaching.
5. **Rounded, personal controls**: radius tokens raised (12/16/8), native
   select arrows replaced with themed inline-SVG chevrons and rounded tracks
   (per-theme chevron colours), so dropdowns match the app instead of the OS.

Verification: `t34` (7 checks: personalization survives wipe, switch
themed/translucent/labelled in three themes, locked-but-visible catalog,
rounded selects), `t33` migration 5/5, full regression 115 checks green,
hit-test audit clean.
