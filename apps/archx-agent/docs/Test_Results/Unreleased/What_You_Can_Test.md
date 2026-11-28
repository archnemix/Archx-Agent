<!-- Purpose: The click-by-click test sheet for the twenty reported items, so each one can be checked by hand in the shipped binary. -->
# What you can test — twenty items, in order

This sheet exists because a green CI run proves that the code compiles and that
its unit tests pass; it does **not** prove that you can reach a feature with the
mouse. Every row below names the exact control, the file it writes, and what a
correct screen looks like — so a pass or a fail is a judgement you can make
without reading Rust.

Evidence for the build described here: CI run `46121930192`, green on Linux,
Windows and macOS, with **34 + 10 + 107** tests passing on each (the launcher's
own suite grew to 10 when the “why it will not open” wording got a test per
branch). Screenshots are in [`visual/`](visual/README.md). The Windows binary is
[`deliverables/Unreleased/windows/archx-ai-lab.exe`](../../../../../deliverables/Unreleased/windows/archx-ai-lab.exe),
**unsigned**.

Two things are honestly not testable from here, and are marked so wherever they
appear: a real provider reply needs your own key on your own machine (no key is
ever used in CI), and the macOS runner's display is too short to show every
screen in one frame.

---

## Items 1–10 — reported together on 2026-11-23

### 1. Empty chats no longer pile up

**Where:** Agent → **Chat** → rail **New chat**.

- With an empty draft open, press **New chat** three times. The rail keeps **one**
  empty draft, and the cursor returns to it. A second empty chat appears only
  when the current one already holds a message.
- Empty drafts never appear in the chat list and are never written to disk
  (`chats.json` is written only once a draft has a turn).

*Proof in code:* `src/app.rs` `Message::NewChat` and `blank_draft()`;
`src/app/tests.rs` — `new_chat_does_not_pile_up_empty_drafts`,
`an_empty_chat_is_never_written_to_disk`.

### 2. One provider at a time, an editable URL, and key rotation

**Where:** Agent → **Settings** → **Providers**.

- **One provider at a time.** The connection card shows a single provider name
  with a caret. Click it: a short list opens under it (each row says `key` or
  `no key`). Pick one — the list closes and the card below is about that provider
  only. This replaced the old screen that stacked every provider at once.
- **Editable URL.** *ENDPOINTS / SHOWN AND EDITABLE* lists **Chat**, **Stream**
  and **Models**, each with a URL field and **Save** / **Default**. Type a URL,
  press Save: the row's label changes from `documented` to `edited · unsaved` as
  you type and back after saving, and the status line reads “Chat saved. The next
  request uses it.” A non-https value (except loopback) is refused with a reason
  rather than silently kept.
- **Key rotation.** *KEY HEALTH* has the switch **Rotate across keys and rest
  failing ones**, on by default. Each saved key shows `ready`, `n recent
  failure(s)`, or `resting · N s` with a **Retry now** button; a key the provider
  blames rests 5 minutes (or the provider's `Retry-After`), and one other key is
  tried once.

*Proof in code:* `src/settings.rs` `provider_picker`, `endpoint_rows`,
`providers`; `src/app_provider.rs` `save_endpoint_value`, `ToggleAutoRotate`.

### 3. A models page that does not dump the list, with bulk actions and auto-disable

**Where:** Agent → **Settings** → **Models**.

- The added-models list is capped and **paged**: footer reads
  `Page 1 of N · 25 model(s) shown of M`, with **Previous** / **Next**. The
  header says `ADDED MODELS / SCROLLABLE, PAGED, BULK`.
- **Bulk:** every row has a checkbox. With two or more ticked, the bar does
  **Test selected**, **Enable**, **Disable**, **Remove**; **Tick matching** ticks
  everything the filter currently matches; **Clear** empties the selection.
- **Auto-disable:** *AUTOMATIC HEALTH* has the switch **Disable a model when the
  provider says it is gone**, plus **Re-enable all**. A disabled row stays in the
  list, greyed, with `disabled · <reason>` under it — never deleted.

*Proof in code:* `src/settings.rs` `models`; `src/app_provider.rs`
`ToggleAutoDisable`, `BulkSelectMatching`, `selected_in_order`.

### 4. Modality, free tier and remaining usage when adding a model

**Where:** Agent → **Settings** → **Models** and → **Providers**.

- Press **Refresh metadata**, then look at an added row: a dim second line gives
  modality, context window and price where a source knows them, labelled with the
  source — e.g.
  `text+image → text  ·  128k context  ·  $1.00 / $2.00 per 1M  ·  models.dev`,
  or `…  ·  free tier: 100k tokens/day  ·  models.dev` when a free tier is known.
  When no source knows a field the part is simply absent; no field is ever shown
  as `0`, and an id no source lists gets no line at all rather than a guess.
- The catalog rows carry a `free` tag for models a free-tier source lists.
- **Remaining usage:** in *Providers*, the card **KEY USAGE / WHAT THE PROVIDER
  PUBLISHES** states, per provider, exactly what it will tell you. For OpenRouter
  press **Check usage** with a key saved — it reads the documented
  `GET /api/v1/key` and shows the remaining cap, daily usage and the free-model
  request counter. For every other provider the panel says plainly that no usage
  read exists for a model key; it never invents a zero and never reports an
  account balance from a per-key cap.

*Proof in code:* `shared/src/model_meta.rs` `modality_label`; `shared/src/usage.rs`
`UsageSource`; `src/settings.rs` `usage_panel`.

### 5. Testing keeps going when you click away, and the result is saved

**Where:** Agent → **Settings** → **Models** → **Add models…**, then close the dialog.

- Tick two models, press **Test selected…  (may be billable)**, confirm, then
  press **×** to close the dialog. The run is **not** cancelled: the network work
  belongs to the app, not the dialog. Reopen the dialog to watch progress, or
  leave it closed.
- When it finishes, *SAVED TEST RESULTS / OVERWRITTEN ONLY BY A RE-RUN* shows the
  run with its id, its age, and per model where the answer came from —
  `provider answered` or `never sent` — plus the request limit at the time. The
  row survives closing the dialog, **quitting the app and restarting**.
- Only **Wipe results** (or the next run) removes it.

*Proof in code:* `src/test_journal.rs` (`nothing_in_this_module_can_end_a_run_early`,
`a_run_round_trips_with_its_provenance_and_our_timeout`); `src/app_provider.rs` run
ids and provenance; `docs/Testing_Results_Persistence.md` for the decision record.

### 6. No hard cut between the launcher and the app

**Where:** the Discover screen → **OPEN ARCHX AGENT →**, and Agent → back to the
launcher.

- The arriving screen **fades in over 220 ms while sliding 14 px** (10 px
  leaving, 6 px moving between surfaces inside one app). There is no white flash
  and no instant swap. One layer only, so no half-transparent screen steals
  clicks.
- Also true: leaving the Agent for the launcher asks the app to settle
  (`leave_app`), so nothing keeps running behind the launcher.

*Proof in code:* `src/transition.rs` `DURATION_MS = 220`, `Direction::slide`.

### 7. The “Lab preview” label is gone, and the two memory matrices are separate

**Where:** Agent → **Settings** → **Agent memory**, and launcher rail → **Lab
settings**.

- The app's section is titled **Agent memory**. It no longer claims to be a “Lab
  preview”, because it is the Agent's own scope.
- The launcher's *Lab settings* keeps its **own** persisted memory matrix
  (`settings.json` → the launcher's field), separate from the Agent's. Changing
  one never changes the other; a launcher setting cannot cap another process, and
  the screen says so.

*Proof in code:* `src/settings.rs` `Section::Lab => "Agent memory"`;
`shared/src/persist.rs` (two separate fields, with a test asserting one edit
leaves the other untouched); `src/app.rs` `LauncherScope`.

### 8. Reasoning scrolls inside a bounded panel instead of overflowing

**Where:** Agent → **Chat** → send to a reasoning model, or
`ARCHX_SNAPSHOT_CHAT=reasoning` for a deterministic look.

- The returned-reasoning body grows to **300 px** and then scrolls internally;
  the message below it does not get pushed off the screen. A short trace does not
  leave an empty 300 px box.
- Reasoning is rendered **as preformatted text**, not Markdown, so code fences and
  asterisks inside a thinking trace stay literal.
- The panel is open while streaming and collapses afterwards unless you toggled
  it yourself.

*Proof in code:* `src/agent.rs` `reasoning_size(...).min(300.0)`.

### 9. A cut-off reply says so — and the Debug page says whose limit it was

**Where:** Agent → **Chat**, then rail → **Request debug**.

- When a model stops at the Agent's **4096-token** output ceiling, the reply is
  kept, marked incomplete, and carries the line
  `Stopped at the 4096-token output limit this Agent sent · the model did not
  finish · ask for the rest`. This is not an error and no key is blamed, so
  nothing is disabled.
- The Debug journal records that request as **cut off** (not `ok`, not `failed`),
  with the diagnosis attached and the owner named.
- A transport failure names the Agent's own **45 s** request limit explicitly, so
  you can tell our timeout from the provider's.
- Both markers **survive a restart**.

**Deterministic check without a key:** launch with `ARCHX_SNAPSHOT=out.png
ARCHX_SNAPSHOT_PAGE=agent ARCHX_SNAPSHOT_CHAT=cut-off` and open
`visual/` — the fixture renders exactly that warning.

*Proof in code:* `src/app.rs` `CHAT_OUTPUT_TOKENS`; `src/agent.rs` the warning
line; `shared/src/diagnostics.rs` `output_capped`, `owner_label`,
`REQUEST_TIMEOUT_SECS`; `src/debug_page.rs`.

### 10. Text size is per area, and the two AIs' documents are in separate folders

**Where:** Agent → **Settings** → **Storage & display**; and the filesystem.

- **DISPLAY / PER AREA** has its own **A− / A+ / Reset** for **Chat text**,
  **Settings text** and **Launcher text**, plus **Chat reading width** with
  **Narrower** / **Wider**. Making chat text larger does not enlarge Settings. The
  choice is saved and applies on the next start.
- **Docs:** the Agent's documents live only in `apps/archx-agent/docs/`; the
  second app's in `apps/training/docs/`; the launcher's cross-app guides in
  `docs/` at the root. Nothing is shared or overwritten. The hand-off note moved
  into `apps/archx-agent/docs/Plan/` beside the contract it references.

*Proof in code:* `src/settings.rs` `storage`; `shared/src/persist.rs`
`DisplaySettings`; `apps/archx-agent/docs/README.md`.

---

## Items 11–20 — what the launcher now does, and how to see it

### 11. A second app can be hosted at all

Before this build the launcher's own code named the Agent in four places, so a
second app could not open even if it existed.

**Where:** the filesystem and the rail.

- In `src/app.rs`, `Page::Agent` / `AgentSettings` / `AgentDebug` are replaced by
  one data variant, `Page::App { id, surface }`. The apps the binary hosts are a
  table, `HOSTED`, one row per app.
- Adding an app is therefore four lines and **no launcher logic**:
  `apps/<id>/Cargo.toml` + the `members` line (same commit, always),
  `.register("<id>")` in `release()`, and one `HOSTED` row.

*Proof:* `src/app.rs` `mod hosting_tests`, six tests:
`a_hosted_app_page_is_data_not_an_enum_variant`,
`an_app_that_is_not_hosted_cannot_be_reached_by_a_page_id`,
`a_surface_that_an_app_does_not_offer_falls_back_to_its_first`,
`every_hosted_app_declares_at_least_one_surface`,
`a_page_id_round_trips_through_the_string_form`,
`hosting_is_what_makes_an_app_openable_not_its_status_label`.

### 12. A page id can never open an app this binary does not contain

**Where:** delete or hand-edit `settings.json`'s `last_page` to `training/home`,
then start the app.

- You land on **Discover**, not a blank screen or a crash. `Page::from_id` returns
  `Page::Home` for any app missing from `HOSTED`, and the legacy bare ids
  `agent` / `settings` / `debug` still resolve for the Agent.

*Proof:* `hosting_tests::an_app_that_is_not_hosted_cannot_be_reached_by_a_page_id`
(which asserts `Page::from_id("training/design") == Page::Home`).

### 13. The rail tells you *why* an app is not openable

**Where:** the left rail, next to each app.

- A registered app that is not `ready` shows `building`.
- An app that has code but is not in this build shows `held · not in this build`.
- Otherwise the app's own status is shown.

*Proof in code:* `src/navigation.rs` — the reason column.

### 14. A tile states whether pressing it will do anything

**Where:** Discover → **AI workspaces**.

- Above the app name the tile reads **OPEN**, **IN PROGRESS** or **HELD · NOT IN
  THIS BUILD**. A registered app whose manifest still says `preview` reads
  `IN PROGRESS` and does **not** launch — the old build used “is it live?” for
  “can I click it?”, so a preview app looked clickable and did nothing.

Pressing a tile that will **not** open is itself honest: the notice names the real
reason — *its folder and docs are in place; its code is not* for a reserved
folder, *its code exists, but this build does not host it* for a held app, *it is
registered, but not ready to open yet* otherwise.

*Proof in code:* `src/navigation.rs` `tile`; `src/app.rs` `launchable` (uses
`is_registered()`) and `App::unopenable_reason`
(`an_app_that_will_not_open_says_the_true_reason`).

### 15. The featured card names the app instead of saying “AGENT”

**Where:** the featured card on Discover.

- The button reads **OPEN <APP NAME> →**, and the wordmark art behind it is that
  app's own art. A non-Agent app no longer gets the Agent's “ARCHX AGENT”
  wordmark or its animated type.

*Proof in code:* `src/navigation.rs` `hero`; `Icon::Workspace` for non-`agent`
art.

### 16. Settings lists the apps that were deliberately held back

**Where:** launcher rail → **Lab settings** → the apps panel.

- Each held app is listed as `<name> · <status> · <id> · held out of this build`,
  with the line “Add a folder with app.toml, then release it here.” A hold is
  never silent.

*Proof in code:* `src/app.rs` — the apps panel; `shared/src/apps.rs`
`Release::Held`.

### 17. Your own apps' documents are separated by app, and the guide is written

**Where:** `apps/archx-agent/docs/Plan/Adding_An_App.md` §7b and §8.

- §7b is the host contract: the exact functions the launcher calls, what it gives
  you (text scale, memory scope, the one vault) and what it does not (live scale
  pushes into a second app, launcher-owned subscriptions).
- §8 now documents **three** gates, not two: the crate is built, the app is
  registered, and the launcher can host it — with the honest labels each gate
  produces when it is closed.

*Proof:* the file itself, plus `apps/training/docs/Registration_Answers.md` §3,
which was corrected after the workspace-manifest failure.

### 18. The second app's registration questions are answered

**Where:** `apps/training/docs/Registration_Answers.md`.

- Token namespaces (`Vault::app("training")`, accounts `hf/read` and
  `kaggle/key`, service `ai.archnemix.archxlab.app.training.v1`), isolated from
  the Agent's provider key-health; storage via `save_app` / `load_app_body` /
  `wipe_app` rather than the four Agent areas; the one-file exception for the
  workspace member and the same-commit rule; and what `SKIP: not in this
  release` means from the App harness.

*Proof:* the file itself.

### 19. The launcher and the Agent are told apart in the UI, not by luck

**Where:** any Agent surface vs any launcher screen.

- `Page::is_agent_surface()` is the single answer to “is this the Agent?”, used
  instead of the four scattered comparisons that used to exist. The Agent's own
  rail, settings and debug page render from one hosted app; the launcher's own
  settings are a different screen with different persistence.

*Proof:* `src/app.rs` `Page::is_agent_surface`, `hosted_app`.

### 20. Every claim here is repeated in the repository's own records

**Where:** the docs tree.

- [Change](../../Change.md) — the ten items, what was actually changed, and the cause
  found for the silent truncation.
- [Testing_Results_Persistence](../../Testing_Results_Persistence.md) — why test
  results outlive the dialog.
- [Plan/Adding_An_App](../../Plan/Adding_An_App.md) — the app contract and its gates.
- [Gui_Validation](Gui_Validation.md)
  — commands, logs and screenshots per OS.
- This sheet.

---

## What is *not* claimed

- No live provider request, real vault read, or hosted inference was performed in
  CI. A real answer needs your key on your machine.
- Delivery trims one thing you can hit: if an app's crate is not in the release,
  you cannot open it — by design, and the tile says so rather than lying.
- The Windows executable is unsigned; Windows SmartScreen will warn.
